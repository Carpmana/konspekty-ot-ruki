"""Профиль почерка: папка с образцами и параметрами.

Структура папки:
    profile.json   — имя, параметры почерка, список образцов
    samples/*.png  — образцы: плотность чернил в оттенках серого, 300 dpi
    samples/*@2x.png — те же образцы в 600 dpi для печати (у образцов из
                     прежних версий их нет, программа обходится без них)

Каждый профиль живёт в своей папке, поэтому почерки не смешиваются, а
профиль можно скопировать или передать целиком.
"""

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .charset import BODY, DIGITS, LAT_LOWER, PUNCT, RU_BY_FREQUENCY, RU_LOWER, RU_UPPER
from .extract import HD, ExtractedSample, refill, upscale_legacy
from .units import px_to_mm

SAMPLE_DPI = 300
PROFILE_FILE = "profile.json"
FORMAT_VERSION = 1

# Символы с нижними выносными элементами (в прописи): у них базовую линию
# по низу чернил не уточняем.
DESCENDERS = set("дзруфцщ" + "gjpqy" + ",;")
BASELINE_FIX_MM = 2.5
# Знаки, которые пишутся над строкой, а не стоят на ней: низ чернил у них
# не базовая линия, иначе тире опускается на строку и выглядит как «_».
ABOVE_LINE = set("-–—=+~*^\"'«»°→")

DRAWN_SOURCE = "нарисовано в программе"

# Зачёркнутый образец: чернил в разы больше, чем у других вариантов того же
# символа. У живых вариантов разброс до ~1.75 раза (сканы 11–19).
CROSSED_INK_RATIO = 2.1

# Пределы ручной подстройки в «Редакторе букв».
SCALE_LIMITS = (0.5, 1.8)
RAISE_LIMITS_MM = (-3.0, 3.0)

# Буквы без выносных элементов: по ним меряем высоту строчных.
XHEIGHT_LETTERS = set("аве иклмнопстхчшьэя".replace(" ", "") + "acemnorsuvwxz")


@dataclass
class Point:
    x: float
    y: float


@dataclass
class GlyphSample:
    id: str
    text: str
    style: str
    file: str
    baseline: float  # пикселей от верхнего края картинки
    width: int
    height: int
    stroke_px: float
    entry: Point | None = None  # где начинается штрих слева (для соединений)
    exit: Point | None = None  # где заканчивается штрих справа
    enabled: bool = True
    source: str = ""
    xheight_px: float | None = None  # высота строчных внутри слова (для сочетаний и слов)

    @staticmethod
    def from_dict(d: dict) -> "GlyphSample":
        d = dict(d)
        for k in ("entry", "exit"):
            if d.get(k) is not None:
                d[k] = Point(**d[k])
        return GlyphSample(**d)


@dataclass
class HandParams:
    """Параметры почерка. Часть измеряется по образцам, часть задаётся."""

    x_height_mm: float = 4.0  # высота строчных в образцах
    stroke_mm: float = 0.35
    slant_deg: float = 0.0  # справочно: наклон уже есть в самих образцах
    letter_gap_mm: float = 0.35  # между рамками букв (если контуры не сравнить)
    optical_gap_mm: float = 0.7  # между ближайшими штрихами соседних букв
    word_gap_mm: float = 3.0
    line_slope_deg: float = -0.7  # минус: строка уходит вверх вправо
    line_slope_jitter_deg: float = 0.35
    baseline_wobble_mm: float = 0.35
    join_prob: float = 0.35  # доля соседних строчных, соединённых штрихом
    cluster_prob: float = 0.7  # как часто брать образец слова/сочетания целиком
    capital_ratio: float = 1.6  # высота заглавных относительно строчных (минимум)
    ink_color: tuple[int, int, int] = (38, 48, 140)


