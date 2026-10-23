"""Отрисовка свёрстанных страниц: бумага, чернила, соединения, экспорт."""

import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .layout import Glyph, Layout, Page, Settings
from .profile import SAMPLE_DPI, Profile
from .units import mm_to_px

GRID_COLOR = np.array([168, 200, 232], np.float32)
MARGIN_COLOR = np.array([226, 104, 118], np.float32)
PAPER_COLOR = np.array([250, 250, 246], np.float32)
MISSING_COLOR = np.array([255, 243, 170], np.float32)


def _paper(s: Settings, rng: np.random.Generator) -> np.ndarray:
    W, H = s.page_mm
    w, h = int(round(mm_to_px(W, s.dpi))), int(round(mm_to_px(H, s.dpi)))
    page = np.empty((h, w, 3), np.float32)
    page[:] = PAPER_COLOR
    if s.paper_texture:
        low = cv2.resize(rng.normal(0, 1, (12, 9)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
        page += (low * 2.5)[..., None]
        page += rng.normal(0, 1.6, (h, w, 1)).astype(np.float32)

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


def normalized_image(profile: Profile, sample) -> np.ndarray:
    """Образец с толщиной линии, приведённой к общей для профиля.

    Образцы с разных страниц скана выходят то тоньше, то жирнее (свет,
    резкость). Настоящая ручка пишет одной толщиной, поэтому слишком жирные
    образцы слегка «сужаем», а слишком тонкие — утолщаем."""
    key = f"{sample.id}:norm"
    if key not in profile._cache:
        a = profile.image(sample)
        target = mm_to_px(profile.params.stroke_mm, SAMPLE_DPI)
        k = (sample.stroke_px - target) / 2.0 if sample.stroke_px > 0 else 0.0
        r = int(round(abs(k)))
        if r >= 1:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
            a = cv2.erode(a, kernel) if k > 0 else cv2.dilate(a, kernel)
        profile._cache[key] = a
    return profile._cache[key]


def _draw_glyph(page: np.ndarray, g: Glyph, profile: Profile, s: Settings, ink: np.ndarray) -> None:
    src = normalized_image(profile, g.sample) if not g.fallback else profile.image(g.sample)
    ppm = mm_to_px(1.0, s.dpi)
    c, sn = math.cos(g.rot), math.sin(g.rot)
    lin = ppm * g.scale * np.array([[c, -sn], [sn, c]]) @ np.array([[1.0, -g.shear], [0.0, 1.0]])
    origin = np.array([g.x * ppm, g.y * ppm]) - lin @ np.array([0.0, g.sample.baseline])
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
    width = max(1, int(round(c.width_mm * ppm)))
    cv2.polylines(canvas, [poly], False, 255, width, cv2.LINE_AA, shift)
    # Края отсканированных штрихов мягкие — соединение не должно быть резче букв.
    soft = cv2.GaussianBlur(canvas.astype(np.float32) / 255.0, (0, 0), max(0.5, 0.08 * ppm))
    _blend(page, soft, int(x0), int(y0), ink, c.opacity)


def render_page(page: Page, profile: Profile, s: Settings, index: int = 0) -> Image.Image:
    rng = np.random.default_rng((s.seed, index))
    canvas = _paper(s, rng)
    base_ink = np.array(s.ink_color or profile.params.ink_color, np.float32)
    for c in page.connectors:
        _draw_connector(canvas, c, s, base_ink)
    for g in page.glyphs:
        ink = np.clip(base_ink + rng.normal(0, 4, 3), 0, 255).astype(np.float32)
        _draw_glyph(canvas, g, profile, s, ink)
    return Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8), "RGB")


def render(layout: Layout, profile: Profile) -> list[Image.Image]:
    return [render_page(p, profile, layout.settings, i) for i, p in enumerate(layout.pages)]


def save_pdf(images: list[Image.Image], path: str | Path, dpi: int) -> None:
    if not images:
        raise ValueError("Нет страниц для сохранения")
    images[0].save(str(path), "PDF", resolution=dpi, save_all=True, append_images=images[1:])


def save_pngs(images: list[Image.Image], stem: str | Path) -> list[Path]:
    stem = Path(stem)
    out = []
    for i, im in enumerate(images, 1):
        p = stem.with_name(f"{stem.stem}_{i:02d}.png")
        im.save(p)
        out.append(p)
    return out
