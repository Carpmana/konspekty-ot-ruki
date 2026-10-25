"""Импорт заполненного бланка: поиск меток, выравнивание, вырезка образцов.

Работает и со сканом, и с фото с телефона. Чернила отделяются от бумаги по
красному каналу: синие и чёрные чернила в нём тёмные, а оранжевые
направляющие бланка почти белые.
"""

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from .template import (ARUCO_DICT, BASELINE_FROM_TOP_MM, DPI, LABEL_H_MM, MAX_PAGES, XHEIGHT_GUIDE_MM, Cell,
                       all_pages, marker_ids, page_marker_centers_px, render_page)
from .units import A4_MM, mm_to_px

CELL_INSET_MM = 1.6
MIN_INK_PX = 60
MIN_COMPONENT_PX = 25
GUIDE_DASH_H_MM = 0.7   # штрих направляющей тоньше любой буквы
GUIDE_TOL_MM = 1.2
SPECK_PX = 120          # мелкая соринка вдали от букв: точка, пылинка
SPECK_DIST_MM = 3.0
EDGE_PX = 3             # полоса у края клетки, где чернила значат «буква вылезла за клетку»
EDGE_INK_PX = 6
SEARCH_MM = 9.0  # насколько клетка может «уехать» из-за изгиба листа
PRINT_MASK_MM = 0.8    # запас вокруг напечатанного при подгонке клетки
MIN_MATCH = 0.25


class ImportErrorRu(Exception):
    """Ошибка импорта с понятным пользователю сообщением."""


@dataclass
class ExtractedSample:
    cell: Cell
    alpha: np.ndarray  # float32 0..1, плотность чернил
    baseline: float  # пикселей от верхнего края alpha
    source: str
    clipped: bool = False  # буква упирается в край клетки — возможно, обрезана


@dataclass
class ImportReport:
    pages_found: list[int] = field(default_factory=list)
    files_without_markers: list[str] = field(default_factory=list)
    samples: list[ExtractedSample] = field(default_factory=list)
    empty_cells: int = 0


def load_images(path: str | Path) -> list[np.ndarray]:
    """Возвращает страницы файла как RGB-массивы. PDF рендерится в 300 dpi."""
    path = Path(path)
    if not path.exists():
        raise ImportErrorRu(f"Файл не найден: {path}")
    if path.suffix.lower() == ".pdf":
        import pymupdf

        out = []
        with pymupdf.open(str(path)) as doc:
            for page in doc:
                pix = page.get_pixmap(dpi=DPI, colorspace=pymupdf.csRGB, alpha=False)
                out.append(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy())
        return out
    try:
        with Image.open(path) as im:
            return [np.array(ImageOps.exif_transpose(im).convert("RGB"))]
    except OSError as e:
        raise ImportErrorRu(f"Не удалось открыть изображение {path.name}: {e}") from e


def find_page(img: np.ndarray) -> tuple[int, np.ndarray] | None:
    """Ищет метки бланка. Возвращает номер страницы и гомографию фото → бланк."""
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(ARUCO_DICT),
                                       cv2.aruco.DetectorParameters())
    scale = 1.0
    if max(gray.shape) > 4000:
        scale = 4000 / max(gray.shape)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    corners, ids, _ = detector.detectMarkers(gray)
    if ids is None:
        return None
    found: dict[int, np.ndarray] = {}
    for c, i in zip(corners, ids.flatten()):
        found[int(i)] = c[0].mean(axis=0) / scale
    best = None
    for page in range(MAX_PAGES):
        have = [i for i in marker_ids(page) if i in found]
        if len(have) >= 3 and (best is None or len(have) > len(best[1])):
            best = (page, have)
    if best is None:
        return None
    page, have = best
    dst_all = page_marker_centers_px()
    src = np.array([found[i] for i in have], np.float32)
    dst = np.array([dst_all[i - 4 * page] for i in have], np.float32)
    if len(have) == 4:
        H = cv2.getPerspectiveTransform(src, dst)
    else:
        H = np.vstack([cv2.getAffineTransform(src, dst), [0, 0, 1]])
    return page, H


def warp_to_template(img: np.ndarray, H: np.ndarray) -> np.ndarray:
    size = (int(round(mm_to_px(A4_MM[0], DPI))), int(round(mm_to_px(A4_MM[1], DPI))))
    return cv2.warpPerspective(img, H, size, flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))