@dataclass
class Profile:
    root: Path
    name: str
    params: HandParams = field(default_factory=HandParams)
    samples: list[GlyphSample] = field(default_factory=list)
    created: str = ""
    imported: list[str] = field(default_factory=list)  # sha256 импортированных файлов
    # Ручная подстройка из «Редактора букв». Хранится отдельно от образцов,
    # чтобы профиль открывался и прежними версиями программы.
    letter_adjust: dict[str, dict[str, float]] = field(default_factory=dict)  # текст → {"scale", "raise_mm"}
    variant_scale: dict[str, float] = field(default_factory=dict)  # id образца → множитель размера
    _cache: dict = field(default_factory=dict, repr=False)

    # ---------- хранение ----------

    @staticmethod
    def create(root: str | Path, name: str) -> "Profile":
        root = Path(root)
        if (root / PROFILE_FILE).exists():
            raise FileExistsError(f"Профиль уже существует: {root}")
        (root / "samples").mkdir(parents=True, exist_ok=True)
        p = Profile(root, name, created=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        p.save()
        return p

    @staticmethod
    def load(root: str | Path) -> "Profile":
        root = Path(root)
        f = root / PROFILE_FILE
        if not f.exists():
            raise FileNotFoundError(f"В папке нет профиля почерка: {root}")
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("format") != FORMAT_VERSION:
            raise ValueError(f"Неподдерживаемая версия профиля: {d.get('format')}")
        params = HandParams(**{**d["params"], "ink_color": tuple(d["params"]["ink_color"])})
        return Profile(root, d["name"], params, [GlyphSample.from_dict(s) for s in d["samples"]],
                       d.get("created", ""), list(d.get("imported", [])),
                       {k: dict(v) for k, v in d.get("letter_adjust", {}).items()},
                       dict(d.get("variant_scale", {})))

    def save(self) -> None:
        d = {
            "format": FORMAT_VERSION,
            "name": self.name,
            "created": self.created,
            "params": asdict(self.params),
            "samples": [asdict(s) for s in self.samples],
            "imported": self.imported,
            "letter_adjust": self.letter_adjust,
            "variant_scale": self.variant_scale,
        }
        tmp = self.root / (PROFILE_FILE + ".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.root / PROFILE_FILE)

    # ---------- образцы ----------

    def add_extracted(self, extracted: list[ExtractedSample]) -> list[GlyphSample]:
        added = []
        for e in extracted:
            sid = uuid.uuid4().hex[:12]
            fname = f"samples/{sid}.png"
            img = (np.clip(e.alpha, 0, 1) * 255).astype(np.uint8)
            Image.fromarray(img, "L").save(self.root / fname)
            if e.alpha_hd is not None:
                hd = (np.clip(e.alpha_hd, 0, 1) * 255).astype(np.uint8)
                Image.fromarray(hd, "L").save(self.root / hd_name(fname))
            text = e.cell.request.text
            baseline = refine_baseline(e.alpha, e.baseline, text)
            entry, exit_ = entry_exit_points(e.alpha, baseline)
            xh = estimate_xheight_px(e.alpha, baseline) if len(text) > 1 else None
            s = GlyphSample(sid, text, e.cell.request.style, fname, float(baseline),
                            img.shape[1], img.shape[0], stroke_width_px(e.alpha), entry, exit_, True, e.source, xh)
            self.samples.append(s)
            added.append(s)
        self.measure()
        return added

    def add_drawn(self, text: str, alpha: np.ndarray, baseline: float, style: str = BODY) -> GlyphSample:
        """Образец, нарисованный в окне программы (мышью, тачпадом, пером).
        alpha — плотность чернил 0..1 при 300 dpi, baseline — точно известна."""
        sid = uuid.uuid4().hex[:12]
        fname = f"samples/{sid}.png"
        img = (np.clip(alpha, 0, 1) * 255).astype(np.uint8)
        (self.root / "samples").mkdir(parents=True, exist_ok=True)
        Image.fromarray(img, "L").save(self.root / fname)
        entry, exit_ = entry_exit_points(alpha, baseline)
        xh = estimate_xheight_px(alpha, baseline) if len(text) > 1 else None
        s = GlyphSample(sid, text, style, fname, float(baseline), img.shape[1], img.shape[0],
                        stroke_width_px(alpha), entry, exit_, True, DRAWN_SOURCE, xh)
        self.samples.append(s)
        self.measure()
        return s

    def remove(self, sample_id: str, measure: bool = True) -> None:
        """Удаляет образец вместе с картинкой: неудачный вариант или «переделать»."""
        s = next(x for x in self.samples if x.id == sample_id)
        self.samples.remove(s)
        for key in [k for k in self._cache if k.split(":")[0] == sample_id]:
            self._cache.pop(key, None)
        self.variant_scale.pop(sample_id, None)
        (self.root / s.file).unlink(missing_ok=True)
        (self.root / hd_name(s.file)).unlink(missing_ok=True)
        if measure:
            self.measure()

    # ---------- ручная подстройка размеров ----------

    def letter_scale(self, text: str) -> float:
        return float(self.letter_adjust.get(text, {}).get("scale", 1.0))

    def letter_raise_mm(self, text: str) -> float:
        """На сколько мм поднять букву над строкой (минус — опустить)."""
        return float(self.letter_adjust.get(text, {}).get("raise_mm", 0.0))

    def set_letter_adjust(self, text: str, scale: float | None = None, raise_mm: float | None = None) -> None:
        a = dict(self.letter_adjust.get(text, {}))
        if scale is not None:
            a["scale"] = round(float(np.clip(scale, *SCALE_LIMITS)), 3)
        if raise_mm is not None:
            a["raise_mm"] = round(float(np.clip(raise_mm, *RAISE_LIMITS_MM)), 2)
        a = {k: v for k, v in a.items() if v != {"scale": 1.0, "raise_mm": 0.0}[k]}
        if a:
            self.letter_adjust[text] = a
        else:
            self.letter_adjust.pop(text, None)

    def sample_scale(self, s: GlyphSample) -> float:
        return float(self.variant_scale.get(s.id, 1.0))

    def set_sample_scale(self, sample_id: str, scale: float) -> None:
        k = round(float(np.clip(scale, *SCALE_LIMITS)), 3)
        if k == 1.0:
            self.variant_scale.pop(sample_id, None)
        else:
            self.variant_scale[sample_id] = k

    def user_scale(self, s: GlyphSample) -> float:
        """Итоговый ручной множитель: вся буква × этот вариант."""
        return self.letter_scale(s.text) * self.sample_scale(s)

    def is_imported(self, path: str | Path) -> bool:
        return file_sha256(path) in self.imported

    def mark_imported(self, path: str | Path) -> None:
        h = file_sha256(path)
        if h not in self.imported:
            self.imported.append(h)

    def image(self, s: GlyphSample) -> np.ndarray:
        """Образец для вёрстки и отрисовки: чернила залиты (extract.refill)."""
        if s.id not in self._cache:
            self._cache[s.id] = refill(self.raw_image(s))
        return self._cache[s.id]

    def raw_image(self, s: GlyphSample) -> np.ndarray:
        """Образец как сохранён, с живой плотностью ручки — для измерений."""
        with Image.open(self.root / s.file) as im:
            return np.asarray(im.convert("L"), np.float32) / 255.0

    def print_image(self, s: GlyphSample) -> tuple[np.ndarray, int]:
        """Образец для печати и во сколько раз он плотнее 300 dpi.
        Размеры и точки в GlyphSample по-прежнему в пикселях 300 dpi."""
        key = f"{s.id}:hd"
        if key not in self._cache:
            hd = self.root / hd_name(s.file) if s.file else None
            if hd is not None and hd.exists():
                with Image.open(hd) as im:
                    self._cache[key] = (refill(np.asarray(im.convert("L"), np.float32) / 255.0, HD), HD)
            elif s.file:
                self._cache[key] = (upscale_legacy(self.image(s), s.text), HD)
            else:
                self._cache[key] = (self.image(s), 1)
        return self._cache[key]

    def variants(self, text: str, style: str = BODY) -> list[GlyphSample]:
        return [s for s in self.samples if s.enabled and s.text == text and s.style == style]

    def clusters(self) -> dict[str, list[GlyphSample]]:
        out: dict[str, list[GlyphSample]] = {}
        for s in self.samples:
            if s.enabled and len(s.text) > 1 and s.style == BODY and self.cluster_size_ok(s):
                out.setdefault(s.text, []).append(s)
        return out

    # ---------- измерения ----------

    def measure(self) -> None:
        """Пересчитывает параметры, которые можно измерить по образцам."""
        hs = [px_to_mm(s.baseline, SAMPLE_DPI) for s in self.samples
              if s.enabled and s.style == BODY and s.text in XHEIGHT_LETTERS]
        if hs:
            self.params.x_height_mm = round(float(np.median(hs)), 2)
        sw = [s.stroke_px for s in self.samples if s.enabled and s.stroke_px > 0]
        if sw:
            self.params.stroke_mm = round(px_to_mm(float(np.median(sw)), SAMPLE_DPI), 3)

    def find_crossed(self) -> list[GlyphSample]:
        """Включённые образцы, похожие на зачёркнутые: чернил намного больше,
        чем у остальных вариантов того же символа. Нужно хотя бы 3 варианта,
        иначе сравнивать не с чем."""
        groups: dict[tuple[str, str], list[GlyphSample]] = {}
        for s in self.samples:
            if s.enabled:
                groups.setdefault((s.text, s.style), []).append(s)
        out = []
        for group in groups.values():
            if len(group) < 3:
                continue
            ink = [float(self.raw_image(s).sum()) for s in group]
            med = float(np.median(ink))
            out += [s for s, v in zip(group, ink) if med > 0 and v > CROSSED_INK_RATIO * med]
        return out

    def cluster_size_ok(self, s: GlyphSample) -> bool:
        """Образец слова, размер которого не удалось надёжно оценить, лучше не
        брать: он выделится в строке. Вместо него слово соберётся из букв."""
        if not s.xheight_px:
            return False
        ratio = self.params.x_height_mm * SAMPLE_DPI / 25.4 / s.xheight_px
        return 0.75 <= ratio <= 1.33

    def size_factor(self, s: GlyphSample) -> float:
        """Во сколько раз увеличить образец, чтобы его строчные совпали по высоте
        с отдельными буквами. Слова в бланке часто пишут мельче букв."""
        xh = self.params.x_height_mm * SAMPLE_DPI / 25.4
        if len(s.text) == 1 and s.text.isupper():
            # Заглавные в клетках бланка обычно пишут мельче, чем в тексте.
            cap = max(s.baseline - 3, 1.0)
            return float(np.clip(self.params.capital_ratio * xh / cap, 1.0, 2.0))
        if not s.xheight_px or s.style != BODY:
            return 1.0
        target = xh
        ratio = target / s.xheight_px
        # Оценка по картинке ненадёжна: сильное расхождение скорее ошибка оценки.
        return float(ratio) if 0.75 <= ratio <= 1.33 else 1.0

    def coverage(self) -> dict:
        """Каких символов нет или мало: честный отчёт о полноте профиля."""
        def count(ch: str) -> int:
            return len(self.variants(ch))
        groups = {"строчные": RU_LOWER, "заглавные": RU_UPPER, "цифры": DIGITS,
                  "знаки": PUNCT, "латиница": LAT_LOWER}
        out = {}
        for gname, chars in groups.items():
            missing = [c for c in chars if count(c) == 0]
            single = [c for c in chars if count(c) == 1]
            out[gname] = {"всего": len(chars), "нет": "".join(missing), "один вариант": "".join(single)}
        out["сочетания и слова"] = sorted(self.clusters())
        out["стоит добавить"] = "".join(c for c in RU_BY_FREQUENCY[:12] if count(c) < 6)
        return out


def hd_name(file: str) -> str:
    """samples/abc.png → samples/abc@2x.png"""
    p = Path(file)
    return str(p.with_name(f"{p.stem}@{HD}x{p.suffix}").as_posix())


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stroke_width_px(alpha: np.ndarray) -> float:
    mask = (alpha > 0.35).astype(np.uint8)
    if mask.sum() == 0:
        return 0.0
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
    skel = cv2.ximgproc.thinning(mask * 255) > 0
    vals = dist[skel]
    return float(2.0 * np.median(vals)) if vals.size else 0.0


def entry_exit_points(alpha: np.ndarray, baseline: float) -> tuple[Point | None, Point | None]:
    """Точки входа и выхода штриха в полосе строчных — к ним крепятся соединения."""
    mask = alpha > 0.35
    h = alpha.shape[0]
    band_top = int(max(0, baseline - 0.75 * max(baseline, 1)))
    band_bot = int(min(h, baseline + 3))
    band = mask[band_top:band_bot]
    ys, xs = np.nonzero(band)
    if xs.size == 0:
        return None, None
    ys = ys + band_top

    def at(x_target: int) -> Point:
        sel = np.abs(xs - x_target) <= 2
        return Point(float(x_target), float(np.median(ys[sel])))

    return at(int(xs.min())), at(int(xs.max()))


def refine_baseline(alpha: np.ndarray, baseline: float, text: str) -> float:
    """Человек не всегда попадает точно на пунктир. Для символов без нижних
    выносных элементов базовая линия — низ основной части чернил."""
    if any(c in DESCENDERS for c in text) or all(c in ABOVE_LINE for c in text):
        return baseline
    mask = alpha > 0.35
    rows = mask.sum(axis=1)
    if rows.max() == 0:
        return baseline
    if len(text) == 1:
        new = float(np.nonzero(rows)[0].max())
    else:
        dense = np.nonzero(rows >= 0.3 * rows.max())[0]
        new = float(dense.max())
    return new if abs(new - baseline) <= BASELINE_FIX_MM * SAMPLE_DPI / 25.4 else baseline


def estimate_xheight_px(alpha: np.ndarray, baseline: float) -> float | None:
    """Высота строчных в слове: самая плотная полоса строк над базовой линией.
    Выносные элементы (б, д, р, у) тонкие и в эту полосу не попадают."""
    mask = alpha > 0.35
    b = int(min(mask.shape[0], round(baseline) + 2))
    rows = mask[:b].sum(axis=1)
    if rows.size == 0 or rows.max() == 0:
        return None
    dense = rows >= 0.3 * rows.max()
    y = b - 1
    while y > 0 and not dense[y]:
        y -= 1
    bottom = y
    while y > 0 and dense[y - 1]:
        y -= 1
    h = max(bottom, baseline) - y
    return float(h) if h > 5 else None


_NAME_RE = re.compile(r"[^\w\- ]+", re.UNICODE)


def safe_folder_name(name: str) -> str:
    n = _NAME_RE.sub("", name).strip().replace(" ", "_")
    return n or "profile"
