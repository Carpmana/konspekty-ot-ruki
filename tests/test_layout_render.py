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
