import numpy as np
from PIL import Image

from konspekt.extract import HD, extract_ink, import_files, upscale_legacy
from konspekt.template import layout_cells, save_template_pdf


def test_all_cells_found(import_report):
    pages = layout_cells()
    assert sorted(set(import_report.pages_found)) == list(range(len(pages)))
    assert import_report.empty_cells == 0
    expected = [c.request for cells in pages for c in cells]
    assert [s.cell.request for s in import_report.samples] == expected


def test_baseline_inside_sample(import_report):
    for s in import_report.samples:
        assert 0 < s.baseline <= s.alpha.shape[0] + 40


def test_empty_cell_is_none():
    assert extract_ink(np.full((200, 160, 3), 245, np.uint8)) is None


def test_guides_are_not_ink():
    cell = np.full((200, 160, 3), 250, np.uint8)
    cell[120:123, 10:150] = (255, 196, 160)  # оранжевая направляющая
    assert extract_ink(cell) is None


def test_photo_without_markers(tmp_path):
    p = tmp_path / "пусто.png"
    Image.new("RGB", (800, 1100), "white").save(p)
    rep = import_files([p])
    assert rep.files_without_markers and not rep.samples


def test_template_pdf(tmp_path):
    out = tmp_path / "бланк.pdf"
    assert save_template_pdf(out) == len(layout_cells())
    assert out.stat().st_size > 10_000


def test_blank_template_has_no_samples(tmp_path):
    out = tmp_path / "бланк.pdf"
    save_template_pdf(out)
    rep = import_files([out])
    assert not rep.files_without_markers
    assert rep.samples == []


def test_main_template_layout_is_stable():
    # Уже заполненные пользователем бланки должны читаться и после изменений.
    from konspekt.template import set_pages

    pages = set_pages("main")
    assert [len(p) for p in pages] == [90, 90, 87, 48, 28]
    assert pages[0][0].x == 18.0 and pages[0][0].page == 0


def test_extra_template_roundtrip(tmp_path):
    from PIL import Image

    from konspekt.synthetic import fill_template, photograph
    from konspekt.template import set_pages

    from conftest import FONT

    paths = []
    for i, page in enumerate(fill_template(FONT, seed=3, key="extra")):
        p = tmp_path / f"доп_{i}.jpg"
        # PIL, а не cv2.imwrite: OpenCV на Windows не пишет в пути с кириллицей
        Image.fromarray(photograph(page, seed=10 + i)).save(p, quality=95)
        paths.append(p)
    rep = import_files(paths)
    pages = set_pages("extra")
    assert sorted(rep.pages_found) == [c[0].page for c in pages]
    assert [s.cell.request for s in rep.samples] == [c.request for cells in pages for c in cells]


def test_guide_dashes_and_far_specks_are_dropped():
    import cv2
    import numpy as np
    from konspekt.extract import _keep_components
    m = np.zeros((200, 300), np.uint8)
    cv2.line(m, (60, 60), (120, 150), 1, 8)          # штрих буквы
    for x in range(10, 290, 20):                    # пунктир на базовой линии
        m[148:152, x:x + 10] = 1
    m[40:47, 100:107] = 1                            # точка над буквой рядом
    m[10:16, 280:286] = 1                            # соринка в углу
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    keep = _keep_components(stats, (150.0,))
    out = keep[labels]
    assert out[100, 90] and out[43, 103]
    assert not out[150, 15] and not out[12, 282]


def test_black_ink_on_bent_sheet():
    """Чёрные чернила серые, как печать бланка: подгонка клеток не должна
    принимать буквы за уголки и подписи."""
    import cv2

    import konspekt.synthetic as syn
    from konspekt.extract import _px, cell_offsets, find_page, warp_to_template
    from konspekt.template import all_pages, render_page

    from conftest import FONT

    old = syn.INK
    syn.INK = (25, 25, 28)
    try:
        page = syn.fill_template(FONT, seed=2)[0]
    finally:
        syn.INK = old
    h, w = page.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    amp = _px(4.0)
    bend = amp * np.sin(np.pi * xx / w) * np.sin(np.pi * yy / h)
    img = cv2.remap(page, xx - bend, yy - 0.6 * bend, cv2.INTER_LINEAR, borderValue=(255, 255, 255))
    img = syn.photograph(img, seed=3, strength=0.6)
    n, H = find_page(img)
    ts, cells, n_pages = all_pages()[n]
    offsets = cell_offsets(warp_to_template(img, H), cells, np.array(render_page(cells, n, n_pages, ts)))
    for c, (dx, dy) in zip(cells, offsets):
        cx, cy = _px(c.x + c.w / 2), _px(c.y + c.h / 2)
        k = amp * np.sin(np.pi * cx / w) * np.sin(np.pi * cy / h)
        assert np.hypot(dx - k, dy - 0.6 * k) < _px(0.8), c.request.text


def test_clipped_letter_detected():
    from konspekt.extract import touches_edge

    a = np.zeros((120, 100), np.float32)
    a[40:80, 45:50] = 1.0
    assert not touches_edge(a)
    a[80:, 45:50] = 1.0  # хвост «д» ушёл за нижний край клетки
    assert touches_edge(a)


