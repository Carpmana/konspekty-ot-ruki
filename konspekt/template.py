"""Бланк образцов почерка: печатается, заполняется ручкой, сканируется.

По углам каждой страницы стоят метки ArUco. По ним импорт находит лист на
фото, выравнивает перспективу и точно знает, где какая клетка. Номер
страницы зашифрован в номерах меток (страница p использует метки 4p..4p+3).
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .charset import HEADING, SampleRequest, be_requests, en_requests, extra_requests, sample_requests
from .units import A4_MM, mm_to_px

TEMPLATE_VERSION = 1
DPI = 300
# Первые 50 меток DICT_4X4_100 совпадают с DICT_4X4_50, поэтому старые
# распечатанные бланки по-прежнему распознаются.
ARUCO_DICT = cv2.aruco.DICT_4X4_100
MAX_PAGES = 25

MARKER_MM = 12.0
# Центры меток: левый верх, правый верх, правый низ, левый низ.
MARKER_CENTERS_MM = [(14.0, 14.0), (196.0, 14.0), (196.0, 283.0), (14.0, 283.0)]

CELL_H_MM = 20.0
CHAR_CELL_W_MM = 15.0
BASELINE_FROM_TOP_MM = 13.0
XHEIGHT_GUIDE_MM = 5.0
LABEL_H_MM = 4.5
ROW_GAP_MM = 3.0
CELL_GAP_MM = 2.0
AREA_MM = (18.0, 26.0, 192.0, 274.0)  # x0, y0, x1, y1

GUIDE_COLOR = (255, 196, 160)  # светло-оранжевый: почти не виден в красном канале
TICK_COLOR = (150, 150, 150)
LABEL_COLOR = (90, 90, 90)

FONT_PATH = Path(__file__).parent / "assets" / "DejaVuSans.ttf"


@dataclass(frozen=True)
class Cell:
    request: SampleRequest
    page: int
    x: float  # мм, левый верхний угол клетки
    y: float
    w: float
    h: float

    @property
    def baseline_y(self) -> float:
        return self.y + BASELINE_FROM_TOP_MM

    @property
    def xheight_y(self) -> float:
        return self.baseline_y - XHEIGHT_GUIDE_MM


def cell_width(req: SampleRequest) -> float:
    if not req.is_word:
        return CHAR_CELL_W_MM
    return 12.0 + 7.0 * len(req.text)


@dataclass(frozen=True)
class TemplateSet:
    key: str
    title: str
    requests: object  # () -> list[SampleRequest]
    first_page: int  # номер первой страницы в метках


# Каждый бланк занимает свой диапазон номеров меток, поэтому импорт по фото
# сам понимает, какой это бланк и какая страница.
TEMPLATE_SETS = {
    "main": TemplateSet("main", "основной", sample_requests, 0),
    "extra": TemplateSet("extra", "дополнительный", extra_requests, 5),
    "be": TemplateSet("be", "белорусский", be_requests, 10),
    "en": TemplateSet("en", "английский", en_requests, 12),
}


def layout_cells(requests: list[SampleRequest] | None = None, first_page: int = 0) -> list[list[Cell]]:
    """Раскладывает запросы по клеткам и страницам. Детерминировано:
    импорт вызывает ту же функцию и получает те же координаты."""
    requests = sample_requests() if requests is None else requests
    x0, y0, x1, y1 = AREA_MM
    pages: list[list[Cell]] = [[]]
    x, y = x0, y0 + LABEL_H_MM
    prev_style = None
    for req in requests:
        w = cell_width(req)
        new_group = prev_style is not None and (req.style != prev_style)
        if x + w > x1 or (new_group and x > x0):
            x = x0
            y += CELL_H_MM + LABEL_H_MM + ROW_GAP_MM
        if y + CELL_H_MM > y1:
            pages.append([])
            x, y = x0, y0 + LABEL_H_MM
        pages[-1].append(Cell(req, first_page + len(pages) - 1, x, y, w, CELL_H_MM))
        x += w + CELL_GAP_MM
        prev_style = req.style
    if first_page + len(pages) > MAX_PAGES:
        raise ValueError(f"Бланк не помещается в {MAX_PAGES} страниц")
    return pages


def set_pages(key: str = "main") -> list[list[Cell]]:
    if key not in TEMPLATE_SETS:
        raise ValueError(f"Неизвестный бланк: {key}. Есть: {', '.join(TEMPLATE_SETS)}")
    ts = TEMPLATE_SETS[key]
    return layout_cells(ts.requests(), ts.first_page)


def all_pages() -> dict[int, tuple[TemplateSet, list[Cell], int]]:
    """Номер страницы в метках → (бланк, клетки, число страниц бланка)."""
    out = {}
    for ts in TEMPLATE_SETS.values():
        pages = set_pages(ts.key)
        for cells in pages:
            out[cells[0].page] = (ts, cells, len(pages))
    return out


def marker_ids(page: int) -> list[int]:
    return [4 * page + i for i in range(4)]


def _font(size_px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size_px)


def _label(req: SampleRequest) -> str:
    if req.style == HEADING:
        return f"{req.text} печ."
    return req.text


def render_page(cells: list[Cell], page: int, n_pages: int, ts: TemplateSet | None = None) -> Image.Image:
    ts = ts or TEMPLATE_SETS["main"]
    px = lambda mm: int(round(mm_to_px(mm, DPI)))  # noqa: E731
    W, H = px(A4_MM[0]), px(A4_MM[1])
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)

    dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    size = px(MARKER_MM)
    for mid, (cx, cy) in zip(marker_ids(page), MARKER_CENTERS_MM):
        marker = cv2.aruco.generateImageMarker(dictionary, mid, size)
        img.paste(Image.fromarray(marker).convert("RGB"), (px(cx) - size // 2, px(cy) - size // 2))

    head = _font(px(3.2))
    draw.text((px(26), px(9)), f"Бланк образцов почерка ({ts.title}) · страница {page - ts.first_page + 1} из {n_pages} · версия {TEMPLATE_VERSION}",
              fill=LABEL_COLOR, font=head)
    small = _font(px(2.6))
    for i, line in enumerate([
        "Пишите обычной ручкой, по одному образцу в клетку. Буквы ставьте на пунктир,",
        "строчные высотой до верхней точечной линии. Не заходите за уголки клетки.",
        "«печ.» — печатные заглавные, как вы пишете заголовки.",
    ]):
        draw.text((px(26), px(13.5 + 3.6 * i)), line, fill=LABEL_COLOR, font=small)

    label_font = _font(px(3.0))
    tick = px(2.0)
    for c in cells:
        l, t, r, b = px(c.x), px(c.y), px(c.x + c.w), px(c.y + c.h)
        for (ax, ay, dx, dy) in [(l, t, 1, 1), (r, t, -1, 1), (l, b, 1, -1), (r, b, -1, -1)]:
            draw.line([(ax, ay), (ax + dx * tick, ay)], fill=TICK_COLOR, width=2)
            draw.line([(ax, ay), (ax, ay + dy * tick)], fill=TICK_COLOR, width=2)
        by, xy = px(c.baseline_y), px(c.xheight_y)
        for xx in range(l + tick, r - tick, 14):
            draw.line([(xx, by), (xx + 7, by)], fill=GUIDE_COLOR, width=3)
        for xx in range(l + tick, r - tick, 18):
            draw.line([(xx, xy), (xx + 4, xy)], fill=GUIDE_COLOR, width=2)
        draw.text((l, px(c.y - LABEL_H_MM + 0.3)), _label(c.request), fill=LABEL_COLOR, font=label_font)
    return img


def render_template(key: str = "main") -> list[Image.Image]:
    pages = set_pages(key)
    ts = TEMPLATE_SETS[key]
    return [render_page(cells, cells[0].page, len(pages), ts) for cells in pages]


def save_template_pdf(path: str | Path, key: str = "main") -> int:
    images = render_template(key)
    images[0].save(str(path), "PDF", resolution=DPI, save_all=True, append_images=images[1:])
    return len(images)


def page_marker_centers_px(dpi: float = DPI) -> np.ndarray:
    return np.array([[mm_to_px(x, dpi), mm_to_px(y, dpi)] for x, y in MARKER_CENTERS_MM], dtype=np.float32)
