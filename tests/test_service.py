import pymupdf
import pytest

from konspekt import service as sv
from konspekt.profile import Profile

TEXT = "# Заголовок\nОщущение — это отражение свойств предметов.\n- пункт списка"


def test_list_profiles(profile, tmp_path):
    assert sv.list_profiles(tmp_path / "нет такой папки") == []
    found = sv.list_profiles(profile.root.parent)
    assert ("Тест", profile.root) in found


def test_broken_profile_is_skipped(profile, tmp_path):
    bad = tmp_path / "плохой"
    bad.mkdir()
    (bad / "profile.json").write_text("{}", encoding="utf-8")
    assert sv.list_profiles(tmp_path) == []
    errors = []
    assert sv.list_profiles(tmp_path, errors) == []
    assert len(errors) == 1 and errors[0].startswith("плохой:")


def test_render_preview_and_export_same_pages(profile, tmp_path):
    opts = sv.Options(seed=3)
    small = sv.render_text(TEXT, profile, opts, dpi=60)
    assert len(small.images) == 1
    pdf = tmp_path / "конспект.pdf"
    big = sv.export_pdf(TEXT, profile, opts, pdf, dpi=100)
    assert len(big.images) == len(small.images)
    with pymupdf.open(pdf) as d:
        assert d.page_count == 1
        w_mm = d[0].rect.width / 72 * 25.4
        assert abs(w_mm - 210) < 1.5  # A4 в реальном размере


def test_empty_text_gives_no_pages(profile):
    assert sv.render_text("  \n ", profile, sv.Options()).images == []


def test_options_map_to_settings():
    s = sv.Options(paper="lines", page="A5", seed=7, neatness=1.3, size_mm=None, pitch_mm=8).settings(150)
    assert (s.paper, s.page, s.seed, s.neatness, s.x_height_mm, s.line_pitch_mm, s.dpi) == \
        ("lines", "A5", 7, 1.3, None, 8, 150)


def test_import_scans_creates_then_extends(filled_photos, tmp_path):
    root = sv.profile_dir_for(tmp_path, "Мой почерк")
    first = sv.import_scans(root, "Мой почерк", filled_photos[:1])
    assert first.added > 0 and first.pages_found == [0]
    second = sv.import_scans(root, "Мой почерк", filled_photos[1:2])
    assert second.total_samples == first.added + second.added
    assert Profile.load(root).name == "Мой почерк"
    assert "Добавлено образцов" in second.summary()
    again = sv.import_scans(root, "Мой почерк", filled_photos[:2])
    assert again.added == 0 and len(again.skipped) == 2
    assert again.total_samples == second.total_samples
    assert "уже импортированы" in again.summary()


def test_coverage_text(profile):
    text = sv.coverage_text(profile)
    assert "Строчные" in text and "частых букв" in text


LONG = "# Конспект\n" + "\n".join(["Ощущение — это отражение отдельных свойств предметов при их воздействии."] * 30)


def test_notebook_sheet_real_size(profile, tmp_path):
    pdf = tmp_path / "тетрадь.pdf"
    sv.export_pdf(TEXT, profile, sv.Options(page="notebook"), pdf, dpi=60)
    with pymupdf.open(pdf) as d:
        w, h = (d[0].rect.width / 72 * 25.4, d[0].rect.height / 72 * 25.4)
    assert abs(w - 170) < 1.5 and abs(h - 205) < 1.5


def test_notebook_margin_is_outside(profile):
    import numpy as np

    opts = sv.Options(page="notebook", seed=2)
    assert opts.margin_mode == "outer"
    r = sv.render_text(LONG, profile, opts, dpi=60)
    assert len(r.images) >= 2
    margin = np.array([226, 104, 118])

    def red_columns(im):
        a = np.asarray(im, np.int16)
        hit = (np.abs(a - margin).sum(axis=2) < 60).mean(axis=0) > 0.5
        return np.nonzero(hit)[0] / im.width

    right_page, left_page = red_columns(r.images[0]), red_columns(r.images[1])
    assert len(right_page) and right_page.min() > 0.8  # стр. 1 — правая, поле справа
    assert len(left_page) and left_page.max() < 0.2  # стр. 2 — левая, поле слева


def test_real_paper_prints_only_ink(profile):
    import numpy as np

    opts = sv.Options(page="notebook", real_paper=True)
    preview = sv.render_text(TEXT, profile, opts, dpi=60)
    printed = sv.render_text(TEXT, profile, opts, dpi=60, for_print=True)
    a = np.asarray(printed.images[0])
    assert (a[:20, :20] == 255).all()  # ни клетки, ни бумаги — только чернила
    assert (a.min(axis=2) < 150).any()  # а текст есть
    assert not (np.asarray(preview.images[0])[:20, :20] == 255).all()

    moved = sv.render_text(TEXT, profile, sv.Options(page="notebook", real_paper=True, offset_x_mm=5),
                           dpi=60, for_print=True)
    cols = lambda im: np.nonzero((np.asarray(im).min(axis=2) < 150).any(axis=0))[0].min()
    assert cols(moved.images[0]) - cols(printed.images[0]) == round(5 * 60 / 25.4)


