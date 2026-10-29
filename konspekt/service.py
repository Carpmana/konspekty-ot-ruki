"""Действия приложения без интерфейса: профили, импорт, генерация, экспорт.

Окно (gui.py) только вызывает эти функции, поэтому всё, что здесь, можно
проверить тестами без Qt.
"""

import math
import os
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
from PIL import Image

from . import layout as lay
from .extract import ExtractedSample, ImportReport, import_files
from .profile import PROFILE_FILE, GlyphSample, Profile, safe_folder_name
from .render import render_page, save_pdf
from .units import mm_to_px

PAPERS = [("grid", "В клетку"), ("lines", "В линейку"), ("blank", "Без линий")]


@dataclass(frozen=True)
class PageFormat:
    key: str
    title: str
    size_mm: tuple[float, float]
    outer_mm: float  # от края до красной линии поля
    inner_mm: float  # от другого края до текста
    margins: str  # поля по умолчанию: left | outer | none
    pitch_mm: float  # шаг строк по умолчанию для клетки; у линейки — шаг линеек


# Тетрадь 12–18 листов: страница 170×205 мм, клетка 5 мм, поле снаружи.
# Двойной листок — это четыре таких страницы: 1 и 3 правые, 2 и 4 левые.
FORMATS = [
    PageFormat("notebook", "Тетрадный листок 170×205", (170.0, 205.0), 20.0, 4.0, "outer", 10.0),
    PageFormat("A4", "Лист A4", (210.0, 297.0), 25.0, 8.0, "left", 10.0),
    PageFormat("A5", "Лист A5", (148.0, 210.0), 20.0, 6.0, "left", 10.0),
]
FORMAT_BY_KEY = {f.key: f for f in FORMATS}
PAGES = [f.key for f in FORMATS]
MARGINS = [("left", "Поле слева"), ("outer", "Снаружи, как в тетради"), ("none", "Без поля")]
INKS = [("", "Синяя"), ("black", "Чёрная")]  # пусто — цвет чернил профиля
INK_COLORS = {"black": (24, 24, 28)}
NOTEBOOK_LINE_PITCH_MM = 8.0  # тетрадь в линейку
DEFAULT_SEED = 3  # вариант оформления, который выбрали в прототипе
PREVIEW_DPI = 110
EXPORT_DPI = 300
PRINT_DPI = 400  # буквы хранятся в 600 dpi; 400 — чётче 300 и ещё не тяжело для памяти


def default_profiles_dir() -> Path:
    """Где хранятся профили почерков.

    Из исходников — папка profiles/ рядом с кодом (как у командной строки).
    В собранной программе — %APPDATA%\\Konspekt\\profiles, чтобы профили не
    пропадали при обновлении .exe.
    """
    env = os.environ.get("KONSPEKT_PROFILES")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "Konspekt" / "profiles"
    return Path(__file__).resolve().parents[1] / "profiles"


def list_profiles(profiles_dir: str | Path, errors: list[str] | None = None) -> list[tuple[str, Path]]:
    """(имя, папка) всех профилей в папке, по алфавиту.

    Повреждённый профиль не мешает остальным; почему он не открылся,
    дописывается в errors, чтобы окно могло это показать."""
    root = Path(profiles_dir)
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if (d / PROFILE_FILE).exists():
            try:
                out.append((Profile.load(d).name, d))
            except Exception as e:
                if errors is not None:
                    errors.append(f"{d.name}: {type(e).__name__}: {e}")
    return sorted(out, key=lambda p: p[0].lower())


def profile_dir_for(profiles_dir: str | Path, name: str) -> Path:
    return Path(profiles_dir) / safe_folder_name(name)


