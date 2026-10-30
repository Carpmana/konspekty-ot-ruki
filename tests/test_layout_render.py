import numpy as np
import pytest

from konspekt import document as doc
from konspekt.layout import Settings, reconstruct_text, typeset
from konspekt.render import render, render_page

TEXT = """# Ощущение и восприятие
Ощущение — это отражение отдельных свойств предметов при их воздействии на органы чувств.
Примеры: цвет, запах, температура, звук. Физиологическая основа — анализатор.

- экстероцептивные (внешняя среда): зрение, слух, обоняние, осязание, вкус;
- интероцептивные: боль, голод, жажда.
""" + " ".join(["Неожиданно длинное предложение с многочисленными переносами слов по слогам."] * 40)


def source_words(text):
    return [w for b in doc.parse(text) for w in b.words]


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_text_is_preserved(profile, seed):
    layout = typeset(TEXT, profile, Settings(seed=seed))
    assert len(layout.pages) >= 2
    assert reconstruct_text(layout) == source_words(TEXT)


def test_hyphenation_happens(profile):
    layout = typeset(TEXT, profile, Settings(seed=1))
    assert any(line.hyphen for p in layout.pages for line in p.trace)


@pytest.mark.parametrize("page,paper", [("A4", "grid"), ("A5", "lines"), ("A4", "blank")])
def test_glyphs_inside_page(profile, page, paper):
    s = Settings(seed=5, page=page, paper=paper)
    layout = typeset(TEXT, profile, s)
    W, H = s.page_mm
    for p in layout.pages:
        for g in p.glyphs:
            assert 0 < g.x < W and 0 < g.y < H


def test_same_seed_same_image(profile):
    s = Settings(seed=7, dpi=60)
    a = render(typeset(TEXT[:300], profile, s), profile)[0]
    b = render(typeset(TEXT[:300], profile, s), profile)[0]
    assert np.array_equal(np.asarray(a), np.asarray(b))


def test_other_seed_other_image(profile):
    a = render(typeset(TEXT[:300], profile, Settings(seed=1, dpi=60)), profile)[0]
    b = render(typeset(TEXT[:300], profile, Settings(seed=2, dpi=60)), profile)[0]
    assert not np.array_equal(np.asarray(a), np.asarray(b))


def test_variants_not_repeated_back_to_back(profile):
    layout = typeset("о " * 60, profile, Settings(seed=3))
    ids = [g.sample.id for p in layout.pages for g in p.glyphs if g.text == "о"]
    assert len(ids) == 60
    assert all(a != b for a, b in zip(ids, ids[1:]))
    assert len(set(ids)) == 3


def test_missing_symbols_reported(profile):
    layout = typeset("сумма ∑ и ∫", profile, Settings())
    assert layout.missing == {"∑", "∫"}
    assert reconstruct_text(layout) == ["сумма", "∑", "и", "∫"]


def test_ink_is_drawn(profile):
    s = Settings(seed=1, dpi=80, paper="blank", paper_texture=False)
    layout = typeset("проверка", profile, s)
    img = np.asarray(render_page(layout.pages[0], profile, s))
    assert (img[..., 2].astype(int) - img[..., 0] > 60).sum() > 50  # синие чернила есть


def test_markup_marks_and_scripts():
    from konspekt.layout import _deco_marks, script_marks

    assert _deco_marks("_важно") == ("важно", {"under"}, set())
    assert _deco_marks("слово_,") == ("слово,", set(), {"under"})
    assert _deco_marks("[[_итог_]]") == ("итог", {"box", "under"}, {"box", "under"})
    assert script_marks("x^2") == ("x2", ["", "sup"])
    assert script_marks("H_2O") == ("H2O", ["", "sub", ""])
    assert script_marks("a^{10}") == ("a10", ["", "sup", "sup"])
    assert script_marks("слово") == ("слово", [""] * 5)


def test_underline_box_arrow_drawn(profile):
    layout = typeset("_Важно_ знать: [[итог]] -> вывод, x^2 и H_2O", profile, Settings(seed=1))
    page = layout.pages[0]
    # подчёркивание + рамка + стрелка (стержень и два штриха наконечника)
    assert len(page.lines) == 1 + 1 + 3
    assert reconstruct_text(layout) == ["Важно", "знать:", "итог", "->", "вывод,", "x2", "и", "H2O"]
    im = render_page(page, profile, layout.settings)
    assert np.asarray(im).min() < 120


def test_corrections_strike_some_words(profile):
    text = " ".join(["Неожиданно длинное предложение с многочисленными словами."] * 20)
    plain = typeset(text, profile, Settings(seed=2))
    fixed = typeset(text, profile, Settings(seed=2, corrections=0.15))
    assert not any(p.lines for p in plain.pages)
    assert sum(len(p.lines) for p in fixed.pages) >= 3
    assert reconstruct_text(fixed) == source_words(text)  # описки — не часть текста


