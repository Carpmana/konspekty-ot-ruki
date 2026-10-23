"""Вёрстка: текст → размещённые на страницах образцы.

Здесь решается, какой образец взять для каждой буквы, где он встанет, как
плывёт строка и где переносить слово. Рисование — в render.py.
"""

import math
from pathlib import Path
from dataclasses import dataclass, field

import numpy as np
import pyphen
from PIL import Image, ImageDraw, ImageFont

from . import document as doc
from .charset import BODY, HEADING
from .profile import SAMPLE_DPI, GlyphSample, Profile, stroke_width_px
from .units import A4_MM, A5_MM, mm_to_px, px_to_mm
from .shape import ROW_MM, band_profile, edges, entry_point, exit_point, optical_x
from .variation import AR1, SmoothNoise, VariantPicker

FALLBACK_FONT = Path(__file__).parent / "assets" / "DejaVuSans.ttf"
TIGHT_PUNCT = set(".,:;!?»)")
TRAIL_PUNCT = ".,:;!?»)"
ARROWS = {"->": "right", "→": "right", "=>": "double", "⇒": "double",
          "<-": "left", "←": "left", "<->": "both", "↔": "both"}
SCRIPT_SCALE = 0.62
LATIN_TWINS = dict(zip("ABCEHKMOPTXaceopxyu", "АВСЕНКМОРТХасеорхуи"))


def script_marks(word: str) -> tuple[str, list[str]]:
    """«x^2», «x^{10}», «H_2O» → текст без значков и пометки sup/sub для каждой буквы."""
    if len(word) < 3 or not any(c in word[1:] for c in "^_"):
        return word, [""] * len(word)
    out, marks, i = [], [], 0
    while i < len(word):
        c = word[i]
        if c in "^_" and i > 0 and i + 1 < len(word):
            mode = "sup" if c == "^" else "sub"
            if word[i + 1] == "{" and "}" in word[i + 2:]:
                j = word.index("}", i + 2)
                part, i = word[i + 2:j], j + 1
            else:
                j = i + 1
                while j < len(word) and word[j].isdigit():
                    j += 1
                j = max(j, i + 2)
                part, i = word[i + 1:j], j
            out += list(part)
            marks += [mode] * len(part)
            continue
        out.append(c)
        marks.append("")
        i += 1
    return "".join(out), marks


def make_typo(word: str, rng: np.random.Generator) -> str:
    """Правдоподобная описка: переставлены две соседние буквы или слово брошено на середине."""
    if rng.random() < 0.35:
        return word[:max(2, int(len(word) * rng.uniform(0.4, 0.7)))]
    for _ in range(6):
        k = int(rng.integers(1, len(word) - 1))
        if word[k] != word[k + 1]:
            return word[:k] + word[k + 1] + word[k] + word[k + 2:]
    return word[:-1]
MAX_CLUSTER = 4


@dataclass
class Settings:
    page: str = "A4"  # A4 | A5
    page_size_mm: tuple[float, float] | None = None  # свой размер листа (тетрадь), важнее page
    paper: str = "grid"  # grid | lines | blank
    dpi: int = 200
    grid_mm: float = 5.0
    line_pitch_mm: float = 10.0
    margin_left_mm: float = 25.0
    margin_right_mm: float = 8.0
    margin_top_mm: float = 10.0
    margin_bottom_mm: float = 10.0
    margin_line: bool = True  # красная линия поля
    indent_mm: float = 10.0
    x_height_mm: float | None = None  # None — как в образцах
    ink_color: tuple[int, int, int] | None = None
    neatness: float = 1.0  # 0.5 — аккуратнее, 1.5 — небрежнее
    seed: int = 1
    paper_texture: bool = True
    highlight_missing: bool = False
    tiredness: float = 0.0  # 0–1: к концу конспекта почерк крупнее, размашистее и небрежнее
    corrections: float = 0.0  # доля слов, перед которыми пишется и зачёркивается ошибка

    @property
    def page_mm(self) -> tuple[float, float]:
        if self.page_size_mm:
            return self.page_size_mm
        return A5_MM if self.page.upper() == "A5" else A4_MM