@dataclass
class ImportResult:
    profile_dir: Path
    profile_name: str
    pages_found: list[int] = field(default_factory=list)
    added: int = 0
    empty_cells: int = 0
    files_without_markers: list[str] = field(default_factory=list)
    total_samples: int = 0
    skipped: list[str] = field(default_factory=list)  # уже импортированы раньше
    crossed: list[str] = field(default_factory=list)  # отключённые зачёркнутые образцы
    turned_off: int = 0  # отключены при просмотре импорта

    def summary(self) -> str:
        pages = ", ".join(str(p + 1) for p in sorted(set(self.pages_found))) or "нет"
        lines = [f"Профиль «{self.profile_name}»", f"Найдены страницы бланка: {pages}",
                 f"Добавлено образцов: {self.added} (всего в профиле: {self.total_samples})"]
        if self.turned_off:
            lines.append(f"Отключено при просмотре: {self.turned_off}. Вернуть их можно в меню "
                         "Почерк → Редактор букв.")
        if self.crossed:
            lines.append(f"Отключены образцы, похожие на зачёркнутые: {' '.join(self.crossed)}. "
                         "Вернуть их можно в меню Почерк → Редактор букв.")
        if self.skipped:
            lines.append("Пропущены, уже импортированы раньше:")
            lines += [f"  • {Path(f).name}" for f in self.skipped]
        if self.files_without_markers:
            lines.append("Не найдены угловые метки бланка (лист должен быть виден целиком):")
            lines += [f"  • {f}" for f in self.files_without_markers]
        return "\n".join(lines)


@dataclass
class ImportPreview:
    """Вырезанные из сканов буквы до того, как они попадут в профиль."""
    profile_dir: Path
    profile_name: str
    new_files: list[Path]
    skipped: list[str]
    report: ImportReport

    @property
    def samples(self) -> list[ExtractedSample]:
        return self.report.samples


def scan_import(profile_dir: str | Path, name: str, files: list[str | Path]) -> ImportPreview:
    """Вырезает буквы из сканов, профиль пока не меняет."""
    root = Path(profile_dir)
    prof = Profile.load(root) if (root / PROFILE_FILE).exists() else None
    new, skipped = [], []
    for f in map(Path, files):
        (skipped if prof is not None and f.exists() and prof.is_imported(f) else new).append(f)
    rep = import_files(new) if new else ImportReport()
    return ImportPreview(root, prof.name if prof else name, new, [str(f) for f in skipped], rep)


def finish_import(preview: ImportPreview, keep: list[bool] | None = None) -> ImportResult:
    """Добавляет вырезанные буквы в профиль (создаёт его, если нет).

    keep — для каждого образца: брать ли его. Не взятые тоже сохраняются,
    но отключёнными: их можно вернуть в «Редакторе букв»."""
    root = preview.profile_dir
    prof = Profile.load(root) if (root / PROFILE_FILE).exists() else Profile.create(root, preview.profile_name)
    rep = preview.report
    if not preview.new_files:
        return ImportResult(root, prof.name, total_samples=len(prof.samples), skipped=preview.skipped)
    added = prof.add_extracted(rep.samples)
    if keep is not None:
        for s, k in zip(added, keep):
            s.enabled = bool(k)
        prof.measure()
    crossed = disable_crossed(prof, among=[s for s in added if s.enabled], save=False)
    for f in preview.new_files:
        prof.mark_imported(f)
    prof.save()
    off = sum(1 for s in added if not s.enabled) - len(crossed)
    return ImportResult(root, prof.name, list(rep.pages_found), len(added), rep.empty_cells,
                        list(rep.files_without_markers), len(prof.samples), preview.skipped,
                        [s.text for s in crossed], off)


def import_scans(profile_dir: str | Path, name: str, files: list[str | Path]) -> ImportResult:
    """Добавляет образцы из сканов бланка в профиль; создаёт профиль, если его нет."""
    return finish_import(scan_import(profile_dir, name, files))


DEMO_NAME = "Пример почерка"
DEMO_FONT = Path(__file__).parent / "assets" / "Caveat.ttf"
DEMO_TEXT = """# Фотосинтез
>> Двадцать пятое октября
Фотосинтез — образование органических веществ из углекислого газа и воды на свету.
Где происходит: в _хлоропластах_ клеток листа.
- световая фаза: вода расщепляется, выделяется кислород
- темновая фаза: из CO_2 образуется глюкоза
6CO_2 + 6H_2O -> C_6H_12O_6 + 6O_2
[[Свет — источник энергии]]

1. Какой газ выделяют растения на свету?
2. Где в клетке идёт фотосинтез?"""