def ink_density(rgb: np.ndarray) -> np.ndarray:
    """Плотность чернил 0..1 с поправкой на неравномерное освещение."""
    r = rgb[..., 0].astype(np.float32)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))
    bg = cv2.morphologyEx(r, cv2.MORPH_CLOSE, kernel)
    bg = cv2.GaussianBlur(bg, (0, 0), 8)
    return np.clip(1.0 - r / np.maximum(bg, 1.0), 0.0, 1.0)


def extract_ink(rgb: np.ndarray, guides: tuple[float, ...] = ()) -> np.ndarray | None:
    """Выделяет чернила в клетке. None, если клетка пустая.

    guides: высоты направляющих линий клетки в пикселях кропа. На блёклых или
    желтоватых сканах оранжевый пунктир темнеет и попадает в маску."""
    dark = ink_density(rgb)
    otsu, _ = cv2.threshold((dark * 255).astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    t = float(np.clip(otsu / 255.0 * 0.8, 0.12, 0.5))
    mask = (dark > t).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = _keep_components(stats, guides)
    mask = keep[labels].astype(np.uint8)
    if mask.sum() < MIN_INK_PX:
        return None
    soft = cv2.dilate(mask, np.ones((3, 3), np.uint8)).astype(np.float32)
    # Растягиваем контраст: бледный (пересвеченный) скан даёт такую же
    # насыщенную линию, как и тёмный. Цвет ручки задаётся при отрисовке.
    lo = t * 0.4
    hi = max(float(np.percentile(dark[mask > 0], 85)), lo + 0.1)
    alpha = np.clip((dark - lo) / (hi - lo), 0.0, 1.0) * soft
    return alpha.astype(np.float32)


def _keep_components(stats: np.ndarray, guides: tuple[float, ...]) -> np.ndarray:
    """Отбрасывает шум: крошки, штрихи пунктира на направляющих и соринки,
    лежащие далеко от написанного."""
    x, y, w, h, area = (stats[:, i] for i in range(5))
    keep = area >= MIN_COMPONENT_PX
    keep[0] = False
    dash_h, tol = _px(GUIDE_DASH_H_MM), _px(GUIDE_TOL_MM)
    cy = y + h / 2.0
    for g in guides:
        keep &= ~((h <= dash_h) & ((w >= 1.5 * h) | (area < SPECK_PX)) & (np.abs(cy - g) <= tol))
    if keep.sum() > 1:
        main = int(np.argmax(np.where(keep, area, 0)))
        far = _px(SPECK_DIST_MM)
        gap_x = np.maximum(0, np.maximum(x[main] - (x + w), x - (x[main] + w[main])))
        gap_y = np.maximum(0, np.maximum(y[main] - (y + h), y - (y[main] + h[main])))
        keep &= ~((area < SPECK_PX) & (np.maximum(gap_x, gap_y) > far))
    return keep


def printed_features(rgb: np.ndarray) -> np.ndarray:
    """Серые типографские элементы бланка (уголки, подписи). Синие чернила
    и оранжевые направляющие почти гасятся: у них высокая насыщенность."""
    f = rgb.astype(np.float32)
    mx, mn = f.max(axis=2), f.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1.0)
    return ((255.0 - mx) * np.clip(1.0 - 2.5 * sat, 0.0, 1.0)).astype(np.float32)


def _px(mm: float) -> int:
    return int(round(mm_to_px(mm, DPI)))


def cell_offsets(flat: np.ndarray, cells: list[Cell], template_rgb: np.ndarray) -> list[tuple[int, int]]:
    """Уточняет положение каждой клетки по напечатанным уголкам и подписи.

    Метки по углам дают общее выравнивание, но лист на фото бывает изогнут,
    и середина страницы съезжает на несколько миллиметров. Поэтому каждую
    клетку ищем отдельно рядом с ожидаемым местом.

    Сравниваем только там, где на бланке что-то напечатано: чёрные чернила
    серые, как типографская краска, и без маски буквы внутри клетки сбивают
    поиск."""
    feat = printed_features(flat)
    tfeat = printed_features(template_rgb)
    printed = cv2.dilate((tfeat > 20).astype(np.uint8), np.ones((2 * _px(PRINT_MASK_MM) + 1,) * 2, np.uint8))
    H, W = feat.shape
    m = _px(SEARCH_MM)
    raw: list[tuple[int, int] | None] = []
    for c in cells:
        l, t = _px(c.x - 1.0), _px(c.y - LABEL_H_MM)
        r, b = _px(c.x + c.w + 1.0), _px(c.y + c.h + 1.0)
        patch = tfeat[t:b, l:r]
        sl, st, sr, sb = max(0, l - m), max(0, t - m), min(W, r + m), min(H, b + m)
        region = feat[st:sb, sl:sr]
        if region.shape[0] < patch.shape[0] or region.shape[1] < patch.shape[1]:
            raw.append(None)
            continue
        mask = printed[t:b, l:r].astype(np.float32)
        res = np.nan_to_num(cv2.matchTemplate(region, patch, cv2.TM_CCOEFF_NORMED, mask=mask),
                            nan=-1.0, posinf=-1.0, neginf=-1.0)
        _, score, _, loc = cv2.minMaxLoc(res)
        raw.append((loc[0] + sl - l, loc[1] + st - t) if score >= MIN_MATCH else None)
    return _smooth_offsets(cells, raw)


