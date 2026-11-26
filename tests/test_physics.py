import numpy as np
import pymupdf
from PIL import ImageDraw

from konspekt import layout, service
from konspekt.extract import find_page, import_files, load_images, warp_to_template
from konspekt.symbols import GROUPS
from konspekt.template import CUSTOM_PAGE, CUSTOM_SET, custom_cells, decode_custom, render_page, save_symbol_pdf
from konspekt.units import mm_to_px


def test_nested_fraction_and_script(profile):
    source = r"$\frac{\frac{v^2}{2}}{\sqrt{g}}$"
    page = layout.typeset("До\n" + source + "\nПосле", profile).pages[0]
    assert len(page.lines) == 3
    v, two, den, g = [glyph for glyph in page.glyphs if glyph.text in "v2g"]
    assert two.y < v.y < den.y < g.y
    assert all(line.points[0][1] > page.glyphs[0].y for line in page.lines)
    assert g.y < page.glyphs[-1].y


def test_zero_join_rate_disables_cluster_samples(profile):
    page = layout.typeset("на на на отражение", profile, layout.Settings(join_rate=0)).pages[0]
    assert not page.connectors
    assert all(len(g.text) == 1 for g in page.glyphs)


def test_custom_sheet_roundtrip(tmp_path):
    path = tmp_path / "symbols.pdf"
    chars = "".join(dict.fromkeys("".join(GROUPS.values())))
    save_symbol_pdf(path, chars)
    decoded = []
    for image in load_images(path):
        page, transform = find_page(image)
        assert page == CUSTOM_PAGE
        decoded.append(decode_custom(warp_to_template(image, transform)))
    assert "".join(decoded) == chars
    cells = custom_cells("Ω±")
    image = render_page(cells, CUSTOM_PAGE, 1, CUSTOM_SET)
    x, y = (round(mm_to_px(v, 300)) for v in (cells[1].x+4, cells[1].y+5))
    ImageDraw.Draw(image).line((x,y,x+35,y+55), fill="black", width=5)
    scan = tmp_path / "filled.png"
    image.save(scan)
    assert [s.cell.request.text for s in import_files([scan]).samples] == ["±"]


def test_calibrated_pdf(profile, tmp_path):
    path = tmp_path / "physics.pdf"
    opts = service.Options(page="notebook", spread=True, real_paper=True, a4_feed=True,
                           offset_x_mm=4, fold_adjust_mm=3)
    result = service.export_pdf(r"$E_k = \frac{m v^2}{2}$", profile, opts, path, dpi=100)
    assert result.size_mm == (297, 210)
    with pymupdf.open(path) as pdf:
        assert abs(pdf[0].rect.width*25.4/72-297) < .2
        pix = pymupdf.Pixmap(pdf, pdf[0].get_images()[0][0])
        rgb = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
        assert np.array_equal(np.unique(rgb), [0, 255])
        assert np.where(rgb[:,:,0] == 0)[1].min() > mm_to_px(177,100)


def test_handwritten_rules_vary_and_match_print(tmp_path):
    from konspekt.profile import Profile
    profile = Profile.create(tmp_path / 'empty', 'Проверка')
    from konspekt.formula import build

    def draw(seed, dpi):
        setter = layout.Typesetter(profile, layout.Settings(seed=seed, dpi=dpi))
        strokes = []
        for _ in range(12):
            box = build(r"$\sqrt{\frac{a}{b}}$", setter, "body", 120)
            bar, root = box.lines
            numerator, denominator = box.glyphs
            assert numerator.y + (numerator.sample.height - numerator.sample.baseline) * numerator.scale < min(y for _, y in bar.points)
            assert denominator.y - denominator.sample.baseline * denominator.scale > max(y for _, y in bar.points)
            # Убираем сдвиг всего знака и ширину, зависящую от образцов букв.
            def shape(points):
                x0, y0 = points[0]
                width = points[-1][0] - x0
                return tuple((round((x-x0)/width, 4), round(y-y0, 4)) for x,y in points)
            strokes.append((shape(bar.points), shape(root.points)))
        return strokes

    preview = draw(17, service.PREVIEW_DPI)
    assert preview == draw(17, service.PRINT_DPI)
    assert preview != draw(23, service.PREVIEW_DPI)
    bars = [bar for bar, _ in preview]
    assert len(set(bars)) >= 3
    assert all(a != b for a, b in zip(bars, bars[1:]))
    # Начальное движение крючка различается по высоте независимо от подкоренного выражения.
    hooks = [root[1][1] for _, root in preview]
    assert len(set(hooks)) >= 3
    assert all(a != b for a, b in zip(hooks, hooks[1:]))


def test_pendulum_equals_has_two_separate_strokes(profile):
    from konspekt.formula import build

    for seed in range(8):
        setter = layout.Typesetter(profile, layout.Settings(seed=seed, weight=2))
        box = build(r"$T = 2\pi\sqrt{\frac{l}{g}}$", setter, "body", 120)
        upper, lower, fraction, radical = box.lines
        assert max(x for x, _ in lower.points) < min(x for x, _ in radical.points)
        for (_, a), (_, b) in zip(upper.points, lower.points):
            assert b - a > upper.width_mm * setter.s.weight
