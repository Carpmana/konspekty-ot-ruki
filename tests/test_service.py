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
        # Без потерь: JPEG давал вокруг букв серые точки, а принтер их печатал.
        img = d.extract_image(d[0].get_images()[0][0])
        assert img["ext"] == "png"


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
    cv2.line(a, (0, 0), (w - 1, h - 1), 255, 16)
    cv2.line(a, (w - 1, 0), (0, h - 1), 255, 16)
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
    assert "справа 1" in r.labels[0] and "пусто, не печатается" in r.labels[1]
    assert r.sheets() == [(0, None)]  # одна страница: оборот не печатается
    assert r.side_indices(inner=False) == [0] and r.side_indices(inner=True) == [1]
    # текст стр. 1 — правая половина наружной стороны
    assert np.array_equal(np.asarray(r.images[0])[:, w:], np.asarray(plain.images[0]))
    # A4 разворот не делает
    assert not sv.render_text(TEXT, profile, sv.Options(page="A4", spread=True), dpi=40).is_spread


def test_sheets_stacked_and_nested():
    from PIL import Image

    assert sv.sheet_pages(2, nested=False) == [((4, 1), (2, 3)), ((8, 5), (6, 7))]
    # тетрадка: внешний листок — 1, 2 и 7, 8; внутренний — середина 3–6
    assert sv.sheet_pages(2, nested=True) == [((8, 1), (2, 7)), ((6, 3), (4, 5))]
    assert sv.sheet_pages(1, nested=True) == sv.sheet_pages(1, nested=False)
    pages = [Image.new("RGB", (4, 6), (k * 20, 0, 0)) for k in range(1, 9)]
    base = sv.Rendered(pages, set(), 40, (170.0, 205.0))

    def halves(side):
        return side.getpixel((0, 0))[0] // 20, side.getpixel((4, 0))[0] // 20

    r = sv.to_spreads(base, real=5, nested=True)
    assert [halves(im) for im in r.images] == [(8, 1), (2, 7), (6, 3), (4, 5)]
    assert r.blank == [False] * 4 and r.sheets() == [(0, 1), (2, 3)]
    assert "слева пусто, справа 1" in r.labels[0]
    stack = sv.to_spreads(base, real=5, nested=False)
    assert [halves(im) for im in stack.images] == [(4, 1), (2, 3), (8, 5), (6, 7)]
    assert stack.sheets() == [(0, 1), (2, None)]  # страниц 6 и 7 нет — оборот листка 2 пустой


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
    # высота строчной ~4 мм при 300 dpi плюс поля в две толщины линии
    assert 35 < got.baseline < 75
    again.remove(s.id)
    again.save()
    assert not (root / got.file).exists()
    assert len(Profile.load(root).variants("ж")) == before


def test_docx_text_and_helpers(tmp_path):
    import datetime
    import zipfile

    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = (f'<w:document {w}><w:body>'
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Дроби</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Числитель </w:t></w:r><w:r><w:t>сверху.</w:t></w:r></w:p>'
            '<w:p><w:pPr><w:numPr/></w:pPr><w:r><w:t>пункт</w:t></w:r></w:p>'
            '</w:body></w:document>')
    path = tmp_path / "конспект.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", body)
    assert sv.read_text_file(path) == "# Дроби\nЧислитель сверху.\n- пункт"
    assert sv.date_words(datetime.date(2026, 10, 23)) == "Двадцать третье октября"
    assert sv.date_words(datetime.date(2026, 3, 1)) == "Первое марта"
    assert sv.date_words(datetime.date(2026, 5, 30)) == "Тридцатое мая"
    assert sv.next_question_number("1. a\nтекст\n2) b\n") == 3
    assert sv.next_question_number("") == 1


def test_spread_printer_offset_does_not_cut_at_fold(profile):
    """Сдвиг под принтер двигает всю сторону двойного листка. Раньше каждая
    страница сдвигалась отдельно, и у правой страницы начало строк обрезалось
    по линии сгиба."""
    import numpy as np

    def ink(o):
        r = sv.render_text(TEXT, profile, o, dpi=60, for_print=True)
        return r, 255.0 - np.asarray(r.images[0], np.float32)

    base = dict(page="notebook", spread=True, real_paper=True)
    r0, a0 = ink(sv.Options(**base))
    r1, a1 = ink(sv.Options(**base, offset_x_mm=-3.0))
    assert abs(a1.sum() - a0.sum()) < 0.002 * a0.sum()  # ничего не потеряно
    dx = round(3.0 * 60 / 25.4)
    w = a0.shape[1]
    assert np.allclose(a1[:, : w - dx], a0[:, dx:])  # вся сторона сдвинута целиком


