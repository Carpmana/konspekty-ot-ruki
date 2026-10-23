import numpy as np
from PIL import Image

from konspekt.extract import extract_ink, import_files
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
