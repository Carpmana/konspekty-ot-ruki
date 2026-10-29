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
# Образцы вырезаются с запасом по плотности: HD раз плотнее бланка (600 dpi).
# Печать тогда берёт буквы с чёткими краями, а не растянутые 300 dpi.
HD = 2
LONE_SPECK_MM = 0.8    # компактная точка не крупнее этого — соринка, если рядом нет штриха
LONE_GAP_MM = 0.5      # обрывки штриха (ручка не прописала) лежат ближе
# Символы, у которых есть отдельные точки и чёрточки: у них точку не трогаем.
DETACHED_MARKS = set("ёйЁЙ!?:;.,іїij%…\"'«»÷")
# Заливка (см. flood_ink): доли от плотности ручки в клетке.
FLOOD_TOL = 0.5        # светлее — бумага (край линии — где ручка вдвое бледнее середины)
FLOOD_LINK = 0.25      # бледнее этого штрих не продолжается (связь кусков линии)
FLOOD_CORE = 0.7       # пятно без такой плотности внутри — соринка, а не штрих
FLOOD_MIN, FLOOD_MAX = 0.08, 0.3  # пределы порога: шум бумаги на сканах до ~0.12
CLOSE_PX = 2           # стягиваемый разрыв штриха, пикселей 300 dpi
GRAIN_PX = 10          # просвет меньше этого (пикселей 300 dpi) внутри штриха — зерно


class ImportErrorRu(Exception):
    """Ошибка импорта с понятным пользователю сообщением."""


@dataclass
class ExtractedSample:
    cell: Cell
    alpha: np.ndarray  # float32 0..1, плотность чернил, 300 dpi
    baseline: float  # пикселей от верхнего края alpha
    source: str
    clipped: bool = False  # буква упирается в край клетки — возможно, обрезана
    alpha_hd: np.ndarray | None = None  # тот же образец в HD раз плотнее


@dataclass
class ImportReport:
    pages_found: list[int] = field(default_factory=list)
    files_without_markers: list[str] = field(default_factory=list)
    samples: list[ExtractedSample] = field(default_factory=list)
    empty_cells: int = 0


def load_images(path: str | Path) -> list[np.ndarray]:
    """Возвращает страницы файла как RGB-массивы.

    Скан в PDF обычно — одна картинка на страницу. Её берём в родном
    разрешении: если растянуть до 300 dpi заранее, буквы потом дважды
    пересчитываются и мылятся."""
    path = Path(path)
    if not path.exists():
        raise ImportErrorRu(f"Файл не найден: {path}")
    if path.suffix.lower() == ".pdf":
        import pymupdf

        out = []
        with pymupdf.open(str(path)) as doc:
            for page in doc:
                pix = page.get_pixmap(dpi=_pdf_dpi(page), colorspace=pymupdf.csRGB, alpha=False)
                out.append(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy())
        return out
    try:
        with Image.open(path) as im:
            return [np.array(ImageOps.exif_transpose(im).convert("RGB"))]
    except OSError as e:
        raise ImportErrorRu(f"Не удалось открыть изображение {path.name}: {e}") from e


def _pdf_dpi(page) -> int:
    """Разрешение, при котором картинка скана ложится на страницу пиксель в
    пиксель. Без картинок (бланк из программы) — 300 dpi. Не больше 600:
    больше бумага сканера всё равно не даёт."""
    best = 0.0
    for info in page.get_image_info():
        w_in = (info["bbox"][2] - info["bbox"][0]) / 72.0
        if w_in > 0 and info.get("width"):
            best = max(best, info["width"] / w_in)
    if best <= 0:
        return DPI
    return int(np.clip(round(best), 72, 2 * DPI))


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