def make_demo_profile(profiles_dir: str | Path) -> Path:
    """Пример почерка, чтобы посмотреть программу до того, как заполнен свой бланк.

    Бланк заполняется рукописным шрифтом Caveat и импортируется как обычный
    скан, поэтому пример ведёт себя как настоящий профиль (только буквы
    ровнее, чем у живой руки)."""
    import tempfile

    from .synthetic import fill_template

    root = profile_dir_for(profiles_dir, DEMO_NAME)
    if (root / PROFILE_FILE).exists():
        return root
    with tempfile.TemporaryDirectory() as d:
        files = []
        for i, page in enumerate(fill_template(str(DEMO_FONT), seed=5)):
            files.append(Path(d) / f"пример_{i + 1}.png")
            Image.fromarray(page).save(files[-1])
        rep = import_files(files)
    prof = Profile.create(root, DEMO_NAME)
    prof.add_extracted(rep.samples)
    prof.save()
    return root


def disable_crossed(prof: Profile, among: list[GlyphSample] | None = None, save: bool = True) -> list[GlyphSample]:
    """Отключает образцы, похожие на зачёркнутые (при импорте — только среди
    новых, чтобы не трогать то, что пользователь вернул сам). Они остаются в
    профиле, и их можно вернуть в окне «Редактор букв»."""
    crossed = prof.find_crossed()
    if among is not None:
        ids = {s.id for s in among}
        crossed = [s for s in crossed if s.id in ids]
    for s in crossed:
        s.enabled = False
    if crossed:
        prof.measure()
        if save:
            prof.save()
    return crossed


Stroke = list[tuple[float, float]]  # точки штриха в мм от левого верхнего угла клетки


def _smooth(pts: Stroke, k: int = 2) -> Stroke:
    """Сглаживание дрожи тачпада: скользящее среднее, концы на месте."""
    if len(pts) < 3:
        return pts
    a = np.asarray(pts, np.float64)
    out = a.copy()
    for i in range(1, len(a) - 1):
        lo, hi = max(0, i - k), min(len(a), i + k + 1)
        out[i] = a[lo:hi].mean(axis=0)
    return [tuple(p) for p in out]


