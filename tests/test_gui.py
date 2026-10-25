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


def test_light_theme_dialogs_readable(app, window):
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QMessageBox

    gui.apply_light_theme(app)
    box = QMessageBox(QMessageBox.Question, gui.APP_NAME, "Проверка", QMessageBox.Yes | QMessageBox.No, window)
    pal = box.palette()
    assert pal.color(QPalette.Window).lightness() > 200
    assert pal.color(QPalette.WindowText).lightness() < 80


def test_insert_helpers(app, window):
    window.text_edit.setPlainText("1. Первый\nтекст")
    c = window.text_edit.textCursor()
    c.movePosition(c.MoveOperation.End)
    window.text_edit.setTextCursor(c)
    window.insert_question()
    assert window.text_edit.toPlainText().endswith("2. \nтекст")
    window.text_edit.setPlainText("важное слово")
    c = window.text_edit.textCursor()
    c.select(c.SelectionType.WordUnderCursor)
    window.text_edit.setTextCursor(c)
    window.wrap_selection("_", "_")
    assert window.text_edit.toPlainText() == "_важное_ слово"
    window.tired_slider.setValue(5)
    window.fix_slider.setValue(4)
    o = window.options()
    assert o.tiredness == 0.5 and abs(o.corrections - 0.02) < 1e-9


def test_letter_editor_delete_and_size(app, window, tmp_path):
    import shutil

    from konspekt.profile import Profile

    root = tmp_path / "Тест"
    shutil.copytree(window.profile.root, root)
    prof = Profile.load(root)
    dlg = gui.SamplesDialog(window, prof, "о")
    n = len(dlg.buttons_for_current())
    victim = dlg.buttons_for_current()[0].property("sample_id")
    dlg.delete_sample(victim)
    assert len(dlg.buttons_for_current()) == n - 1
    dlg.scale_slider.setValue(120)
    dlg.raise_spin.setValue(-0.4)
    spin = next(w for w in dlg.grid_box.findChildren(gui.QSpinBox) if w.property("scale_for"))
    spin.setValue(90)
    dlg._render_preview()
    assert dlg.preview.pixmap() is not None and not dlg.preview.pixmap().isNull()
    assert dlg.changed() == 3
    # Отмена: профиль на диске и в памяти не меняется
    dlg.reject()
    assert victim in {s.id for s in prof.samples} and not prof.letter_adjust
    assert victim in {s.id for s in Profile.load(root).samples}

    dlg = gui.SamplesDialog(window, prof, "о")
    dlg.delete_sample(victim)
    dlg.scale_slider.setValue(120)
    dlg._save()
    again = Profile.load(root)
    assert victim not in {s.id for s in again.samples}
    assert not (root / next(s for s in window.profile.samples if s.id == victim).file).exists()
    assert again.letter_scale("о") == 1.2


def test_live_edge_slider(app, window):
    assert window.options().live_edge == 1.0  # по умолчанию край живой
    window.edge_slider.setValue(0)
    assert window.options().live_edge == 0.0
    window.flip_back.setChecked(True)
    assert window.options().flip_back


def test_new_text_and_blank_window(app, window, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    window.text_edit.setPlainText("старый текст")
    window.new_text()
    assert window.text_edit.toPlainText() == ""
    window.text_edit.undo()
    assert window.text_edit.toPlainText() == "старый текст"

    qs = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    qs.setValue("text", "конспект главного окна")
    second = gui.MainWindow(tmp_path / "profiles", qs, blank=True)
    assert second.text_edit.toPlainText() == ""
    second.text_edit.setPlainText("второй")
    second._save_settings()
    assert qs.value("text") == "конспект главного окна"  # второе окно не затирает текст первого
    second.close()

    calls = []
    monkeypatch.setattr(gui.QProcess, "startDetached", lambda prog, args: calls.append(args) or (True, 1))
    assert window.new_window() and calls[-1][-1] == "--new"


def test_update_check(app, window, monkeypatch):
    rel = gui.updates.Release("0.2.99", "Что нового", "https://example/rel", "", 0)
    monkeypatch.setattr(gui.updates, "fetch_latest", lambda: rel)
    monkeypatch.setattr(gui.updates, "current_version", lambda: "0.2.20")
    shown = []
    monkeypatch.setattr(gui.QMessageBox, "exec", lambda box: shown.append(box.text()) or 0)
    window.check_updates()
    wait_idle(app, window)
    assert shown and "0.2.99" in shown[0] and "0.2.20" in shown[0]

    window.qs.setValue("skip_version", "0.2.99")  # пропущенную версию при запуске не предлагаем
    window.check_updates()
    wait_idle(app, window)
    assert len(shown) == 1


def test_update_check_offline_is_silent(app, window, monkeypatch):
    def offline():
        raise OSError("нет сети")
    monkeypatch.setattr(gui.updates, "fetch_latest", offline)
    monkeypatch.setattr(gui.updates, "current_version", lambda: "0.2.20")
    infos = []
    monkeypatch.setattr(gui.QMessageBox, "information", lambda *a: infos.append(a[2]))
    window.check_updates(silent=True)
    wait_idle(app, window)
    assert infos == []
    window.check_updates(silent=False)
    wait_idle(app, window)
    assert infos and "нет связи" in infos[0]