def test_spread_flip_back_rotates_inner_side(profile):
    import numpy as np

    text = "\n".join([TEXT] * 6)
    base = dict(page="notebook", spread=True, real_paper=True, offset_y_mm=2.0)
    plain = sv.render_text(text, profile, sv.Options(**base), dpi=40, for_print=True)
    flipped = sv.render_text(text, profile, sv.Options(**base, flip_back=True), dpi=40, for_print=True)
    assert np.array_equal(np.asarray(plain.images[0]), np.asarray(flipped.images[0]))
    # Оборот повёрнут, а сдвиг принтера тот же (вниз), а не перевёрнутый.
    a, b = (255 - np.asarray(im.images[1].convert("L"), np.int32) for im in (plain, flipped))
    assert not np.array_equal(a, b)
    dy = round(2.0 * 40 / 25.4)
    assert b[:dy].sum() == 0 and a[:dy].sum() == 0


def test_preview_then_finish_import(filled_photos, tmp_path):
    root = sv.profile_dir_for(tmp_path, "Проверка")
    preview = sv.scan_import(root, "Проверка", filled_photos[:1])
    assert preview.samples and not (root / "profile.json").exists()
    keep = [i % 5 != 0 for i in range(len(preview.samples))]
    res = sv.finish_import(preview, keep)
    prof = Profile.load(root)
    assert res.added == len(preview.samples)
    assert sum(not s.enabled for s in prof.samples) >= keep.count(False)
    assert res.turned_off + len(res.crossed) == sum(not s.enabled for s in prof.samples)
    assert "Отключено при просмотре" in res.summary()


def test_demo_profile_renders_demo_text(tmp_path):
    root = sv.make_demo_profile(tmp_path)
    assert sv.list_profiles(tmp_path) == [(sv.DEMO_NAME, root)]
    assert sv.make_demo_profile(tmp_path) == root  # второй раз не пересоздаётся
    prof = Profile.load(root)
    assert len(prof.samples) > 300
    r = sv.render_text(sv.DEMO_TEXT, prof, sv.Options(), 60)
    assert r.images and not r.missing


def test_delete_profile_goes_to_trash_or_aside(tmp_path):
    root = tmp_path / "profiles"
    a = Profile.create(root / "Мой", "Мой").root
    b = Profile.create(root / "Второй", "Второй").root
    trashed = []

    def trash(p):
        import shutil
        trashed.append(p)
        shutil.rmtree(p)
        return True

    assert sv.delete_profile(root, a, trash=trash) is None
    assert trashed == [str(a.resolve())] and not a.exists()
    moved = sv.delete_profile(root, b, trash=lambda p: False)  # Корзины нет: переносим, не стираем
    assert moved == sv.removed_profiles_dir(root) / "Второй"
    assert (moved / "profile.json").exists() and not b.exists()
    assert sv.list_profiles(root) == []
    again = Profile.create(root / "Второй", "Второй").root
    moved2 = sv.delete_profile(root, again)
    assert moved2 != moved and moved.exists() and moved2.exists()


def test_delete_profile_refuses_foreign_folders(tmp_path):
    root = tmp_path / "profiles"
    Profile.create(root / "Мой", "Мой")
    other = tmp_path / "чужая"
    other.mkdir()
    (other / "profile.json").write_text("{}", encoding="utf-8")
    for bad in (other, root, root / "нет", root / "Мой" / ".."):
        with pytest.raises(ValueError):
            sv.delete_profile(root, bad)
    assert other.exists() and (root / "Мой" / "profile.json").exists()


def test_view_templates_roundtrip():
    t = {"Тетрадь": {"paper": "lines", "weight10": 3, "лишнее": 1}, " ": {"paper": "grid"}}
    loaded = sv.load_view_templates(sv.dump_view_templates(t))
    assert loaded == {"Тетрадь": {"paper": "lines", "weight10": 3}}
    for bad in ("", None, "не json", "[1, 2]"):
        assert sv.load_view_templates(bad) == {}


def test_printer_shift_left_up_to_30mm(profile):
    """Влево можно сдвинуть на 30 мм; справа освобождается белое, размер листа тот же."""
    import numpy as np

    opts = sv.Options(page="A4", real_paper=True)
    printed = sv.render_text(TEXT, profile, opts, dpi=60, for_print=True)
    moved = sv.render_text(TEXT, profile, sv.Options(page="A4", real_paper=True, offset_x_mm=-sv.MAX_SHIFT_LEFT_MM),
                           dpi=60, for_print=True)
    a0, a1 = np.asarray(printed.images[0]), np.asarray(moved.images[0])
    assert a0.shape == a1.shape
    dx = round(sv.MAX_SHIFT_LEFT_MM * 60 / 25.4)
    assert np.array_equal(a1[:, : a0.shape[1] - dx], a0[:, dx:])
    assert (a1[:, a0.shape[1] - dx:] == 255).all()
