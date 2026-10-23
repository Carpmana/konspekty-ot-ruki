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
from .extract import import_files
from .profile import PROFILE_FILE, GlyphSample, Profile, safe_folder_name
from .render import PAPER_COLOR, render_page, save_pdf
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
NOTEBOOK_LINE_PITCH_MM = 8.0  # тетрадь в линейку
DEFAULT_SEED = 3  # вариант оформления, который выбрали в прототипе
PREVIEW_DPI = 110
EXPORT_DPI = 200
PRINT_DPI = 300


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

    def summary(self) -> str:
        pages = ", ".join(str(p + 1) for p in sorted(set(self.pages_found))) or "нет"
        lines = [f"Профиль «{self.profile_name}»", f"Найдены страницы бланка: {pages}",
                 f"Добавлено образцов: {self.added} (всего в профиле: {self.total_samples})"]
        if self.crossed:
            lines.append(f"Отключены образцы, похожие на зачёркнутые: {' '.join(self.crossed)}. "
                         "Вернуть их можно в меню Почерк → Образцы букв.")
        if self.skipped:
            lines.append("Пропущены, уже импортированы раньше:")
            lines += [f"  • {Path(f).name}" for f in self.skipped]
        if self.files_without_markers:
            lines.append("Не найдены угловые метки бланка (лист должен быть виден целиком):")
            lines += [f"  • {f}" for f in self.files_without_markers]
        return "\n".join(lines)


def import_scans(profile_dir: str | Path, name: str, files: list[str | Path]) -> ImportResult:
    """Добавляет образцы из сканов бланка в профиль; создаёт профиль, если его нет."""
    root = Path(profile_dir)
    prof = Profile.load(root) if (root / PROFILE_FILE).exists() else Profile.create(root, name)
    new, skipped = [], []
    for f in map(Path, files):
        (skipped if f.exists() and prof.is_imported(f) else new).append(f)
    if not new:
        return ImportResult(root, prof.name, total_samples=len(prof.samples), skipped=[str(f) for f in skipped])
    rep = import_files(new)
    added = prof.add_extracted(rep.samples)
    crossed = disable_crossed(prof, among=added, save=False)
    for f in new:
        prof.mark_imported(f)
    prof.save()
    return ImportResult(root, prof.name, list(rep.pages_found), len(added), rep.empty_cells,
                        list(rep.files_without_markers), len(prof.samples), [str(f) for f in skipped],
                        [s.text for s in crossed])


def disable_crossed(prof: Profile, among: list[GlyphSample] | None = None, save: bool = True) -> list[GlyphSample]:
    """Отключает образцы, похожие на зачёркнутые (при импорте — только среди
    новых, чтобы не трогать то, что пользователь вернул сам). Они остаются в
    профиле, и их можно вернуть в окне «Образцы букв»."""
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
                            margin_right_mm=f.inner_mm)


@dataclass
class Rendered:
    images: list[Image.Image]
    missing: set[str]
    dpi: int
    size_mm: tuple[float, float] = (210.0, 297.0)
    labels: list[str] = field(default_factory=list)  # подписи сторон листков (для разворота)

    @property
    def is_spread(self) -> bool:
        return bool(self.labels)

    def side_indices(self, inner: bool) -> list[int]:
        """Стороны разворота: снаружи (чётные) или внутри (нечётные)."""
        return list(range(int(inner), len(self.images), 2))


def _mirror_page(page: lay.Page, dx: float) -> lay.Page:
    """Сдвигает строки правой страницы тетради: поле у неё справа."""
    glyphs = [replace(g, x=g.x + dx) for g in page.glyphs]
    conns = [replace(c, p0=(c.p0[0] + dx, c.p0[1]), p1=(c.p1[0] + dx, c.p1[1])) for c in page.connectors]
    return replace(page, glyphs=glyphs, connectors=conns)


def _ink_only(im: Image.Image, opts: Options, dpi: int) -> Image.Image:
    """Белый фон вместо бумаги и сдвиг под принтер: клетки уже есть на листке."""
    a = np.asarray(im, np.float32) * (255.0 / PAPER_COLOR)
    out = Image.fromarray(np.clip(np.rint(a), 0, 255).astype(np.uint8), "RGB")
    dx, dy = round(mm_to_px(opts.offset_x_mm, dpi)), round(mm_to_px(opts.offset_y_mm, dpi))
    if dx or dy:
        moved = Image.new("RGB", out.size, (255, 255, 255))
        moved.paste(out, (dx, dy))
        out = moved
    return out


def render_text(text: str, prof: Profile, opts: Options, dpi: int = PREVIEW_DPI,
                for_print: bool = False) -> Rendered:
    """Текст → картинки страниц. Вёрстка в миллиметрах, поэтому предпросмотр
    и печать при разном dpi дают одинаковые страницы.

    for_print с real_paper: на картинке только текст (бумага — настоящий листок)."""
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
        if ink_only:
            ps = replace(ps, paper="blank", paper_texture=False)
        im = render_page(page, prof, ps, i)
        images.append(_ink_only(im, opts, dpi) if ink_only else im)
    r = Rendered(images, set(layout.missing), dpi, f.size_mm)
    return to_spreads(r) if opts.use_spread else r


def to_spreads(r: Rendered) -> Rendered:
    """Страницы тетради → стороны развёрнутых двойных листков (две страницы рядом).

    Двойной листок — страницы 1–4. Снаружи: слева 4, справа 1; внутри:
    слева 2, справа 3. Сначала печатается наружная сторона, потом листок
    переворачивают и печатают внутреннюю."""
    w, h = r.images[0].size
    sides, labels = [], []
    for k in range(0, len(r.images), 4):
        p = r.images[k:k + 4]
        n = k // 4 + 1
        for left, right, where, nums in ((p[3], p[0], "снаружи", (k + 4, k + 1)),
                                         (p[1], p[2], "внутри", (k + 2, k + 3))):
            side = Image.new("RGB", (2 * w, h), (255, 255, 255))
            side.paste(left, (0, 0))
            side.paste(right, (w, 0))
            sides.append(side)
            labels.append(f"Листок {n}, {where}: страницы {nums[0]} и {nums[1]}")
    W, H = r.size_mm
    return Rendered(sides, r.missing, r.dpi, (2 * W, H), labels)


def export_pdf(text: str, prof: Profile, opts: Options, path: str | Path, dpi: int = EXPORT_DPI) -> Rendered:
    r = render_text(text, prof, opts, dpi, for_print=True)
    save_pdf(r.images, path, dpi)
    return r