def test_tiredness_grows_handwriting(profile):
    text = " ".join(["Неожиданно длинное предложение с многочисленными словами."] * 60)

    def last_scale(t):
        lay = typeset(text, profile, Settings(seed=3, tiredness=t))
        gs = lay.pages[-1].glyphs  # вся страница: 60 букв — слишком мало против случайного выбора вариантов
        return np.mean([g.scale for g in gs]), len(lay.pages)

    calm, tired = last_scale(0.0), last_scale(1.0)
    assert tired[0] > calm[0] * 1.03


def test_numbered_and_right_aligned(profile):
    s = Settings(seed=1)
    layout = typeset(">> 23.10\n1. Вопрос", profile, s)
    page = layout.pages[0]
    W = s.page_mm[0]
    date = [g for g in page.glyphs if g.y < page.glyphs[-1].y - 3]
    assert min(g.x for g in date) > W / 2  # дата справа
    assert reconstruct_text(layout) == ["23.10", "Вопрос"]


def _line_starts(layout):
    starts = []
    for p in layout.pages:
        rows = {}
        for g in p.glyphs:
            rows.setdefault(round(g.y / 10), []).append(g.x)
        starts += [min(v) for v in rows.values()]
    starts = np.array(starts)
    return starts[starts < starts.min() + 8]  # без красной строки абзаца


def test_live_left_edge(profile):
    text = " ".join(["Неожиданно длинное предложение с многочисленными переносами слов по слогам."] * 25)
    s = dict(page_size_mm=(170.0, 205.0), margin_left_mm=20.0, margin_right_mm=4.0)
    flat = _line_starts(typeset(text, profile, Settings(seed=2, live_edge=0.0, **s)))
    live = _line_starts(typeset(text, profile, Settings(seed=2, live_edge=1.0, **s)))
    assert flat.std() < 0.05 and live.std() > 0.8
    # Начало строки гуляет, но не заезжает за красное поле.
    assert live.min() >= 20.0


def test_letter_size_editor_changes_layout(profile, tmp_path):
    import shutil

    from konspekt.profile import Profile

    shutil.copytree(profile.root, tmp_path / "p")
    prof = Profile.load(tmp_path / "p")
    base = typeset("ааа", prof, Settings(seed=1, live_edge=0.0))
    prof.set_letter_adjust("а", scale=1.3, raise_mm=1.0)
    big = typeset("ааа", prof, Settings(seed=1, live_edge=0.0))
    g0, g1 = base.pages[0].glyphs[0], big.pages[0].glyphs[0]
    assert g1.scale == pytest.approx(1.3 * g0.scale, rel=0.01)
    assert g1.y < g0.y - 0.8  # выше строки


def test_trace_makes_solid_smooth_strokes():
    from konspekt.vector import fill, trace

    # Штрих шариковой ручки: пропуск, где шарик не провернулся, и зерно.
    a = np.zeros((40, 120), np.float32)
    a[18:23, 10:110] = 0.9
    a[18:23, 30:32] = 0.0
    a[18:23, 60:110:3] = 0.35
    contours = trace(a, 0.5)
    assert len(contours) == 1  # одна цельная линия, без дыр и обрывков
    alpha, x0, y0 = fill(contours, np.eye(2), np.zeros(2))
    assert x0 <= 10 and y0 <= 18
    assert alpha[20 - y0, 31 - x0] > 0.95 and alpha[20 - y0, 63 - x0] > 0.95
    # толщина как была: 5 пикселей
    assert 4 <= (alpha[:, 50 - x0] > 0.5).sum() <= 7
    # внутри линии сплошная заливка, без светлых точек
    assert alpha[19 - y0:22 - y0, 15 - x0:105 - x0].min() > 0.95


def test_trace_keeps_holes_and_dots():
    import cv2

    from konspekt.vector import fill, trace

    a = np.zeros((80, 80), np.float32)
    cv2.circle(a, (40, 45), 18, 1.0, 4)  # «о»
    cv2.circle(a, (40, 12), 3, 1.0, -1)  # точка над буквой
    alpha, x0, y0 = fill(trace(a, 0.5), np.eye(2), np.zeros(2))
    assert alpha[45 - y0, 40 - x0] < 0.05  # дырка в «о» осталась
    assert alpha[12 - y0, 40 - x0] > 0.9  # точка не пропала
    assert alpha[45 - y0, 22 - x0] > 0.9


def test_smoothness_changes_ink(profile):
    from konspekt.layout import Settings

    def draw(v):
        s = Settings(dpi=100, smoothness=v, paper_texture=False)
        return np.asarray(render_page(typeset("Ощущение и восприятие", profile, s).pages[0], profile, s), np.float32)

    imgs = [draw(v) for v in (0.0, 1.0)]
    assert np.abs(imgs[0] - imgs[1]).mean() > 0.01


