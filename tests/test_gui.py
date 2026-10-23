"""Окно запускается без экрана (offscreen) и делает основные действия."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from konspekt import gui  # noqa: E402
from konspekt import service as sv  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def window(app, profile, tmp_path):
    qs = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.IniFormat)
    w = gui.MainWindow(profile.root.parent, qs)
    yield w
    wait_idle(app, w)
    w.close()


def wait_idle(app, w, timeout_s=60):
    timer = QtCore.QElapsedTimer()
    timer.start()
    while w.busy() or w.timer.isActive():
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        assert timer.elapsed() < timeout_s * 1000, "фоновая задача не закончилась"


def test_defaults(window):
    assert window.profile_box.currentText() == "Тест"
    assert window.profile is not None
    assert window.paper_box.currentData() == "grid"
    assert window.seed_spin.value() == sv.DEFAULT_SEED
    assert window.options().size_mm is None
    assert window.page_box.currentData() == "notebook"
    assert window.margin_box.currentData() == "outer"
    assert not window.off_x.isVisibleTo(window)


def test_format_switch_sets_margin_and_pitch(window):
    window.page_box.setCurrentIndex(window.page_box.findData("A4"))
    assert window.margin_box.currentData() == "left"
    window.page_box.setCurrentIndex(window.page_box.findData("notebook"))
    window.paper_box.setCurrentIndex(window.paper_box.findData("lines"))
    assert window.pitch_spin.value() == sv.NOTEBOOK_LINE_PITCH_MM
    window.paper_box.setCurrentIndex(window.paper_box.findData("grid"))
    assert window.pitch_spin.value() == 10.0
    window.real_paper.setChecked(True)
    assert window.off_x.isVisibleTo(window)
    assert window.options().real_paper


def test_preview_and_regenerate(app, window):
    window.text_edit.setPlainText("# Заголовок\nОщущение — это отражение свойств предметов. Ъ")
    window.refresh_preview()
    wait_idle(app, window)
    assert window.pages.page_count() == 1
    window.next_variant()
    assert window.seed_spin.value() == sv.DEFAULT_SEED + 1
    wait_idle(app, window)
    assert window.pages.page_count() == 1


def test_settings_are_remembered(app, profile, tmp_path):
    qs = QtCore.QSettings(str(tmp_path / "s.ini"), QtCore.QSettings.IniFormat)
    w = gui.MainWindow(profile.root.parent, qs)
    w.text_edit.setPlainText("привет")
    w.paper_box.setCurrentIndex(w.paper_box.findData("lines"))
    w.seed_spin.setValue(11)
    wait_idle(app, w)
    w.close()
    w2 = gui.MainWindow(profile.root.parent, qs)
    assert w2.text_edit.toPlainText() == "привет"
    assert w2.paper_box.currentData() == "lines"
    assert w2.seed_spin.value() == 11
    wait_idle(app, w2)
    w2.close()


def test_no_profiles_shows_hint(app, tmp_path):
    qs = QtCore.QSettings(str(tmp_path / "s.ini"), QtCore.QSettings.IniFormat)
    w = gui.MainWindow(tmp_path / "пусто", qs)
    assert w.profile is None
    assert w.pages.page_count() == 0
    assert "Импорт" in w.pages._hint.text()
    w.close()


def test_broken_profile_reason_is_shown(app, tmp_path):
    bad = tmp_path / "profiles" / "Мой_почерк"
    bad.mkdir(parents=True)
    (bad / "profile.json").write_text('{"format": 99}', encoding="utf-8")
    qs = QtCore.QSettings(str(tmp_path / "s.ini"), QtCore.QSettings.IniFormat)
    w = gui.MainWindow(tmp_path / "profiles", qs)
    assert w.profile is None
    hint = w.pages._hint.text()
    assert "не открылся" in hint and "Мой_почерк" in hint and "99" in hint
    w.close()


def test_print_is_real_size(app, window, profile, tmp_path):
    from PySide6.QtGui import QPageLayout, QPageSize
    from PySide6.QtPrintSupport import QPrinter

    import pymupdf

    out = tmp_path / "печать.pdf"
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(out))
    printer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, printer.pageLayout().margins()))
    printer.setFullPage(True)
    pages = sv.render_text("Ощущение — это отражение свойств.", profile, sv.Options(page="A4"), dpi=72)
    window._paint_to_printer(printer, pages)
    with pymupdf.open(out) as d:
        assert d.page_count == 1
        assert abs(d[0].rect.width / 72 * 25.4 - 210) < 1.5

    out2 = tmp_path / "листок.pdf"
    printer.setOutputFileName(str(out2))
    printer.setPageLayout(QPageLayout(gui.page_size("notebook"), QPageLayout.Portrait,
                                      printer.pageLayout().margins()))
    pages = sv.render_text("Ощущение.", profile, sv.Options(page="notebook", real_paper=True), 72, True)
    window._paint_to_printer(printer, pages)
    with pymupdf.open(out2) as d:
        assert abs(d[0].rect.width / 72 * 25.4 - 170) < 1.5
        assert abs(d[0].rect.height / 72 * 25.4 - 205) < 1.5


def test_samples_dialog_disables_and_saves(app, window):
    from konspekt.profile import Profile

    dlg = gui.SamplesDialog(window, window.profile, "а")
    buttons = dlg.buttons_for_current()
    assert len(buttons) == len(window.profile.variants("а")) >= 2
    sid = buttons[0].property("sample_id")
    buttons[0].click()
    assert dlg.changed() == 1
    dlg.reject()  # отмена ничего не сохраняет
    assert all(s.enabled for s in Profile.load(window.profile.root).samples if s.id == sid)


def test_crossed_offer_and_samples_save(app, profile, tmp_path, monkeypatch):
    from test_service import crossed_copy

    from konspekt.profile import Profile

    prof, sid = crossed_copy(profile, tmp_path)
    monkeypatch.setattr(gui.QMessageBox, "question", lambda *a, **k: gui.QMessageBox.Yes)
    qs = QtCore.QSettings(str(tmp_path / "s.ini"), QtCore.QSettings.IniFormat)
    w = gui.MainWindow(tmp_path, qs)
    assert not next(s for s in w.profile.samples if s.id == sid).enabled
    assert not next(s for s in Profile.load(prof.root).samples if s.id == sid).enabled

    dlg = gui.SamplesDialog(w, w.profile, "п")
    b = next(b for b in dlg.buttons_for_current() if b.property("sample_id") == sid)
    assert not b.isChecked()
    b.click()  # вернуть образец
    dlg._save()
    assert next(s for s in Profile.load(prof.root).samples if s.id == sid).enabled
    wait_idle(app, w)
    w.close()


def test_print_double_sheet(app, window, profile, tmp_path):
    from PySide6.QtGui import QPageLayout
    from PySide6.QtPrintSupport import QPrinter

    import pymupdf

    out = tmp_path / "двойной.pdf"
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(out))
    printer.setPageLayout(QPageLayout(gui.page_size("notebook", True), QPageLayout.Landscape,
                                      printer.pageLayout().margins()))
    printer.setFullPage(True)
    r = sv.render_text("Ощущение.", profile, sv.Options(page="notebook", spread=True, real_paper=True), 72, True)
    window._paint_to_printer(printer, r, ask_flip=False)
    with pymupdf.open(out) as d:  # второй проход (оборот) перезаписал файл: одна сторона
        w, h = d[0].rect.width / 72 * 25.4, d[0].rect.height / 72 * 25.4
    assert abs(w - 340) < 1.5 and abs(h - 205) < 1.5


def test_spread_option_only_for_notebook(app, window):
    window.page_box.setCurrentIndex(window.page_box.findData("A4"))
    assert window.spread_box.isHidden()
    window.page_box.setCurrentIndex(window.page_box.findData("notebook"))
    assert not window.spread_box.isHidden()
    window.spread_box.setChecked(True)
    assert window.options().use_spread
    assert not window.flip_back.isHidden()
    assert not window.nested_box.isHidden() and window.options().nested


def test_draw_dialog_save_and_delete(app, window, tmp_path):
    import shutil

    from konspekt.profile import Profile

    root = tmp_path / "Тест"
    shutil.copytree(window.profile.root, root)
    prof = Profile.load(root)
    dlg = gui.DrawDialog(window, prof, "ж")
    n = len(dlg.strip_buttons())
    dlg.canvas.strokes = [[(10, 12), (14, 16)], [(14, 12), (10, 16)]]
    dlg.save_variant()
    assert dlg.canvas.strokes == []
    buttons = dlg.strip_buttons()
    assert len(buttons) == n + 1
    drawn = buttons[-1]
    assert "удаляет" in drawn.toolTip()
    drawn.click()
    app.processEvents()
    assert len(dlg.strip_buttons()) == n
    assert len(Profile.load(root).variants("ж")) == n
    dlg.close()