@pytest.mark.parametrize("pitch", [8.0, 10.0, 7.5])
def test_lines_under_text(profile, pitch):
    import math

    from konspekt import layout as lay

    s = sv.Options(paper="lines", pitch_mm=pitch).settings(60)
    first_line = s.margin_top_mm + pitch
    first_base = math.ceil((s.margin_top_mm + pitch) / s.grid_mm) * s.grid_mm
    assert first_line == pytest.approx(first_base)
    lay.typeset(TEXT, profile, s)


def crossed_copy(profile, tmp_path):
    """Копия профиля, в которой один образец перечёркнут крестом."""
    import shutil

    import cv2
    import numpy as np
    from PIL import Image

    root = tmp_path / "Тест"
    shutil.copytree(profile.root, root)
    prof = Profile.load(root)
    s = next(s for s in prof.samples if s.text == "п" and len(prof.variants("п")) >= 3)
    p = root / s.file
    a = np.array(Image.open(p))
    h, w = a.shape
    cv2.line(a, (0, 0), (w - 1, h - 1), 255, 12)
    cv2.line(a, (w - 1, 0), (0, h - 1), 255, 12)
    Image.fromarray(a).save(p)
    return Profile.load(root), s.id


def test_crossed_sample_is_found_and_disabled(profile, tmp_path):
    assert profile.find_crossed() == []  # аккуратные образцы не трогаем
    prof, sid = crossed_copy(profile, tmp_path)
    assert [s.id for s in prof.find_crossed()] == [sid]
    assert sv.disable_crossed(prof, among=[]) == []
    assert [s.id for s in sv.disable_crossed(prof)] == [sid]
    again = Profile.load(prof.root)
    assert not next(s for s in again.samples if s.id == sid).enabled
    assert again.find_crossed() == []


def test_import_summary_mentions_crossed():
    r = sv.ImportResult(profile_dir=None, profile_name="Тест", crossed=["п"])
    assert "зачёркнутые: п" in r.summary()


def test_double_sheet_spread(profile):
    import numpy as np

    plain = sv.render_text(TEXT, profile, sv.Options(page="notebook"), dpi=40)
    assert len(plain.images) == 1
    r = sv.render_text(TEXT, profile, sv.Options(page="notebook", spread=True), dpi=40)
    # одна страница текста → один двойной листок: снаружи (4|1) и внутри (2|3)
    assert len(r.images) == 2 and r.is_spread
    assert r.size_mm == (340.0, 205.0)
    w, h = plain.images[0].size
    assert r.images[0].size == (2 * w, h)
    assert "4 и 1" in r.labels[0] and "2 и 3" in r.labels[1]
    assert r.side_indices(inner=False) == [0] and r.side_indices(inner=True) == [1]
    # текст стр. 1 — правая половина наружной стороны
    assert np.array_equal(np.asarray(r.images[0])[:, w:], np.asarray(plain.images[0]))
    # A4 разворот не делает
    assert not sv.render_text(TEXT, profile, sv.Options(page="A4", spread=True), dpi=40).is_spread


def test_drawn_sample_is_saved_and_removed(profile, tmp_path):
    import shutil

    root = tmp_path / "Тест"
    shutil.copytree(profile.root, root)
    prof = Profile.load(root)
    before = len(prof.variants("ж"))
    # «ж» из трёх штрихов, строчная высотой ~4 мм над базовой линией 16 мм
    strokes = [[(10, 12), (12, 14), (14, 16)], [(14, 12), (14, 16)], [(18, 12), (16, 14), (14, 16)]]
    alpha, base = sv.strokes_to_alpha(strokes, 0.35, 16.0)
    assert alpha.max() > 0.9 and 0 < base <= alpha.shape[0]
    s = sv.add_drawn_sample(prof, "ж", strokes, 16.0)
    again = Profile.load(root)
    assert len(again.variants("ж")) == before + 1
    got = next(x for x in again.samples if x.id == s.id)
    assert got.source == "нарисовано в программе" and (root / got.file).exists()
    # высота строчной ~4 мм при 300 dpi
    assert 35 < got.baseline < 70
    again.remove(s.id)
    again.save()
    assert not (root / got.file).exists()
    assert len(Profile.load(root).variants("ж")) == before