def test_samples_not_clipped_in_clean_fill(import_report):
    # крупные заглавные шрифта иногда и правда задевают край клетки
    assert sum(s.clipped for s in import_report.samples) <= len(import_report.samples) // 25


def _cell_with_speck(scale: int = 1) -> np.ndarray:
    """Клетка со штрихом и пылинкой в 1,5 мм слева от него."""
    import cv2

    cell = np.full((200 * scale, 160 * scale, 3), 250, np.uint8)
    cv2.line(cell, (60 * scale, 140 * scale), (90 * scale, 60 * scale), (40, 50, 140), 4 * scale)
    cv2.line(cell, (90 * scale, 60 * scale), (120 * scale, 140 * scale), (40, 50, 140), 4 * scale)
    cv2.circle(cell, (40 * scale, 120 * scale), 3 * scale, (40, 50, 140), -1)
    return cell


def test_lone_speck_dropped_but_dot_kept():
    for scale in (1, HD):
        speck = (slice(115 * scale, 126 * scale), slice(35 * scale, 46 * scale))
        a = extract_ink(_cell_with_speck(scale), text="л", scale=scale)
        assert a[speck].max() == 0  # в «л» точки нет — это соринка
        a = extract_ink(_cell_with_speck(scale), text="ё", scale=scale)
        assert a[speck].max() > 0.5  # а в «ё» точка своя


def test_samples_have_hd_copy(import_report):
    for s in import_report.samples[:40]:
        assert s.alpha_hd.shape == (s.alpha.shape[0] * HD, s.alpha.shape[1] * HD)
        assert abs(float(s.alpha_hd.mean()) - float(s.alpha.mean())) < 0.03


def test_legacy_sample_upscaled_without_specks():
    a = extract_ink(_cell_with_speck(), text="ё")  # старый образец с точкой
    hd = upscale_legacy(a, "л")
    assert hd.shape == (a.shape[0] * HD, a.shape[1] * HD)
    assert hd[115 * HD:126 * HD, 35 * HD:46 * HD].max() == 0
    assert hd.max() > 0.9


def test_flood_drops_faint_smudge_and_fills_grain():
    import cv2

    cell = np.full((200, 160, 3), 250, np.uint8)
    cv2.line(cell, (40, 140), (120, 60), (40, 50, 140), 5)
    cell[98:101, 79:82] = 200  # светлое зерно внутри штриха
    cv2.circle(cell, (40, 60), 6, (215, 215, 225), -1)  # бледное пятно рядом
    a = extract_ink(cell, text="л")
    assert a[50:71, 30:51].max() == 0  # пятно залито бумагой
    assert a[99, 80] > 0.9  # зерно залито чернилами
    assert a[a > 0.5].min() > 0.5 and np.mean(a[a > 0.04] > 0.9) > 0.6  # линия сплошная


def test_belarusian_template_adds_to_profile(tmp_path, profile):
    """Белорусский бланк — отдельная страница со своими метками; его сканы
    добавляются к готовому профилю, ничего не стирая."""
    import shutil

    from PIL import Image

    from konspekt.charset import BE_ONLY
    from konspekt.layout import Settings, typeset
    from konspekt.profile import Profile
    from konspekt.synthetic import fill_template, photograph
    from konspekt.template import all_pages, set_pages

    from conftest import FONT

    pages = set_pages("be")
    assert len(pages) == 1 and pages[0][0].page == 10
    assert len(all_pages()) == 12  # номера страниц бланков не пересекаются
    p = tmp_path / "бел.jpg"
    Image.fromarray(photograph(fill_template(FONT, seed=4, key="be")[0], seed=21)).save(p, quality=95)
    rep = import_files([p])
    assert [s.cell.request for s in rep.samples] == [c.request for c in pages[0]]

    prof = Profile.load(shutil.copytree(profile.root, tmp_path / "Мой"))
    before = len(prof.samples)
    prof.add_extracted(rep.samples)
    prof.save()
    prof = Profile.load(prof.root)
    assert len(prof.samples) == before + len(rep.samples)
    assert all(prof.variants(c) for c in BE_ONLY)
    assert prof.coverage()["белорусские"]["нет"] == ""
    layout = typeset("Ўсе дзеці ішлі ў школу. Сям'я", prof, Settings(seed=1))
    assert not layout.missing


def test_english_template_roundtrip(tmp_path):
    """Английский бланк — на метках после 50-й: словарь меток расширен,
    а первые 50 совпадают со старым, так что старые бланки читаются."""
    import cv2
    import numpy as np
    from PIL import Image

    from konspekt.synthetic import fill_template, photograph
    from konspekt.template import ARUCO_DICT, set_pages

    from conftest import FONT

    old = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50).bytesList
    assert np.array_equal(cv2.aruco.getPredefinedDictionary(ARUCO_DICT).bytesList[:50], old)
    paths = []
    for i, page in enumerate(fill_template(FONT, seed=5, key="en")):
        p = tmp_path / f"англ_{i}.jpg"
        Image.fromarray(photograph(page, seed=30 + i)).save(p, quality=95)
        paths.append(p)
    rep = import_files(paths)
    pages = set_pages("en")
    assert sorted(rep.pages_found) == [c[0].page for c in pages] == [12, 13]
    assert [s.cell.request for s in rep.samples] == [c.request for cells in pages for c in cells]
