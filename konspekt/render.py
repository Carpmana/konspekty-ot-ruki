"""Отрисовка свёрстанных страниц: бумага, чернила, соединения, экспорт."""

import io
import math
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .layout import Glyph, Layout, Page, Settings
from .profile import SAMPLE_DPI, Profile
from .units import mm_to_px
from .vector import fill, trace

GRID_COLOR = np.array([168, 200, 232], np.float32)
MARGIN_COLOR = np.array([226, 104, 118], np.float32)
PAPER_COLOR = np.array([250, 250, 246], np.float32)
MISSING_COLOR = np.array([255, 243, 170], np.float32)
HD_MIN_DPI = 200  # с этой плотности страницы буквы берутся в 600 dpi (PDF, печать)
WHITE = np.array([255, 255, 255], np.float32)


def _paper(s: Settings, rng: np.random.Generator) -> np.ndarray:
    W, H = s.page_mm
    w, h = int(round(mm_to_px(W, s.dpi))), int(round(mm_to_px(H, s.dpi)))
    page = np.empty((h, w, 3), np.float32)
    page[:] = WHITE if s.solid_print else PAPER_COLOR
    if s.paper_texture and not s.solid_print:
        low = cv2.resize(rng.normal(0, 1, (12, 9)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
        low *= 2.5
        page += low[..., None]
        del low
        page += rng.standard_normal((h, w, 1), dtype=np.float32) * np.float32(1.6)

    def hline(y_mm: float, color, width: int = 1, alpha: float = 0.85):
        y = int(round(mm_to_px(y_mm, s.dpi)))
        page[y:y + width] = page[y:y + width] * (1 - alpha) + color * alpha

    def vline(x_mm: float, color, width: int = 1, alpha: float = 0.85):
        x = int(round(mm_to_px(x_mm, s.dpi)))
        page[:, x:x + width] = page[:, x:x + width] * (1 - alpha) + color * alpha

    if s.paper == "grid":
        k = 0
        while k * s.grid_mm < H:
            hline(k * s.grid_mm, GRID_COLOR)
            k += 1
        k = 0
        while k * s.grid_mm < W:
            vline(k * s.grid_mm, GRID_COLOR)
            k += 1
    elif s.paper == "lines":
        y = s.margin_top_mm + s.line_pitch_mm
        while y < H - 2:
            hline(y, GRID_COLOR)
            y += s.line_pitch_mm
    if s.margin_line and s.paper != "blank":
        vline(s.margin_left_mm, MARGIN_COLOR, width=max(1, s.dpi // 100))
    return page


def _blend(page: np.ndarray, alpha: np.ndarray, x0: int, y0: int, color: np.ndarray, opacity: float) -> None:
    h, w = alpha.shape
    H, W = page.shape[:2]
    ax0, ay0 = max(0, -x0), max(0, -y0)
    px0, py0 = max(0, x0), max(0, y0)
    px1, py1 = min(W, x0 + w), min(H, y0 + h)
    if px1 <= px0 or py1 <= py0:
        return
    a = alpha[ay0:ay0 + (py1 - py0), ax0:ax0 + (px1 - px0)][..., None] * opacity
    roi = page[py0:py1, px0:px1]
    roi *= 1 - a
    roi += color * a


def normalized_image(profile: Profile, sample, hd: bool = False, weight: float = 1.0) -> tuple[np.ndarray, int]:
    """Образец с толщиной линии, приведённой к общей для профиля, и во
    сколько раз он плотнее 300 dpi.

    Образцы с разных страниц скана выходят то тоньше, то жирнее (свет,
    резкость). Настоящая ручка пишет одной толщиной, поэтому слишком жирные
    образцы слегка «сужаем», а слишком тонкие — утолщаем. Общая толщина —
    как на скане; weight плавно делает её тоньше (<1) или толще (>1).

    hd: взять образец в 600 dpi — для печати и PDF. Предпросмотр мелкий,
    ему хватает 300 dpi, и так быстрее."""
    weight = _weight(weight)
    key = f"{sample.id}:norm:{int(hd)}:{weight}"
    if key not in profile._cache:
        a, f = profile.print_image(sample) if hd else (profile.image(sample), 1)
        target = mm_to_px(profile.params.stroke_mm, SAMPLE_DPI) * weight
        have = sample.stroke_px if sample.stroke_px > 0 else target / weight
        profile._cache[key] = (offset_stroke(a, (target - have) / 2.0 * f), f)
    return profile._cache[key]


def _weight(weight: float) -> float:
    return round(float(np.clip(weight, 0.3, 3.0)), 2)


def offset_stroke(a: np.ndarray, d: float) -> np.ndarray:
    """Сдвигает край линии на d пикселей наружу (d < 0 — внутрь), с долями
    пикселя: толщина меняется плавно, а не ступеньками в целый пиксель.
    Край остаётся сглаженным на один пиксель."""
    if abs(d) < 0.05:
        return a
    ink = (a >= 0.5).astype(np.uint8)
    if not ink.any():
        return a
    pad = int(np.ceil(max(d, 0.0))) + 2
    ink = cv2.copyMakeBorder(ink, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    inside = cv2.distanceTransform(ink, cv2.DIST_L2, 5)
    outside = cv2.distanceTransform(1 - ink, cv2.DIST_L2, 5)
    signed = np.where(ink > 0, inside - 0.5, 0.5 - outside)  # >0 внутри, край — 0
    out = np.clip(signed + d + 0.5, 0.0, 1.0).astype(np.float32)
    return out[pad:-pad, pad:-pad]


def glyph_contours(profile: Profile, sample, smoothness: float = 0.5, fallback: bool = False,
                   weight: float = 1.0) -> list[np.ndarray]:
    """Гладкие контуры образца в пикселях 300 dpi (см. vector.trace).
    Обводим образец в 600 dpi с выровненной толщиной линии."""
    smoothness = round(float(np.clip(smoothness, 0.0, 1.0)), 2)
    weight = _weight(weight)
    key = f"{sample.id}:vec:{smoothness}:{weight}"
    if key not in profile._cache:
        if fallback:
            a, f = profile.image(sample), 1
        else:
            a, f = normalized_image(profile, sample, hd=True, weight=weight)
        profile._cache[key] = trace(a, smoothness, f)
    return profile._cache[key]


def _glyph_transform(g: Glyph, s: Settings) -> tuple[np.ndarray, np.ndarray]:
    """Перевод координат образца (пиксели 300 dpi) в пиксели страницы."""
    ppm = mm_to_px(1.0, s.dpi)
    c, sn = math.cos(g.rot), math.sin(g.rot)
    lin = ppm * g.scale * np.array([[c, -sn], [sn, c]]) @ np.array([[1.0, -g.shear], [0.0, 1.0]])
    origin = np.array([g.x * ppm, g.y * ppm]) - lin @ np.array([0.0, g.sample.baseline])
    return lin, origin


def _draw_glyph(page: np.ndarray, g: Glyph, profile: Profile, s: Settings, ink: np.ndarray) -> None:
    if s.solid_lines:
        lin, origin = _glyph_transform(g, s)
        alpha, x0, y0 = fill(glyph_contours(profile, g.sample, s.smoothness, g.fallback, s.weight), lin, origin)
        if g.fallback and s.highlight_missing:
            _blend(page, np.full_like(alpha, 0.6), x0, y0, MISSING_COLOR, 1.0)
        _blend(page, alpha, x0, y0, ink, g.opacity)
        return
    if g.fallback:
        src, f = profile.image(g.sample), 1
    else:
        src, f = normalized_image(profile, g.sample, hd=s.dpi >= HD_MIN_DPI, weight=s.weight)
    lin, origin = _glyph_transform(g, s)
    lin = lin / f  # координаты образца в GlyphSample — в пикселях 300 dpi
    k = math.sqrt(abs(float(np.linalg.det(lin))))
    if k < 0.9:
        # Сильное уменьшение одним warpAffine теряет тонкие линии (берёт
        # пиксели через один): сначала честно уменьшаем по площади.
        src = cv2.resize(src, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        lin = lin / k
    h, w = src.shape
    corners = np.array([[0, 0], [w, 0], [0, h], [w, h]], float) @ lin.T + origin
    x0, y0 = np.floor(corners.min(axis=0)).astype(int) - 1
    x1, y1 = np.ceil(corners.max(axis=0)).astype(int) + 1
    M = np.hstack([lin, (origin - [x0, y0])[:, None]]).astype(np.float32)
    warped = cv2.warpAffine(src, M, (int(x1 - x0), int(y1 - y0)), flags=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    if g.fallback and s.highlight_missing:
        _blend(page, np.full_like(warped, 0.6), int(x0), int(y0), MISSING_COLOR, 1.0)
    _blend(page, warped, int(x0), int(y0), ink, g.opacity)


def _stroke_edge(canvas: np.ndarray, s: Settings) -> np.ndarray:
    """Край нарисованного штриха под стать буквам: у гладких букв чёткий,
    у букв как в скане — мягкий (соединение не должно быть резче букв)."""
    a = canvas.astype(np.float32) / 255.0
    if s.solid_lines:
        return a
    return cv2.GaussianBlur(a, (0, 0), max(0.5, 0.08 * mm_to_px(1.0, s.dpi)))


def _draw_connector(page: np.ndarray, c, s: Settings, ink: np.ndarray) -> None:
    ppm = mm_to_px(1.0, s.dpi)
    p0 = np.array(c.p0) * ppm
    p3 = np.array(c.p1) * ppm
    d = p3 - p0
    sag = 0.25 * ppm  # штрих слегка провисает, как у настоящего соединения
    p1 = p0 + [d[0] * 0.45, sag]
    p2 = p3 - [d[0] * 0.45, -sag * 0.5]
    t = np.linspace(0, 1, 16)[:, None]
    pts = (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3
    x0, y0 = np.floor(pts.min(axis=0)).astype(int) - 6
    x1, y1 = np.ceil(pts.max(axis=0)).astype(int) + 6
    canvas = np.zeros((y1 - y0, x1 - x0), np.uint8)
    shift = 4  # субпиксельная точность
    poly = np.round((pts - [x0, y0]) * (1 << shift)).astype(np.int32)
    width = max(1, int(round(c.width_mm * s.weight * ppm)))
    cv2.polylines(canvas, [poly], False, 255, width, cv2.LINE_AA, shift)
    _blend(page, _stroke_edge(canvas, s), int(x0), int(y0), ink, c.opacity)


def _draw_line(page: np.ndarray, ln, s: Settings, ink: np.ndarray) -> None:
    ppm = mm_to_px(1.0, s.dpi)
    pts = np.array(ln.points, float) * ppm
    x0, y0 = np.floor(pts.min(axis=0)).astype(int) - 6
    x1, y1 = np.ceil(pts.max(axis=0)).astype(int) + 6
    canvas = np.zeros((y1 - y0, x1 - x0), np.uint8)
    shift = 4
    poly = np.round((pts - [x0, y0]) * (1 << shift)).astype(np.int32)
    width = max(1, int(round(ln.width_mm * s.weight * ppm)))
    cv2.polylines(canvas, [poly], False, 255, width, cv2.LINE_AA, shift)
    _blend(page, _stroke_edge(canvas, s), int(x0), int(y0), ink, ln.opacity)


def render_page(page: Page, profile: Profile, s: Settings, index: int = 0) -> Image.Image:
    rng = np.random.default_rng((s.seed, index))
    canvas = _paper(s, rng)
    base_ink = np.array(s.ink_color or profile.params.ink_color, np.float32)
    if s.solid_print:
        _draw_solid(canvas, page, profile, s, print_ink(base_ink))
    else:
        for c in page.connectors:
            _draw_connector(canvas, c, s, base_ink)
        for ln in page.lines:
            _draw_line(canvas, ln, s, base_ink)
        for g in page.glyphs:
            ink = np.clip(base_ink + rng.normal(0, 4, 3), 0, 255).astype(np.float32)
            _draw_glyph(canvas, g, profile, s, ink)
    np.clip(canvas, 0, 255, out=canvas)  # на месте: при печати страница большая
    return Image.fromarray(canvas.astype(np.uint8), "RGB")


def print_ink(ink: np.ndarray) -> np.ndarray:
    """Цвет чернил для принтера. Почти чёрный становится чистым чёрным:
    его принтер кладёт сплошным слоем, а тёмно-серый рисует растром из
    точек."""
    return np.zeros(3, np.float32) if ink.max() < 64 else ink


def _draw_solid(canvas: np.ndarray, page: Page, profile: Profile, s: Settings, ink: np.ndarray) -> None:
    """Чернила для принтера: каждый пиксель либо бумага, либо чернила в
    полную силу.

    Принтер не умеет печатать серый или полупрозрачный цвет: он заменяет
    его растром — частыми точками краски с просветами. На экране буквы с
    прозрачностью 0.93 и мягким краем выглядят живыми, а на бумаге
    получаются в крапинку, с пыльной каймой. Поэтому здесь сначала
    собирается, где на странице есть чернила, и по порогу половины
    закрашивается одним цветом. При 400 dpi ступенька края — 0.06 мм,
    глазом её не видно."""
    cover = np.zeros(canvas.shape[:2] + (1,), np.float32)
    one = np.ones(1, np.float32)
    ps = replace(s, highlight_missing=False)
    for c in page.connectors:
        _draw_connector(cover, replace(c, opacity=1.0), ps, one)
    for ln in page.lines:
        _draw_line(cover, replace(ln, opacity=1.0), ps, one)
    for g in page.glyphs:
        _draw_glyph(cover, replace(g, opacity=1.0), profile, ps, one)
    canvas[cover[..., 0] >= 0.5] = ink


def render(layout: Layout, profile: Profile) -> list[Image.Image]:
    return [render_page(p, profile, layout.settings, i) for i, p in enumerate(layout.pages)]


def save_pdf(images: list[Image.Image], path: str | Path, dpi: int) -> None:
    """Страницы в PDF без потерь (PNG внутри). Pillow кладёт картинки в PDF
    как JPEG: вокруг букв появлялся «снег» из серых точек, и принтер честно
    печатал его вкраплениями."""
    import pymupdf

    if not images:
        raise ValueError("Нет страниц для сохранения")
    with pymupdf.open() as doc:
        for im in images:
            page = doc.new_page(width=im.width * 72.0 / dpi, height=im.height * 72.0 / dpi)
            buf = io.BytesIO()
            im.save(buf, "PNG", optimize=False, compress_level=6)
            page.insert_image(page.rect, stream=buf.getvalue())
        doc.save(str(path), deflate=True)


def save_pngs(images: list[Image.Image], stem: str | Path) -> list[Path]:
    stem = Path(stem)
    out = []
    for i, im in enumerate(images, 1):
        p = stem.with_name(f"{stem.stem}_{i:02d}.png")
        im.save(p)
        out.append(p)
    return out