def ink_density(rgb: np.ndarray, scale: int = 1) -> np.ndarray:
    """Плотность чернил 0..1 с поправкой на неравномерное освещение.
    scale — во сколько раз картинка плотнее 300 dpi."""
    r = rgb[..., 0].astype(np.float32)
    k = 31 * scale | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    bg = cv2.morphologyEx(r, cv2.MORPH_CLOSE, kernel)
    bg = cv2.GaussianBlur(bg, (0, 0), 8 * scale)
    return np.clip(1.0 - r / np.maximum(bg, 1.0), 0.0, 1.0)


def extract_ink(rgb: np.ndarray, guides: tuple[float, ...] = (), text: str = "",
                scale: int = 1) -> np.ndarray | None:
    """Выделяет чернила в клетке. None, если клетка пустая.

    guides: высоты направляющих линий клетки в пикселях кропа. На блёклых или
    желтоватых сканах оранжевый пунктир темнеет и попадает в маску.
    text: что написано в клетке — по нему понятно, может ли там быть точка.
    scale: во сколько раз кроп плотнее 300 dpi."""
    dark = ink_density(rgb, scale)
    mask = flood_ink(dark, scale)
    if mask is None:
        return None
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = _keep_components(stats, guides, scale)
    keep = _drop_lone_specks(labels, stats, keep, text, scale)
    mask = keep[labels].astype(np.uint8)
    if mask.sum() < MIN_INK_PX * scale * scale:
        return None
    return _solid_alpha(mask, scale)


def flood_ink(dark: np.ndarray, scale: int = 1) -> np.ndarray | None:
    """Чернила «заливкой», как ведром в графическом редакторе.

    Всё, что прозрачнее порога FLOOD_TOL (доля от плотности самой ручки в
    этой клетке), заливается бумагой. Остальное считается чернилами, но
    только если пятно дотягивается до настоящего штриха (там чернила
    плотнее FLOOD_CORE): серые соринки, тень пылинки, след JPEG и ореол
    вокруг букв уходят целиком, а бледный край настоящей линии остаётся.
    Мелкие светлые просветы внутри штриха (зерно шарика) заливаются
    чернилами, большие (дырка в «о») остаются бумагой.

    Порог подобран на сканах бланков: бумага на них почти вся светлее 0.12,
    а ручка в середине линии — 0.3–0.7 смотря по странице. При половине
    плотности ручки толщина линии та же, что на скане."""
    strong = dark[dark > FLOOD_MIN]
    if strong.size < MIN_INK_PX * scale * scale:
        return None
    core = float(np.percentile(strong, 90))
    tol = float(np.clip(FLOOD_TOL * core, FLOOD_MIN, FLOOD_MAX))
    link = float(np.clip(FLOOD_LINK * core, FLOOD_MIN, tol))
    reach = (dark > link).astype(np.uint8)
    n, labels, _, _ = cv2.connectedComponentsWithStats(reach, connectivity=8)
    peak = np.zeros(n, np.float32)
    np.maximum.at(peak, labels.ravel(), dark.ravel())
    real = peak >= max(FLOOD_CORE * core, tol + 0.05)
    real[0] = False
    reach = real[labels].astype(np.uint8)
    # Толщину линии задаёт порог tol, а бледные тонкие места (ручка едва
    # коснулась бумаги) не рвутся: по ним идёт тонкая осевая линия.
    spine = cv2.dilate(cv2.ximgproc.thinning(reach * 255), np.ones((scale + 1, scale + 1), np.uint8)) > 0
    mask = (((dark > tol) | spine) & (reach > 0)).astype(np.uint8)
    # Где шарик ручки проскочил, линия рвётся на чёрточки: стягиваем разрывы
    # длиной в толщину линии, чтобы при печати штрих не выглядел пунктиром.
    k = CLOSE_PX * scale + 1
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    holes = 1 - mask
    n, labels, stats, _ = cv2.connectedComponentsWithStats(holes, connectivity=4)
    grain = stats[:, 4] < GRAIN_PX * scale * scale
    grain[np.unique(np.r_[labels[0], labels[-1], labels[:, 0], labels[:, -1]])] = False
    grain[0] = False
    mask[grain[labels]] = 1
    return mask if mask.any() else None