def strokes_to_alpha(strokes: list[Stroke], stroke_mm: float, baseline_mm: float,
                     dpi: int = 300) -> tuple[np.ndarray, float]:
    """Штрихи (мм) → картинка образца, как у отсканированных: плотность чернил
    0..1 при 300 dpi, обрезанная по чернилам; и базовая линия в пикселях."""
    import cv2
    from PIL import ImageDraw

    ss = 3  # рисуем крупнее и уменьшаем — края штриха сглаживаются
    k = dpi / 25.4 * ss
    pts_all = [p for st in strokes for p in st]
    if not pts_all:
        raise ValueError("Пустой рисунок")
    xs, ys = [p[0] for p in pts_all], [p[1] for p in pts_all]
    pad = stroke_mm * 2 + 0.5
    x0, y0 = min(xs) - pad, min(ys) - pad
    w = int((max(xs) - x0 + pad) * k) + 1
    h = int((max(ys) - y0 + pad) * k) + 1
    im = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(im)
    r = max(stroke_mm * k / 2, 1.0)
    for st in strokes:
        pts = [((x - x0) * k, (y - y0) * k) for x, y in _smooth(st)]
        if len(pts) > 1:
            d.line(pts, fill=255, width=int(round(2 * r)), joint="curve")
        for x, y in (pts[0], pts[-1]) if len(pts) > 1 else pts:
            d.ellipse((x - r, y - r, x + r, y + r), fill=255)
    im = im.resize((max(1, w // ss), max(1, h // ss)), Image.LANCZOS)
    alpha = cv2.GaussianBlur(np.asarray(im, np.float32) / 255.0, (0, 0), 0.6)
    return alpha, (baseline_mm - y0) * dpi / 25.4


def add_drawn_sample(prof: Profile, text: str, strokes: list[Stroke], baseline_mm: float,
                     style: str = "body") -> GlyphSample:
    alpha, baseline = strokes_to_alpha(strokes, prof.params.stroke_mm, baseline_mm)
    s = prof.add_drawn(text, alpha, baseline, style)
    prof.save()
    return s


def coverage_text(prof: Profile) -> str:
    lines = [f"Профиль «{prof.name}»: {len(prof.samples)} образцов", ""]
    for group, info in prof.coverage().items():
        if group == "стоит добавить":
            lines.append("")
            lines.append(f"Мало вариантов у частых букв (меньше 6): {info}. Заполните ещё раз дополнительный бланк."
                         if info else "Частых букв достаточно.")
        elif isinstance(info, dict):
            lines.append(f"{group.capitalize()}: нет — {info['нет'] or '—'}; "
                         f"один вариант — {info['один вариант'] or '—'}")
        else:
            lines.append(f"{group.capitalize()}: {', '.join(info) or '—'}")
    return "\n".join(lines)


@dataclass
class Options:
    """То, что пользователь выбирает в окне."""
    paper: str = "grid"
    page: str = "A4"
    seed: int = DEFAULT_SEED
    neatness: float = 1.0
    size_mm: float | None = None  # None — как в образцах
    pitch_mm: float = 10.0
    show_missing: bool = False
    margins: str = ""  # left | outer | none; пусто — как принято для формата
    real_paper: bool = False  # печать на настоящий листок: только чернила
    offset_x_mm: float = 0.0  # подстройка под принтер (для печати на листок)
    offset_y_mm: float = 0.0
    spread: bool = False  # двойной листок целиком: две страницы рядом, с оборотом
    nested: bool = True  # листки вкладываются друг в друга, как в тетради (иначе — стопкой)
    tiredness: float = 0.0  # 0–1: рука устаёт к концу конспекта
    corrections: float = 0.0  # доля слов с зачёркнутой опиской перед ними
    live_edge: float = 1.0  # 0–2: насколько гуляет начало строк у левого края
    flip_back: bool = False  # двойной листок: внутренняя сторона печатается повёрнутой на 180°
    smoothness: float = 0.5  # 0–1: насколько плавные контуры букв (0 — как в скане)
    ink: str = ""  # цвет ручки из INKS; пусто — как в профиле
    weight: float = 1.0  # толщина линии: 1 — как на скане

    @property
    def fmt(self) -> PageFormat:
        return FORMAT_BY_KEY.get(self.page, FORMAT_BY_KEY["A4"])

    @property
    def use_spread(self) -> bool:
        return self.spread and self.page == "notebook"

    @property
    def margin_mode(self) -> str:
        return self.margins or self.fmt.margins

    def settings(self, dpi: int) -> lay.Settings:
        f = self.fmt
        mode = self.margin_mode
        top = lay.Settings.margin_top_mm
        if self.paper == "lines":
            # Линейки рисуются от верхнего поля, а строки встают на клетку 5 мм:
            # подбираем поле так, чтобы первая строка легла ровно на линейку.
            g = lay.Settings.grid_mm
            top = math.ceil((top + self.pitch_mm) / g) * g - self.pitch_mm
        return lay.Settings(margin_top_mm=top, page=self.page if self.page in ("A4", "A5") else "A4", page_size_mm=f.size_mm,
                            paper=self.paper, dpi=dpi, seed=self.seed, neatness=self.neatness,
                            x_height_mm=self.size_mm, line_pitch_mm=self.pitch_mm,
                            highlight_missing=self.show_missing and not self.real_paper,
                            margin_line=mode != "none",
                            margin_left_mm=f.outer_mm if mode != "none" else f.inner_mm,
                            margin_right_mm=f.inner_mm,
                            tiredness=self.tiredness, corrections=self.corrections, live_edge=self.live_edge,
                            smoothness=self.smoothness, ink_color=INK_COLORS.get(self.ink),
                            weight=self.weight)


@dataclass
class Rendered:
    images: list[Image.Image]
    missing: set[str]
    dpi: int
    size_mm: tuple[float, float] = (210.0, 297.0)
    labels: list[str] = field(default_factory=list)  # подписи сторон листков (для разворота)
    blank: list[bool] = field(default_factory=list)  # сторона листка без текста: не печатается

    @property
    def is_spread(self) -> bool:
        return bool(self.labels)

    def side_indices(self, inner: bool) -> list[int]:
        """Стороны разворота: снаружи (чётные) или внутри (нечётные)."""
        return list(range(int(inner), len(self.images), 2))

    def sheets(self) -> list[tuple[int, int | None]]:
        """Двойные листки по порядку: (наружная сторона, внутренняя или None, если она пустая)."""
        out = []
        for k in range(0, len(self.images), 2):
            inner = k + 1 if not (self.blank and self.blank[k + 1]) else None
            out.append((k, inner))
        return out


def _mirror_page(page: lay.Page, dx: float) -> lay.Page:
    """Сдвигает строки правой страницы тетради: поле у неё справа."""
    glyphs = [replace(g, x=g.x + dx) for g in page.glyphs]
    conns = [replace(c, p0=(c.p0[0] + dx, c.p0[1]), p1=(c.p1[0] + dx, c.p1[1])) for c in page.connectors]
    lines = [replace(ln, points=[(x + dx, y) for x, y in ln.points]) for ln in page.lines]
    return replace(page, glyphs=glyphs, connectors=conns, lines=lines)


def printer_shift(im: Image.Image, opts: Options, dpi: int) -> Image.Image:
    """Сдвиг под принтер. Применяется к тому, что целиком ложится в лоток:
    к странице или ко всей стороне двойного листка. Если сдвигать каждую
    страницу разворота по отдельности, правая страница обрезается по линии
    сгиба — буквы в начале строк теряют пару миллиметров."""
    dx, dy = round(mm_to_px(opts.offset_x_mm, dpi)), round(mm_to_px(opts.offset_y_mm, dpi))
    if not (dx or dy):
        return im
    moved = Image.new("RGB", im.size, (255, 255, 255))
    moved.paste(im, (dx, dy))
    return moved


def render_text(text: str, prof: Profile, opts: Options, dpi: int = PREVIEW_DPI,
                for_print: bool = False) -> Rendered:
    """Текст → картинки страниц. Вёрстка в миллиметрах, поэтому предпросмотр
    и печать при разном dpi дают одинаковые страницы.

    for_print: чернила сплошным цветом на белом (см. render._draw_solid); с
    real_paper на картинке только текст (бумага — настоящий листок)."""
    f = opts.fmt
    if not text.strip():
        return Rendered([], set(), dpi, f.size_mm)
    s = opts.settings(dpi)
    layout = lay.typeset(text, prof, s)
    ink_only = for_print and opts.real_paper
    W = f.size_mm[0]
    pages = list(layout.pages)
    if opts.use_spread:
        pages += [lay.Page() for _ in range(-len(pages) % 4)]  # листок — четыре страницы
    images = []
    for i, page in enumerate(pages):
        ps = s
        if opts.margin_mode == "outer" and i % 2 == 0:  # правая страница: поле справа
            page = _mirror_page(page, f.inner_mm - (f.outer_mm + 2.0))
            ps = replace(s, margin_left_mm=W - f.outer_mm)
        if for_print:
            ps = replace(ps, solid_print=True)
        if ink_only:
            ps = replace(ps, paper="blank")
        images.append(render_page(page, prof, ps, i))
    r = Rendered(images, set(layout.missing), dpi, f.size_mm)
    if opts.use_spread:
        r = to_spreads(r, len(layout.pages), opts.nested)
    if ink_only:
        # Сдвиг принтера одинаков для каждой стороны в лотке, поэтому оборот
        # сначала поворачиваем, а потом сдвигаем.
        r.images = [printer_shift(im.rotate(180) if r.is_spread and k % 2 and opts.flip_back else im, opts, dpi)
                    for k, im in enumerate(r.images)]
    return r


def sheet_pages(sheets: int, nested: bool) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Номера страниц на сторонах каждого листка: ((снаружи слева, справа), (внутри слева, справа)).

    Стопкой: листок 1 — страницы 1–4, листок 2 — 5–8… Тетрадкой (вложены друг
    в друга): листок 1 самый внешний, на нём первые две и последние две страницы,
    самый внутренний листок — середина конспекта."""
    out = []
    for i in range(sheets):
        if nested:
            last = 4 * sheets
            out.append(((last - 2 * i, 2 * i + 1), (2 * i + 2, last - 2 * i - 1)))
        else:
            k = 4 * i
            out.append(((k + 4, k + 1), (k + 2, k + 3)))
    return out


def to_spreads(r: Rendered, real: int | None = None, nested: bool = False) -> Rendered:
    """Страницы тетради → стороны развёрнутых двойных листков (две страницы рядом).

    У каждого листка сначала печатается наружная сторона, потом листок
    переворачивают и печатают внутреннюю. real — сколько страниц с текстом;
    сторона, где обе страницы пустые, помечается в blank и не печатается."""
    w, h = r.images[0].size
    real = len(r.images) if real is None else real
    sheets = len(r.images) // 4
    sides, labels, blank = [], [], []
    for i, (outer, inner) in enumerate(sheet_pages(sheets, nested)):
        for nums, where in ((outer, "снаружи"), (inner, "внутри")):
            side = Image.new("RGB", (2 * w, h), (255, 255, 255))
            side.paste(r.images[nums[0] - 1], (0, 0))
            side.paste(r.images[nums[1] - 1], (w, 0))
            sides.append(side)
            empty = min(nums) > real
            shown = [str(x) if x <= real else "пусто" for x in nums]
            labels.append(f"Листок {i + 1}, {where}: " + ("пусто, не печатается" if empty
                                                          else f"слева {shown[0]}, справа {shown[1]}"))
            blank.append(empty)
    W, H = r.size_mm
    return Rendered(sides, r.missing, r.dpi, (2 * W, H), labels, blank)


def export_pdf(text: str, prof: Profile, opts: Options, path: str | Path, dpi: int = EXPORT_DPI) -> Rendered:
    r = render_text(text, prof, opts, dpi, for_print=True)
    save_pdf(r.images, path, dpi)
    return r


# ---------- текст из файлов и вставки ----------

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_text(path: str | Path) -> str:
    """Текст документа Word: заголовки → «# », списки → «- », абзацы — строки."""
    import zipfile
    from xml.etree import ElementTree as ET

    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    lines = []
    for p in root.iter(f"{_W}p"):
        parts = []
        for el in p.iter():
            if el.tag == f"{_W}t" and el.text:
                parts.append(el.text)
            elif el.tag in (f"{_W}tab", f"{_W}br"):
                parts.append(" ")
        text = " ".join("".join(parts).split())
        style = p.find(f"{_W}pPr/{_W}pStyle")
        name = (style.get(f"{_W}val") or "").lower() if style is not None else ""
        if not text:
            if lines and lines[-1]:
                lines.append("")
            continue
        if "heading" in name or "заголов" in name or name == "title":
            lines.append("# " + text)
        elif p.find(f"{_W}pPr/{_W}numPr") is not None or "list" in name:
            lines.append("- " + text)
        else:
            lines.append(text)
    return "\n".join(lines).strip()


def read_text_file(path: str | Path) -> str:
    path = Path(path)
    if path.suffix.lower() == ".docx":
        return docx_text(path)
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


_DAYS = ("первое второе третье четвёртое пятое шестое седьмое восьмое девятое десятое одиннадцатое "
         "двенадцатое тринадцатое четырнадцатое пятнадцатое шестнадцатое семнадцатое восемнадцатое "
         "девятнадцатое двадцатое").split()
_MONTHS = ("января февраля марта апреля мая июня июля августа сентября октября ноября декабря").split()


def date_words(d) -> str:
    """23 октября → «Двадцать третье октября», как пишут в школьных тетрадях."""
    n = d.day
    if n <= 20:
        day = _DAYS[n - 1]
    elif n == 30:
        day = "тридцатое"
    else:
        day = ("двадцать " if n < 30 else "тридцать ") + _DAYS[n % 10 - 1]
    return f"{day[0].upper()}{day[1:]} {_MONTHS[d.month - 1]}"


def next_question_number(text_before: str) -> int:
    """Номер следующего вопроса: на единицу больше последнего «N.» выше курсора."""
    import re

    nums = re.findall(r"^\s*(\d{1,3})[.)]\s", text_before, re.M)
    return int(nums[-1]) + 1 if nums else 1