def test_black_ink(profile):
    s = Settings(dpi=100, paper_texture=False, paper="blank", ink_color=(24, 24, 28))
    im = np.asarray(render_page(typeset("Ощущение", profile, s).pages[0], profile, s), np.float32)
    ink = im[im.sum(axis=2) < 300]
    assert len(ink) > 50
    # чернила серые, без синевы
    assert np.abs(ink[:, 2] - ink[:, 0]).mean() < 8


def test_hd_print_matches_preview(profile):
    # Печать берёт буквы в 600 dpi, предпросмотр — в 300: буквы должны
    # стоять на тех же местах и быть той же толщины.
    import cv2

    from konspekt.render import HD_MIN_DPI

    s = Settings(seed=2, dpi=HD_MIN_DPI - 50, paper="blank", paper_texture=False)
    page = typeset(TEXT[:200], profile, s).pages[0]
    lo = np.asarray(render_page(page, profile, s).convert("L"), np.float32)
    s2 = Settings(seed=2, dpi=2 * (HD_MIN_DPI - 50), paper="blank", paper_texture=False)
    hi = np.asarray(render_page(page, profile, s2).convert("L"), np.float32)
    hi = cv2.resize(hi, lo.shape[::-1], interpolation=cv2.INTER_AREA)
    ink_lo, ink_hi = 255 - lo, 255 - hi
    assert abs(ink_hi.sum() / ink_lo.sum() - 1) < 0.15
    ys, xs = np.nonzero(ink_lo > 60)
    yh, xh = np.nonzero(ink_hi > 60)
    assert abs(xs.mean() - xh.mean()) < 2 and abs(ys.mean() - yh.mean()) < 2


def test_solid_print_has_no_grey_ink(profile):
    # Принтер печатает серый растром из точек, поэтому для печати каждый
    # пиксель — либо белая бумага, либо чернила в полную силу.
    s = Settings(seed=1, dpi=150, paper="blank", ink_color=(24, 24, 28), solid_print=True)
    im = np.asarray(render(typeset(TEXT[:200], profile, s), profile)[0])
    colors = {tuple(c) for c in im.reshape(-1, 3)}
    assert colors == {(255, 255, 255), (0, 0, 0)}


def test_weight_changes_stroke_gradually(profile):
    # Толщина линии меняется плавно: каждый шаг ползунка даёт чуть больше чернил.
    def ink(w):
        s = Settings(seed=2, dpi=150, paper="blank", weight=w)
        im = np.asarray(render(typeset(TEXT[:120], profile, s), profile)[0].convert("L"), np.float32)
        return float((255 - im).sum())
    vals = [ink(w) for w in (0.62, 0.8, 0.93, 1.0, 1.15, 1.4, 2.0)]
    assert all(a < b for a, b in zip(vals, vals[1:]))
    assert vals[0] < 0.9 * vals[3] and vals[-1] > 1.3 * vals[3]


def test_belarusian_without_samples_is_reported(profile):
    """Нет образцов ў, Ў, І — предупреждаем; і пишется как латинская i,
    обычный апостроф — как ’ (его тоже нет в основном бланке)."""
    layout = typeset("Ўсе дзеці ішлі ў школу. Інфармацыя сям'я", profile, Settings(seed=1))
    assert layout.missing == {"ў", "Ў", "І", "'"}
    assert reconstruct_text(layout) == ["Ўсе", "дзеці", "ішлі", "ў", "школу.", "Інфармацыя", "сям'я"]


def test_hyphenation_language_by_word():
    from konspekt.layout import word_lang
    assert word_lang("understanding") == "en_US"
    assert word_lang("інфармацыя") == "be_BY"
    assert word_lang("информация") == "ru_RU"


def test_hyphenators_survive_missing_dictionary(monkeypatch):
    """Без словаря be_BY (неполная сборка) вёрстка не падает, а берёт русский."""
    import pyphen

    from konspekt import layout as lay

    real = pyphen.Pyphen

    def fake(lang):
        if lang == "be_BY":
            raise KeyError(None)
        return real(lang=lang)

    monkeypatch.setattr(lay.pyphen, "Pyphen", fake)
    h = lay.hyphenators()
    assert set(h) == set(lay.HYPH_LANGS)
    assert h["be_BY"] is h["ru_RU"]


def test_build_keeps_all_hyphenation_dictionaries():
    from pathlib import Path

    from konspekt import layout as lay

    spec = (Path(__file__).parent.parent / "packaging" / "konspekt.spec").read_text(encoding="utf-8")
    for lang in lay.HYPH_LANGS:
        assert f"hyph_{lang}.dic" in spec