def refill(alpha: np.ndarray, scale: int = 1) -> np.ndarray:
    """Та же заливка для образца, сохранённого прежней очисткой: бледные
    пятна вокруг уходят, зерно внутри линии становится сплошным. Так старые
    профили печатаются так же чисто, сканы заново загружать не нужно."""
    mask = flood_ink(alpha, scale)
    return alpha if mask is None else _solid_alpha(mask, scale)


def _solid_alpha(mask: np.ndarray, scale: int) -> np.ndarray:
    """Залитые чернила: внутри линии сплошной цвет, без зерна и бледных
    мест, край сглажен на полпикселя, чтобы не было лесенки."""
    a = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 0.5 * scale)
    a[a < 0.04] = 0.0
    return a


def _keep_components(stats: np.ndarray, guides: tuple[float, ...], scale: int = 1) -> np.ndarray:
    """Отбрасывает шум: крошки, штрихи пунктира на направляющих и соринки,
    лежащие далеко от написанного."""
    x, y, w, h, area = (stats[:, i] for i in range(5))
    s2 = scale * scale
    keep = area >= MIN_COMPONENT_PX * s2
    keep[0] = False
    dash_h, tol = _px(GUIDE_DASH_H_MM, scale), _px(GUIDE_TOL_MM, scale)
    cy = y + h / 2.0
    for g in guides:
        keep &= ~((h <= dash_h) & ((w >= 1.5 * h) | (area < SPECK_PX * s2)) & (np.abs(cy - g) <= tol))
    if keep.sum() > 1:
        main = int(np.argmax(np.where(keep, area, 0)))
        far = _px(SPECK_DIST_MM, scale)
        gap_x = np.maximum(0, np.maximum(x[main] - (x + w), x - (x[main] + w[main])))
        gap_y = np.maximum(0, np.maximum(y[main] - (y + h), y - (y[main] + h[main])))
        keep &= ~((area < SPECK_PX * s2) & (np.maximum(gap_x, gap_y) > far))
    return keep


def _drop_lone_specks(labels: np.ndarray, stats: np.ndarray, keep: np.ndarray, text: str,
                      scale: int = 1) -> np.ndarray:
    """Убирает точки-соринки рядом с буквой: пыль на стекле сканера, след
    ручки, крошка ластика. В «не» или «ш» отдельной точки быть не может, а
    при печати она выглядела как лишний штрих.

    Не трогаем символы с точками (ё, й, ?, !, «:») и обрывки штриха там, где
    ручка не прописала: они вытянуты и лежат вплотную к линии."""
    if any(c in DETACHED_MARKS for c in text) or keep.sum() < 2:
        return keep
    x, y, w, h, area = (stats[:, i] for i in range(5))
    small = keep & (np.maximum(w, h) <= _px(LONE_SPECK_MM, scale)) & (area < SPECK_PX * scale * scale)
    big = keep & ~small
    if not small.any() or not big.any():
        return keep
    dist = cv2.distanceTransform((~big[labels]).astype(np.uint8), cv2.DIST_L2, 3)
    out = keep.copy()
    gap = _px(LONE_GAP_MM, scale)
    for i in np.nonzero(small)[0]:
        if dist[labels == i].min() > gap:
            out[i] = False
    return out


def printed_features(rgb: np.ndarray) -> np.ndarray:
    """Серые типографские элементы бланка (уголки, подписи). Синие чернила
    и оранжевые направляющие почти гасятся: у них высокая насыщенность."""
    f = rgb.astype(np.float32)
    mx, mn = f.max(axis=2), f.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1.0)
    return ((255.0 - mx) * np.clip(1.0 - 2.5 * sat, 0.0, 1.0)).astype(np.float32)