def _smooth_offsets(cells: list[Cell], raw: list[tuple[int, int] | None], k: int = 6,
                    tol_mm: float = 1.5) -> list[tuple[int, int]]:
    """Изгиб листа плавный, поэтому сдвиг клетки близок к сдвигам соседей.
    Не найденные и выбивающиеся значения заменяем медианой соседей."""
    centers = np.array([(c.x + c.w / 2, c.y + c.h / 2) for c in cells])
    known = [i for i, o in enumerate(raw) if o is not None]
    if not known:
        return [(0, 0)] * len(cells)
    vals = np.array([raw[i] for i in known], float)
    out = []
    for i, o in enumerate(raw):
        d = np.linalg.norm(centers[known] - centers[i], axis=1)
        order = [j for j in np.argsort(d) if known[j] != i][:k] or list(range(len(known)))
        med = np.median(vals[order], axis=0)
        if o is None or np.abs(np.array(o) - med).max() > _px(tol_mm):
            out.append((int(round(med[0])), int(round(med[1]))))
        else:
            out.append(o)
    return out


def crop_cell(page_img: np.ndarray, cell: Cell, offset: tuple[int, int] = (0, 0)) -> tuple[np.ndarray, float]:
    dx, dy = offset
    l, t = _px(cell.x + CELL_INSET_MM) + dx, _px(cell.y + CELL_INSET_MM) + dy
    r, b = _px(cell.x + cell.w - CELL_INSET_MM) + dx, _px(cell.y + cell.h - CELL_INSET_MM) + dy
    baseline = mm_to_px(cell.y + BASELINE_FROM_TOP_MM, DPI) + dy - t
    l, t = max(l, 0), max(t, 0)
    return page_img[t:b, l:r], baseline


def touches_edge(alpha: np.ndarray) -> bool:
    """Чернила лежат вдоль края вырезанной клетки: буква, скорее всего,
    вылезла за уголки и часть её не попала в образец."""
    e = EDGE_PX
    strong = alpha > 0.5
    return any(int(band.sum()) >= EDGE_INK_PX
               for band in (strong[:e], strong[-e:], strong[:, :e], strong[:, -e:]))


def tight_crop(alpha: np.ndarray, baseline: float, pad: int = 3) -> tuple[np.ndarray, float]:
    ys, xs = np.nonzero(alpha > 0.05)
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad + 1, alpha.shape[0])
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad + 1, alpha.shape[1])
    return alpha[y0:y1, x0:x1].copy(), baseline - y0


def import_files(paths: list[str | Path]) -> ImportReport:
    pages = all_pages()
    report = ImportReport()
    for path in paths:
        for idx, img in enumerate(load_images(path)):
            name = f"{Path(path).name}#{idx + 1}"
            hit = find_page(img)
            if hit is None:
                report.files_without_markers.append(name)
                continue
            page, H = hit
            if page not in pages:
                report.files_without_markers.append(name)
                continue
            ts, cells, n_pages = pages[page]
            report.pages_found.append(page)
            flat = warp_to_template(img, H)
            template_rgb = np.array(render_page(cells, page, n_pages, ts))
            offsets = cell_offsets(flat, cells, template_rgb)
            for cell, off in zip(cells, offsets):
                crop, baseline = crop_cell(flat, cell, off)
                alpha = extract_ink(crop, (baseline, baseline - mm_to_px(XHEIGHT_GUIDE_MM, DPI)))
                if alpha is None:
                    report.empty_cells += 1
                    continue
                clipped = touches_edge(alpha)
                alpha, baseline = tight_crop(alpha, baseline)
                report.samples.append(ExtractedSample(cell, alpha, baseline, name, clipped))
    return report