@dataclass
class Glyph:
    sample: GlyphSample
    text: str
    x: float  # мм: левый край картинки образца
    y: float  # мм: базовая линия
    scale: float  # мм на пиксель образца
    shear: float = 0.0
    rot: float = 0.0
    opacity: float = 1.0
    fallback: bool = False


@dataclass
class Connector:
    p0: tuple[float, float]
    p1: tuple[float, float]
    width_mm: float
    opacity: float = 0.9


@dataclass
class InkLine:
    """Штрих от руки: подчёркивание, рамка, стрелка, зачёркивание."""
    points: list[tuple[float, float]]
    width_mm: float
    opacity: float = 0.9


@dataclass
class TraceLine:
    words: list[str] = field(default_factory=list)
    hyphen: bool = False


@dataclass
class Page:
    glyphs: list[Glyph] = field(default_factory=list)
    connectors: list[Connector] = field(default_factory=list)
    trace: list[TraceLine] = field(default_factory=list)
    lines: list[InkLine] = field(default_factory=list)


@dataclass
class WordPlan:
    glyphs: list[Glyph]  # координаты относительно начала слова и базовой линии
    connectors: list[Connector]
    width: float
    trace: str | None  # None — служебный знак (маркер списка)
    lines: list[InkLine] = field(default_factory=list)
    deco: frozenset = frozenset()  # "under" — подчёркнуто, "box" — в рамке


@dataclass
class Layout:
    pages: list[Page]
    missing: set[str]
    settings: Settings


def _mm_per_px(scale_ratio: float) -> float:
    return px_to_mm(1.0, SAMPLE_DPI) * scale_ratio