def _px(mm: float, scale: int = 1) -> int:
    return int(round(mm_to_px(mm, DPI * scale)))


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


def cell_rect(cell: Cell, offset: tuple[int, int] = (0, 0)) -> tuple[int, int, int, int]:
    dx, dy = offset
    l, t = _px(cell.x + CELL_INSET_MM) + dx, _px(cell.y + CELL_INSET_MM) + dy
    r, b = _px(cell.x + cell.w - CELL_INSET_MM) + dx, _px(cell.y + cell.h - CELL_INSET_MM) + dy
    return l, t, r, b


def crop_cell_hd(img: np.ndarray, H: np.ndarray, cell: Cell, offset: tuple[int, int] = (0, 0)) -> np.ndarray:
    """Клетка прямо из исходного скана в HD раз плотнее бланка. Один пересчёт
    пикселей вместо двух, поэтому края букв не мылятся."""
    l, t, r, b = cell_rect(cell, offset)
    M = np.array([[HD, 0, -HD * l], [0, HD, -HD * t], [0, 0, 1]], np.float64) @ H
    return cv2.warpPerspective(img, M, (HD * (r - l), HD * (b - t)), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))


def downsample(alpha_hd: np.ndarray) -> np.ndarray:
    h, w = alpha_hd.shape
    return cv2.resize(alpha_hd, (w // HD, h // HD), interpolation=cv2.INTER_AREA)


def upscale_legacy(alpha: np.ndarray, text: str = "") -> np.ndarray:
    """Образец старого профиля (300 dpi) → HD для печати: та же очистка от
    соринок и резкий край, что и у нового импорта. Сканы заново загружать
    не нужно."""
    mask = (alpha > 0.35).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = stats[:, 4] > 0
    keep[0] = False
    keep = _drop_lone_specks(labels, stats, keep, text)
    # Оставляем только окрестность настоящих штрихов: бледные пятна и
    # соринки вокруг уходят.
    a = alpha * cv2.dilate(keep[labels].astype(np.uint8), np.ones((5, 5), np.uint8))
    h, w = a.shape
    a = cv2.resize(a, (w * HD, h * HD), interpolation=cv2.INTER_CUBIC)
    a = np.clip((a - 0.08) / 0.75, 0.0, 1.0)
    a = a * a * (3 - 2 * a)
    a[a < 0.04] = 0.0
    return a.astype(np.float32)


def touches_edge(alpha: np.ndarray) -> bool:
    """Чернила лежат вдоль края вырезанной клетки: буква, скорее всего,
    вылезла за уголки и часть её не попала в образец."""
    e = EDGE_PX
    strong = alpha > 0.5
    return any(int(band.sum()) >= EDGE_INK_PX
               for band in (strong[:e], strong[-e:], strong[:, :e], strong[:, -e:]))


def tight_box(alpha: np.ndarray, pad: int = 3) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(alpha > 0.05)
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad + 1, alpha.shape[0])
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad + 1, alpha.shape[1])
    return x0, y0, x1, y1


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
                baseline = mm_to_px(cell.y + BASELINE_FROM_TOP_MM, DPI) + off[1] - cell_rect(cell, off)[1]
                crop = crop_cell_hd(img, H, cell, off)
                guides = (baseline * HD, (baseline - mm_to_px(XHEIGHT_GUIDE_MM, DPI)) * HD)
                alpha_hd = extract_ink(crop, guides, cell.request.text, HD)
                if alpha_hd is None:
                    report.empty_cells += 1
                    continue
                alpha = downsample(alpha_hd)
                clipped = touches_edge(alpha)
                x0, y0, x1, y1 = tight_box(alpha)
                report.samples.append(ExtractedSample(
                    cell, alpha[y0:y1, x0:x1].copy(), baseline - y0, name, clipped,
                    alpha_hd[HD * y0:HD * y1, HD * x0:HD * x1].copy()))
    return report