class FallbackGlyphs:
    """Запасные глифы из TTF для символов, которых нет в профиле."""

    def __init__(self, profile: Profile):
        self.profile = profile
        self.items: dict[str, GlyphSample] = {}

    def get(self, ch: str) -> GlyphSample:
        if ch not in self.items:
            xh_px = mm_to_px(self.profile.params.x_height_mm, SAMPLE_DPI)
            size = max(8, int(round(xh_px / 0.55)))
            font = ImageFont.truetype(str(FALLBACK_FONT), size)
            asc, desc = font.getmetrics()
            img = Image.new("L", (size * 2, asc + desc + 8), 0)
            ImageDraw.Draw(img).text((4, 4), ch, fill=255, font=font)
            a = np.asarray(img, np.float32) / 255.0
            ys, xs = np.nonzero(a > 0.05)
            if xs.size == 0:  # пробельный символ
                a, base = np.zeros((4, max(4, size // 3)), np.float32), 4.0
            else:
                y0, x0 = ys.min(), xs.min()
                a = a[y0:ys.max() + 1, x0:xs.max() + 1]
                base = 4 + asc - y0
            sid = f"fallback:{ord(ch)}"
            s = GlyphSample(sid, ch, BODY, "", float(base), a.shape[1], a.shape[0], stroke_width_px(a))
            self.profile._cache[sid] = a
            self.items[ch] = s
        return self.items[ch]


class Typesetter:
    def __init__(self, profile: Profile, settings: Settings):
        self.p = profile
        self.s = settings
        self.hp = profile.params
        self.rng = np.random.default_rng(settings.seed)
        self.picker = VariantPicker(self.rng)
        self.fallbacks = FallbackGlyphs(profile)
        self.clusters = profile.clusters()
        self.missing: set[str] = set()
        self.hyph = pyphen.Pyphen(lang="ru_RU")
        xh = settings.x_height_mm or self.hp.x_height_mm
        self.xh_mm = xh
        self._shapes: dict = {}
        self.line_slope = AR1(self.rng, settings.neatness * self.hp.line_slope_jitter_deg, keep=0.6)
        self.line_start = AR1(self.rng, 0.7 * settings.neatness, keep=0.7)
        self.base_scale_ratio = xh / self.hp.x_height_mm
        self.base_scale = _mm_per_px(self.base_scale_ratio)
        self.word_shear = AR1(self.rng, 0.025)
        self.fatigue = 1.0
        self.tired = 0.0  # усталость за весь конспект: tiredness × доля написанного
        self.typo_rng = np.random.default_rng((settings.seed, 7))

    # ---------- штрихи от руки ----------

    def _wobbly(self, pts: list[tuple[float, float]], jitter: float = 0.12) -> list[tuple[float, float]]:
        """Ломаная по точкам с мелким дрожанием руки."""
        out = [pts[0]]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            n = max(2, int(math.hypot(x1 - x0, y1 - y0) / 2.0))
            for k in range(1, n + 1):
                t = k / n
                j = self.rng.normal(0, jitter) if k < n else 0.0
                out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t + j))
        return out

    def _stroke(self) -> float:
        return self.hp.stroke_mm * self.base_scale_ratio

    def build_arrow(self, kind: str, trace: str) -> WordPlan:
        xh, rng = self.xh_mm, self.rng
        length = 2.6 * xh * rng.normal(1.0, 0.08)
        y = -0.5 * xh
        rise = rng.normal(0, 0.15)
        head = 0.55 * xh
        lines = []
        shafts = (y - 0.18 * xh, y + 0.18 * xh) if kind == "double" else (y,)
        for sy in shafts:
            lines.append(InkLine(self._wobbly([(0.0, sy), (length, sy + rise)], 0.06), self._stroke()))
        ends = {"right": [(length, y + rise, -1)], "double": [(length, y + rise, -1)],
                "left": [(0.0, y, 1)], "both": [(length, y + rise, -1), (0.0, y, 1)]}[kind]
        for ex, ey, d in ends:
            for side in (-1, 1):
                a = math.radians(rng.normal(32, 4))
                lines.append(InkLine([(ex + d * head * math.cos(a), ey + side * head * math.sin(a)), (ex, ey)],
                                     self._stroke()))
        return WordPlan([], [], length, trace, lines)

    def strike(self, plan: WordPlan) -> None:
        """Зачёркивает слово одной-двумя линиями."""
        xh, rng = self.xh_mm, self.rng
        for k in range(1 if rng.random() < 0.6 else 2):
            y0 = -0.65 * xh + rng.normal(0, 0.1 * xh) + 0.25 * xh * k
            y1 = y0 + rng.normal(-0.15 * xh, 0.12 * xh)
            plan.lines.append(InkLine(self._wobbly([(-0.4, y0), (plan.width + 0.4, y1)], 0.08), self._stroke()))

    # ---------- слова ----------

    def _choose(self, word: str, i: int, style: str, plain: bool = True) -> tuple[GlyphSample, str, bool]:
        if plain and style == BODY and self.rng.random() < self.hp.cluster_prob:
            for L in range(min(MAX_CLUSTER, len(word) - i), 1, -1):
                sub = word[i:i + L]
                if sub in self.clusters:
                    return self.picker.pick(sub, self.clusters[sub]), sub, False
        ch = word[i]
        vs = self.p.variants(ch, style)
        if not vs and style == HEADING:
            vs = self.p.variants(ch, BODY)
        if not vs and ch in LATIN_TWINS:  # латинская H пишется так же, как русская Н
            vs = self.p.variants(LATIN_TWINS[ch], style) or self.p.variants(LATIN_TWINS[ch], BODY)
        if vs:
            return self.picker.pick(f"{style}:{ch}", vs), ch, False
        self.missing.add(ch)
        return self.fallbacks.get(ch), ch, True

    def _shape(self, sample: GlyphSample):
        """Контуры и точки входа/выхода образца (считаются один раз)."""
        if sample.id not in self._shapes:
            a = self.p.image(sample)
            xh_px = mm_to_px(self.hp.x_height_mm, SAMPLE_DPI) / self.p.size_factor(sample)
            self._shapes[sample.id] = (edges(a), exit_point(a, sample.baseline, xh_px),
                                       entry_point(a, sample.baseline, xh_px))
        return self._shapes[sample.id]

    def build_word(self, word: str, style: str = BODY, trace: str | None = "", tight: float = 1.0) -> WordPlan:
        word, marks = script_marks(word)
        trace = word if trace == "" else trace
        tired = self.tired
        neat = self.s.neatness * self.fatigue * (1.0 + 1.2 * tired)
        rng = self.rng
        word_scale = rng.normal(1.0, 0.03 * neat) * (1.0 + 0.07 * tired)
        shear = self.word_shear.next(neat)
        xh = self.xh_mm
        # Интервалы меряем только в полосе строчных: верхние и нижние
        # выносные элементы у людей свободно нависают над соседями.
        lo, hi = int(round(-1.05 * xh / ROW_MM)), int(round(0.15 * xh / ROW_MM))
        stroke = self.hp.stroke_mm * self.base_scale_ratio
        glyphs: list[Glyph] = []
        conns: list[Connector] = []
        prev: Glyph | None = None
        right = 0.0
        i = 0
        while i < len(word):
            mark = marks[i]
            sample, text, fb = self._choose(word, i, style, plain=not any(marks))
            sc = self.base_scale * self.p.size_factor(sample) * word_scale * rng.normal(1.0, 0.025 * neat)
            dy = rng.normal(0, 0.12 * neat)
            if mark:
                sc *= SCRIPT_SCALE
                dy += -0.8 * xh if mark == "sup" else 0.35 * xh
            e, _, entry = self._shape(sample)
            if prev is None:
                x = 0.0
            else:
                p_edges, p_exit, _ = self._shape(prev.sample)
                join = (not mark and not marks[i - 1] and not prev.fallback and not fb
                        and _is_lower(prev.text[-1]) and _is_lower(text[0])
                        and p_exit is not None and entry is not None and rng.random() < self.hp.join_prob)
                if join:
                    gap = max(0.35, rng.normal(0.9, 0.25))  # место под соединительный штрих
                else:
                    gap = self.hp.optical_gap_mm * max(0.3, rng.normal(1.0, 0.25 * neat)) * (1.0 + 0.25 * tired)
                    if mark or marks[i - 1]:
                        gap *= 0.5
                    if text[0] in TIGHT_PUNCT:
                        gap *= 0.4
                gap *= tight
                pr = band_profile(p_edges, prev.sample.baseline, prev.scale, prev.x, prev.y, lo, hi, "right")
                nl = band_profile(e, sample.baseline, sc, 0.0, dy, lo, hi, "left")
                ox = optical_x(pr, nl, gap)
                if ox is None:
                    ox = right + gap * self.hp.letter_gap_mm / self.hp.optical_gap_mm
                x = ox
                # Нависать можно, но не заезжать глубоко внутрь предыдущей буквы.
                x = max(x, prev.x + prev.sample.width * prev.scale - 0.35 * xh)
                if join:
                    ex = prev.x + p_exit[0] * prev.scale
                    ey = prev.y + (p_exit[1] - prev.sample.baseline) * prev.scale
                    nx = x + entry[0] * sc
                    ny = dy + (entry[1] - sample.baseline) * sc
                    if 0.15 <= nx - ex <= 2.5 and abs(ny - ey) <= 0.9 * xh:
                        conns.append(Connector((ex, ey), (nx, ny), stroke))
            g = Glyph(sample, text, x, dy, sc, shear, rng.normal(0, 0.012 * neat),
                      float(np.clip(rng.normal(0.93, 0.04), 0.8, 1.0)), fb)
            glyphs.append(g)
            right = max(right, x + sample.width * sc)
            prev = g
            i += len(text)
        return WordPlan(glyphs, conns, right, trace)

    # ---------- страницы ----------

    def run(self, blocks: list[doc.Block]) -> Layout:
        W, H = self.s.page_mm
        left = self.s.margin_left_mm + (2.0 if self.s.margin_line else 0.0)
        right = W - self.s.margin_right_mm
        overflow = 2.5  # люди иногда немного заходят за край
        pitch = self.s.line_pitch_mm
        g = self.s.grid_mm
        first_base = math.ceil((self.s.margin_top_mm + pitch) / g) * g
        lines_per_page = max(1, int((H - self.s.margin_bottom_mm - first_base) // pitch) + 1)

        pages: list[Page] = [Page()]
        line_idx = 0
        cur: list[tuple[float, WordPlan]] = []
        cur_trace = TraceLine()
        x = left

        total_words = max(1, sum(len(b.words) for b in blocks))
        done_words = 0

        def flush(align: str = "left") -> None:
            nonlocal cur, cur_trace, line_idx, x
            if cur:
                page = pages[-1]
                base_y = first_base + line_idx * pitch
                tired = self.tired
                neat = self.s.neatness * (1.0 + tired)
                # Соседние строки похожи: наклон и отступ слева меняются плавно,
                # а строка не ложится точно на линию клетки. Уставшая рука
                # заметнее уводит строку вверх.
                slope = math.tan(math.radians(self.hp.line_slope_deg + self.line_slope.next() - 1.2 * tired))
                wobble = SmoothNoise(self.rng, self.hp.baseline_wobble_mm * neat * self.fatigue)
                start_jitter = self.line_start.next()
                base_y += self.rng.normal(0, 0.3 * neat)
                shift = start_jitter
                used = cur[-1][0] + cur[-1][1].width - cur[0][0]
                if align == "center":
                    shift += (right - left - used) / 2 - (cur[0][0] - left)
                elif align == "right":
                    shift += right - used - (cur[0][0] - left) - left - abs(self.rng.normal(1.0, 0.8))

                def at(X: float, dy: float) -> tuple[float, float]:
                    return X, base_y + slope * (X - left) + wobble(X) + dy

                word_dys = []
                for wx, plan in cur:
                    word_dy = self.rng.normal(0, 0.15 * neat)
                    word_dys.append(word_dy)
                    for gl in plan.glyphs:
                        X, Y = at(wx + gl.x + shift, word_dy + gl.y)
                        page.glyphs.append(Glyph(gl.sample, gl.text, X, Y, gl.scale, gl.shear, gl.rot,
                                                 gl.opacity, gl.fallback))
                    for c in plan.connectors:
                        pts = [at(wx + cx + shift, word_dy + cy) for (cx, cy) in (c.p0, c.p1)]
                        page.connectors.append(Connector(pts[0], pts[1], c.width_mm, c.opacity))
                    for ln in plan.lines:
                        pts = [at(wx + lx + shift, word_dy + ly) for (lx, ly) in ln.points]
                        page.lines.append(InkLine(pts, ln.width_mm, ln.opacity))
                self._decorate(page, cur, shift, at)
                page.trace.append(cur_trace)
            cur, cur_trace = [], TraceLine()
            line_idx += 1
            x = left
            if line_idx >= lines_per_page:
                pages.append(Page())
                line_idx = 0
            self.fatigue = 1.0 + 0.5 * line_idx / lines_per_page

        def place(plan: WordPlan, gap: float) -> None:
            nonlocal x
            px = x + (gap if cur else 0.0)
            cur.append((px, plan))
            if plan.trace is not None:
                cur_trace.words.append(plan.trace)
            x = px + plan.width

        def word_gap() -> float:
            return self.hp.word_gap_mm * max(0.4, self.rng.normal(1.0, 0.18 * self.s.neatness))

        deco: set[str] = set()
        for block in blocks:
            if block.kind == doc.GAP:
                flush()
                continue
            style = HEADING if block.kind == doc.HEADING else BODY
            if block.kind == doc.PARAGRAPH:
                x = left + self.s.indent_mm + self.rng.normal(0, 1.2 * self.s.neatness)
            if block.kind == doc.ITEM:
                place(self.build_word("—", BODY, trace=None), 0.0)
            if block.kind == doc.NUMBERED:
                place(self.build_word(block.marker, BODY, trace=None), 0.0)
            deco.clear()
            for w in block.words:
                self.tired = self.s.tiredness * done_words / total_words
                done_words += 1
                w, starts, ends = _deco_marks(w)
                deco |= starts
                if not w:
                    deco -= ends
                    continue
                if w in ARROWS:
                    plan = self.build_arrow(ARROWS[w], w)
                else:
                    plan = self.build_word(w, style)
                plan.deco = frozenset(deco)
                deco -= ends
                gap = word_gap() * (1.0 + 0.3 * self.tired)
                if (style == BODY and self.s.corrections > 0 and not plan.deco and w not in ARROWS
                        and self.typo_rng.random() < self.s.corrections):
                    core = w.rstrip(TRAIL_PUNCT)
                    if len(core) >= 4 and core.isalpha():
                        wrong = self.build_word(make_typo(core, self.typo_rng), style, trace=None)
                        self.strike(wrong)
                        if x + 2 * gap + wrong.width + plan.width <= right:
                            place(wrong, gap)
                if not cur or x + gap + plan.width <= right + overflow:
                    place(plan, gap)
                    continue
                # Чуть не влезает — человек сожмёт буквы в конце строки.
                if x + gap + plan.width <= right + overflow + 0.12 * plan.width:
                    squeezed = self.build_word(w, style, tight=0.45)
                    if x + gap * 0.7 + squeezed.width <= right + overflow:
                        place(squeezed, gap * 0.7)
                        continue
                split = self._hyphenate(w, style, right + overflow - x - gap) if block.kind != doc.HEADING else None
                if split:
                    head, tail = split
                    place(head, gap)
                    cur_trace.hyphen = True
                    flush()
                    place(tail, 0.0)
                else:
                    flush()
                    place(plan, 0.0)
            flush({doc.HEADING: "center", doc.CENTER: "center", doc.RIGHT: "right"}.get(block.kind, "left"))
        if not pages[-1].glyphs and len(pages) > 1:
            pages.pop()
        return Layout(pages, self.missing, self.s)

    def _decorate(self, page: Page, cur: list[tuple[float, "WordPlan"]], shift: float, at) -> None:
        """Подчёркивания и рамки вокруг подряд идущих слов строки."""
        xh, stroke = self.xh_mm, self._stroke()
        for kind in ("under", "box"):
            runs: list[list[float]] = []
            prev_in = False
            for wx, plan in cur:
                inside = kind in plan.deco
                if inside and prev_in:
                    runs[-1][1] = wx + shift + plan.width
                elif inside:
                    runs.append([wx + shift, wx + shift + plan.width])
                prev_in = inside
            for x0, x1 in runs:
                if kind == "under":
                    y = 0.45 * xh + self.rng.normal(0, 0.1)
                    pts = [at(x0 - 0.5, y), at(x1 + 0.8, y + self.rng.normal(0, 0.2))]
                    page.lines.append(InkLine(self._wobbly(pts, 0.07), stroke))
                else:
                    top, bot = -1.75 * xh, 0.75 * xh
                    a, b = x0 - 1.2, x1 + 1.2
                    corners = [at(a, top), at(b, top + self.rng.normal(0, 0.2)), at(b, bot),
                               at(a, bot + self.rng.normal(0, 0.2)), at(a + 0.6, top - 0.3)]
                    page.lines.append(InkLine(self._wobbly(corners, 0.08), stroke))

    def _hyphenate(self, word: str, style: str, room: float) -> tuple[WordPlan, WordPlan] | None:
        core = word.rstrip(".,:;!?»)")
        if len(core) < 5 or not core.isalpha():
            return None
        for pos in reversed(self.hyph.positions(core)):
            if pos < 2 or len(word) - pos < 2:
                continue
            head = self.build_word(word[:pos] + "-", style, trace=word[:pos])
            if head.width <= room:
                return head, self.build_word(word[pos:], style)
        return None


def _deco_marks(word: str) -> tuple[str, set[str], set[str]]:
    """Снимает метки «_…_» (подчеркнуть) и «[[…]]» (рамка) с краёв слова."""
    starts: set[str] = set()
    ends: set[str] = set()
    changed = True
    while changed:
        changed = False
        if word.startswith("[["):
            word, changed = word[2:], True
            starts.add("box")
        if word.startswith("_") and len(word) > 1:
            word, changed = word[1:], True
            starts.add("under")
    core = word.rstrip(TRAIL_PUNCT)
    punct = word[len(core):]
    changed = True
    while changed:
        changed = False
        if core.endswith("]]"):
            core, changed = core[:-2], True
            ends.add("box")
        if core.endswith("_") and len(core) > 1:
            core, changed = core[:-1], True
            ends.add("under")
    return core + punct, starts, ends


def _is_lower(ch: str) -> bool:
    return ch.isalpha() and ch.islower()


def typeset(text: str, profile: Profile, settings: Settings | None = None) -> Layout:
    return Typesetter(profile, settings or Settings()).run(doc.parse(text))


def reconstruct_text(layout: Layout) -> list[str]:
    """Собирает слова обратно из вёрстки — для проверки, что текст не искажён."""
    words: list[str] = []
    carry = ""
    for page in layout.pages:
        for line in page.trace:
            for k, w in enumerate(line.words):
                if carry and k == 0:
                    w, carry = carry + w, ""
                if line.hyphen and k == len(line.words) - 1:
                    carry = w
                    continue
                words.append(w)
    if carry:
        words.append(carry)
    return words
