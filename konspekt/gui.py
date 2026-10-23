"""Окно приложения: настройки слева, текст посередине, страницы справа.

    python -m konspekt.gui

Тяжёлая работа (импорт сканов, генерация страниц) идёт в фоновом потоке,
чтобы окно не зависало. Сами действия — в service.py.
"""

import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSettings, QSizeF, Qt, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import (
    QAction, QColor, QDesktopServices, QFont, QImage, QKeySequence, QPageLayout, QPageSize, QPainter, QPixmap,
)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QSplitter, QVBoxLayout,
    QWidget,
)

from . import service as sv
from .profile import Profile
from .template import TEMPLATE_SETS, save_template_pdf

APP_NAME = "Конспекты от руки"
PREVIEW_DELAY_MS = 700

ACCENT = "#3156c8"
ASSETS = (Path(__file__).parent / "assets").as_posix()

STYLE = f"""
QMainWindow, QWidget#body {{ background: #f4f5f8; }}
QWidget {{ font-size: 10pt; color: #1f2430; }}
QFrame#header {{ background: #ffffff; border-bottom: 1px solid #e3e6ee; }}
QLabel#title {{ font-size: 15pt; font-weight: 600; }}
QLabel#subtitle {{ color: #6b7385; }}
QScrollArea#sidebar, QWidget#sidebarBox {{ background: #ffffff; border: none; }}
QFrame#sidebarFrame {{ background: #ffffff; border-right: 1px solid #e3e6ee; }}
QLabel#section {{ color: #6b7385; font-size: 8.5pt; font-weight: 600; letter-spacing: 1px;
                  padding-top: 14px; }}
QLabel#hint {{ color: #6b7385; font-size: 9pt; }}
QFrame#card {{ background: #ffffff; border: 1px solid #e3e6ee; border-radius: 10px; }}
QLabel#cardTitle {{ font-weight: 600; }}
QPlainTextEdit {{ border: none; background: #ffffff; font-size: 11.5pt; selection-background-color: #c9d6ff; }}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: #ffffff; border: 1px solid #d5d9e3; border-radius: 6px; padding: 4px 8px; min-height: 22px; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({ASSETS}/arrow-down.svg); width: 10px; height: 6px; }}
QComboBox QAbstractItemView {{ border: 1px solid #d5d9e3; selection-background-color: #e6ecfb;
                               selection-color: #1f2430; outline: none; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 24px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
    border: none; width: 22px; subcontrol-origin: border; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({ASSETS}/arrow-up.svg); width: 10px; height: 6px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({ASSETS}/arrow-down.svg); width: 10px; height: 6px; }}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QPushButton {{ background: #ffffff; border: 1px solid #d5d9e3; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ background: #eef1f8; }}
QPushButton:pressed {{ background: #e2e7f3; }}
QPushButton#primary {{ background: {ACCENT}; color: #ffffff; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton#primary:hover {{ background: #2848ad; }}
QPushButton:disabled {{ color: #9aa1b2; }}
QSlider::groove:horizontal {{ height: 4px; background: #dfe3ec; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #ffffff; border: 2px solid {ACCENT}; width: 14px; height: 14px;
                              margin: -6px 0; border-radius: 8px; }}
QRadioButton, QCheckBox {{ spacing: 8px; }}
QLabel#missing {{ background: #fff4c2; color: #5a4a00; padding: 8px 10px; border-radius: 8px; }}
QStatusBar {{ background: #ffffff; border-top: 1px solid #e3e6ee; color: #6b7385; }}
QSplitter::handle {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #c9ceda; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""

PLACEHOLDER = """Вставьте сюда текст конспекта.

# Заголовок — строка с решёткой в начале
- пункт списка — строка с дефисом
Пустая строка — отступ. Каждая строка — отдельный абзац."""


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def page_size(key: str) -> QPageSize:
    if key == "A4":
        return QPageSize(QPageSize.A4)
    if key == "A5":
        return QPageSize(QPageSize.A5)
    w, h = sv.FORMAT_BY_KEY[key].size_mm
    return QPageSize(QSizeF(w, h), QPageSize.Millimeter, "Тетрадный листок", QPageSize.ExactMatch)


def to_qimage(im) -> QImage:
    im = im.convert("RGB")
    data = im.tobytes("raw", "RGB")
    return QImage(data, im.width, im.height, im.width * 3, QImage.Format_RGB888).copy()


class _Signals(QObject):
    finished = Signal(object, object, str)  # задача, результат, текст ошибки


class Task(QRunnable):
    """Функция в фоновом потоке. Итог приходит в окно сигналом, а on_done /
    on_fail вызываются уже в главном потоке (см. MainWindow._task_finished)."""

    def __init__(self, fn, *args, on_done=None, on_fail=None):
        super().__init__()
        self.setAutoDelete(False)
        self.fn, self.args = fn, args
        self.on_done, self.on_fail = on_done, on_fail
        self.signals = _Signals()

    def run(self):
        try:
            res = self.fn(*self.args)
        except Exception as e:  # показываем пользователю, а не роняем программу
            traceback.print_exc()
            self.signals.finished.emit(self, None, str(e) or e.__class__.__name__)
            return
        self.signals.finished.emit(self, res, "")


class PagesView(QScrollArea):
    """Страницы друг под другом, по ширине окна."""

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("QScrollArea { background: #e9ebf0; border-radius: 10px; }")
        self._box = QWidget()
        self._box.setStyleSheet("background: #e9ebf0;")
        self._lay = QVBoxLayout(self._box)
        self._lay.setContentsMargins(22, 22, 22, 22)
        self._lay.setSpacing(22)
        self.setWidget(self._box)
        self._images: list[QImage] = []
        self._labels: list[QLabel] = []
        self._hint = QLabel()
        self._hint.setAlignment(Qt.AlignCenter)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: #6b7385; font-size: 12pt; padding: 40px;")
        self._lay.addWidget(self._hint)
        self._lay.addStretch(1)

    def show_hint(self, text: str) -> None:
        self.set_pages([])
        self._hint.setText(text)
        self._hint.show()

    def set_pages(self, images: list[QImage]) -> None:
        for lab in self._labels:
            lab.deleteLater()
        self._labels = []
        self._images = images
        self._hint.setVisible(not images)
        for k, _ in enumerate(images):
            lab = QLabel()
            lab.setAlignment(Qt.AlignHCenter)
            lab.setStyleSheet("background: transparent;")
            shadow = QGraphicsDropShadowEffect(lab)
            shadow.setBlurRadius(18)
            shadow.setOffset(0, 3)
            shadow.setColor(QColor(30, 40, 70, 60))
            lab.setGraphicsEffect(shadow)
            self._lay.insertWidget(k + 1, lab)
            self._labels.append(lab)
        self._rescale()

    def page_count(self) -> int:
        return len(self._images)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale()

    def _rescale(self) -> None:
        w = max(200, min(self.viewport().width() - 44, 900))
        for im, lab in zip(self._images, self._labels):
            pm = QPixmap.fromImage(im).scaledToWidth(w, Qt.SmoothTransformation)
            lab.setPixmap(pm)


class ImportDialog(QDialog):
    """Выбор профиля (новый или существующий) и сканов бланка."""

    def __init__(self, parent, profiles: list[tuple[str, Path]], current: str | None):
        super().__init__(parent)
        self.setWindowTitle("Импорт сканов бланка")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel("Сканы или фото заполненного бланка образцов (PDF, JPG, PNG). "
                             "Лист должен быть виден целиком, со всеми четырьмя чёрными квадратами."))
        self.files = QListWidget()
        lay.addWidget(self.files)
        row = QHBoxLayout()
        add = QPushButton("Добавить файлы…")
        add.clicked.connect(self._add_files)
        clear = QPushButton("Очистить")
        clear.clicked.connect(self.files.clear)
        row.addWidget(add)
        row.addWidget(clear)
        row.addStretch(1)
        lay.addLayout(row)

        form = QFormLayout()
        self.existing = QRadioButton("Дополнить профиль")
        self.profile_box = QComboBox()
        for name, path in profiles:
            self.profile_box.addItem(name, str(path))
        if current:
            self.profile_box.setCurrentText(current)
        self.new = QRadioButton("Новый профиль")
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("например, Мой почерк")
        form.addRow(self.existing, self.profile_box)
        form.addRow(self.new, self.new_name)
        lay.addLayout(form)
        if profiles:
            self.existing.setChecked(True)
        else:
            self.existing.setEnabled(False)
            self.profile_box.setEnabled(False)
            self.new.setChecked(True)
        self.new_name.textEdited.connect(lambda _: self.new.setChecked(True))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Импортировать")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Сканы бланка", "",
                                                "Сканы и фото (*.pdf *.jpg *.jpeg *.png *.bmp *.tif *.tiff);;Все файлы (*)")
        for p in paths:
            self.files.addItem(p)

    def selected_files(self) -> list[str]:
        return [self.files.item(i).text() for i in range(self.files.count())]

    def target(self) -> tuple[str | None, str]:
        """(папка существующего профиля или None, имя)."""
        if self.existing.isChecked():
            return self.profile_box.currentData(), self.profile_box.currentText()
        return None, self.new_name.text().strip()

    def _accept(self):
        if not self.selected_files():
            QMessageBox.warning(self, APP_NAME, "Добавьте хотя бы один скан.")
            return
        if self.new.isChecked() and not self.new_name.text().strip():
            QMessageBox.warning(self, APP_NAME, "Введите имя нового профиля.")
            return
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, profiles_dir: str | Path | None = None, settings: QSettings | None = None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 820)
        self.qs = settings or QSettings("Konspekt", "Konspekt")
        self.profiles_dir = Path(profiles_dir or self.qs.value("profiles_dir", "") or sv.default_profiles_dir())
        self.pool = QThreadPool.globalInstance()
        self.profile: Profile | None = None
        self._generation = 0  # устаревшие результаты предпросмотра отбрасываются
        self._busy_tasks: set[Task] = set()
        self.last_missing: set[str] = set()

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(PREVIEW_DELAY_MS)
        self.timer.timeout.connect(self.refresh_preview)

        self._build_ui()
        self._build_menu()
        self._restore()
        self.reload_profiles(self.qs.value("profile", ""))

    # ---------- построение окна ----------

    def _build_ui(self):
        self.setStyleSheet(STYLE)

        # шапка: название и главные действия
        header = QFrame(objectName="header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 12, 20, 12)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(QLabel(APP_NAME, objectName="title"))
        titles.addWidget(QLabel("Текст вашим почерком, готовый к печати", objectName="subtitle"))
        hl.addLayout(titles)
        hl.addStretch(1)
        self.regen_btn = QPushButton("↻  Другой вариант")
        self.regen_btn.setToolTip("Тот же текст, но написанный по-другому (Ctrl+R)")
        self.regen_btn.clicked.connect(self.next_variant)
        self.pdf_btn = QPushButton("Сохранить PDF")
        self.pdf_btn.clicked.connect(self.save_pdf)
        self.print_btn = QPushButton("Печать", objectName="primary")
        self.print_btn.clicked.connect(self.print_pages)
        for b in (self.regen_btn, self.pdf_btn, self.print_btn):
            b.setMinimumHeight(34)
            hl.addWidget(b)

        # боковая панель настроек
        side = QWidget(objectName="sidebarBox")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(18, 4, 18, 18)
        sl.setSpacing(6)

        def section(title):
            sl.addWidget(QLabel(title.upper(), objectName="section"))

        def field(label, w):
            box = QVBoxLayout()
            box.setSpacing(3)
            box.addWidget(QLabel(label))
            box.addWidget(w)
            sl.addLayout(box)

        def hint(text):
            lab = QLabel(text, objectName="hint")
            lab.setWordWrap(True)
            sl.addWidget(lab)
            return lab

        section("Почерк")
        self.profile_box = QComboBox()
        self.profile_box.currentIndexChanged.connect(self._profile_changed)
        sl.addWidget(self.profile_box)
        row = QHBoxLayout()
        imp = QPushButton("Импорт сканов…")
        imp.clicked.connect(self.import_scans)
        blank = QPushButton("Бланк…")
        blank.setToolTip("Сохранить бланк образцов для заполнения ручкой")
        blank.clicked.connect(lambda: self.save_template("main"))
        row.addWidget(imp, 1)
        row.addWidget(blank)
        sl.addLayout(row)

        section("Бумага")
        self.page_box = QComboBox()
        for f in sv.FORMATS:
            self.page_box.addItem(f.title, f.key)
        field("Формат", self.page_box)
        self.paper_box = QComboBox()
        for key, title in sv.PAPERS:
            self.paper_box.addItem(title, key)
        field("Линовка", self.paper_box)
        self.margin_box = QComboBox()
        for key, title in sv.MARGINS:
            self.margin_box.addItem(title, key)
        field("Красное поле", self.margin_box)

        section("Письмо")
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(1, 9999)
        self.seed_spin.setPrefix("Вариант ")
        self.seed_spin.setToolTip("Другое число — другое оформление того же текста")
        sl.addWidget(self.seed_spin)
        self.neat_slider = QSlider(Qt.Horizontal)
        self.neat_slider.setRange(5, 15)  # десятые: 0.5 … 1.5
        self.neat_slider.setToolTip("Насколько небрежно пишется текст")
        sl.addWidget(QLabel("Аккуратность"))
        sl.addWidget(self.neat_slider)
        ends = QHBoxLayout()
        ends.addWidget(QLabel("аккуратно", objectName="hint"))
        ends.addStretch(1)
        ends.addWidget(QLabel("небрежно", objectName="hint"))
        sl.addLayout(ends)
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(0.0, 8.0)
        self.size_spin.setSingleStep(0.25)
        self.size_spin.setSuffix(" мм")
        self.size_spin.setSpecialValueText("как в образцах")
        field("Высота строчных букв", self.size_spin)
        self.pitch_spin = QDoubleSpinBox()
        self.pitch_spin.setRange(5.0, 20.0)
        self.pitch_spin.setSingleStep(0.5)
        self.pitch_spin.setSuffix(" мм")
        self.pitch_spin.setToolTip("10 мм — через клетку, 8 мм — тетрадь в линейку")
        field("Расстояние между строками", self.pitch_spin)
        self.show_missing = QCheckBox("Подсветить буквы без образцов")
        sl.addWidget(self.show_missing)

        section("Печать")
        self.on_clean = QRadioButton("На чистый лист\n(клетка печатается)")
        self.real_paper = QRadioButton("На настоящий тетрадный листок\n(печатается только текст)")
        self.on_clean.setChecked(True)
        sl.addWidget(self.on_clean)
        sl.addWidget(self.real_paper)
        offs = QHBoxLayout()
        self.off_x = QDoubleSpinBox()
        self.off_y = QDoubleSpinBox()
        for sp, pre in ((self.off_x, "→ "), (self.off_y, "↓ ")):
            sp.setRange(-15.0, 15.0)
            sp.setSingleStep(0.5)
            sp.setPrefix(pre)
            sp.setSuffix(" мм")
            sp.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            offs.addWidget(sp)
        self.offset_label = QLabel("Сдвиг под принтер")
        sl.addWidget(self.offset_label)
        sl.addLayout(offs)
        self.real_hint = hint("Вставьте листок в лоток как бумагу размера «Тетрадный листок». "
                              "Если строки легли не по клеткам, сдвиньте текст и напечатайте снова.")
        sl.addStretch(1)

        side_scroll = QScrollArea(objectName="sidebar")
        side_scroll.setWidget(side)
        side_scroll.setWidgetResizable(True)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side_frame = QFrame(objectName="sidebarFrame")
        sfl = QVBoxLayout(side_frame)
        sfl.setContentsMargins(0, 0, 0, 0)
        sfl.addWidget(side_scroll)
        side_frame.setFixedWidth(310)

        # текст
        text_card = QFrame(objectName="card")
        tl = QVBoxLayout(text_card)
        tl.setContentsMargins(14, 12, 14, 10)
        top = QHBoxLayout()
        top.addWidget(QLabel("Текст конспекта", objectName="cardTitle"))
        top.addStretch(1)
        open_btn = QPushButton("Открыть файл…")
        open_btn.clicked.connect(self.open_text)
        top.addWidget(open_btn)
        tl.addLayout(top)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(PLACEHOLDER)
        tl.addWidget(self.text_edit, 1)
        self.chars_label = QLabel(objectName="hint")
        tl.addWidget(self.chars_label)

        # страницы
        preview = QWidget()
        pl = QVBoxLayout(preview)
        pl.setContentsMargins(0, 0, 0, 0)
        ptop = QHBoxLayout()
        ptop.addWidget(QLabel("Как будет выглядеть", objectName="cardTitle"))
        ptop.addStretch(1)
        self.pages_label = QLabel(objectName="hint")
        ptop.addWidget(self.pages_label)
        pl.addLayout(ptop)
        self.pages = PagesView()
        pl.addWidget(self.pages, 1)
        self.missing_label = QLabel(objectName="missing")
        self.missing_label.setWordWrap(True)
        self.missing_label.hide()
        pl.addWidget(self.missing_label)

        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(14)
        split.addWidget(text_card)
        split.addWidget(preview)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        split.setSizes([420, 640])

        work = QWidget()
        wl = QVBoxLayout(work)
        wl.setContentsMargins(14, 14, 14, 10)
        wl.addWidget(split)

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        middle.addWidget(side_frame)
        middle.addWidget(work, 1)

        body = QWidget(objectName="body")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        bl.addWidget(header)
        bl.addLayout(middle, 1)
        self.setCentralWidget(body)

        for sig in (self.paper_box.currentIndexChanged, self.page_box.currentIndexChanged,
                    self.margin_box.currentIndexChanged, self.seed_spin.valueChanged,
                    self.neat_slider.valueChanged, self.size_spin.valueChanged, self.pitch_spin.valueChanged,
                    self.show_missing.toggled, self.text_edit.textChanged):
            sig.connect(self.schedule_preview)
        self.text_edit.textChanged.connect(self._update_counter)
        self.page_box.currentIndexChanged.connect(self._format_changed)
        self.paper_box.currentIndexChanged.connect(self._lining_changed)
        self.real_paper.toggled.connect(self._update_print_mode)
        self._update_print_mode()

    def _format_changed(self, *_):
        """У тетради поле снаружи, у листа — слева: ставим принятое для формата."""
        fmt = sv.FORMAT_BY_KEY[self.page_box.currentData()]
        self.margin_box.setCurrentIndex(self.margin_box.findData(fmt.margins))
        self._lining_changed()

    def _lining_changed(self, *_):
        if self.paper_box.currentData() == "lines" and self.page_box.currentData() == "notebook":
            self.pitch_spin.setValue(sv.NOTEBOOK_LINE_PITCH_MM)
        elif self.pitch_spin.value() == sv.NOTEBOOK_LINE_PITCH_MM:
            self.pitch_spin.setValue(10.0)

    def _update_print_mode(self, *_):
        on = self.real_paper.isChecked()
        for w in (self.offset_label, self.off_x, self.off_y, self.real_hint):
            w.setVisible(on)

    def _build_menu(self):
        def act(menu, title, slot, shortcut=None):
            a = QAction(title, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            menu.addAction(a)
            return a

        m = self.menuBar().addMenu("Файл")
        act(m, "Открыть текст…", self.open_text, QKeySequence.Open)
        act(m, "Сохранить PDF…", self.save_pdf, QKeySequence.Save)
        act(m, "Печать…", self.print_pages, QKeySequence.Print)
        m.addSeparator()
        act(m, "Выход", self.close, QKeySequence.Quit)

        m = self.menuBar().addMenu("Почерк")
        act(m, "Импорт сканов бланка…", self.import_scans, "Ctrl+I")
        act(m, "Сохранить основной бланк (PDF)…", lambda: self.save_template("main"))
        act(m, "Сохранить дополнительный бланк (PDF)…", lambda: self.save_template("extra"))
        act(m, "Что есть в профиле", self.show_coverage)
        m.addSeparator()
        act(m, "Открыть папку профилей", self.open_profiles_dir)
        act(m, "Выбрать папку профилей…", self.choose_profiles_dir)

        m = self.menuBar().addMenu("Вид")
        act(m, "Перегенерировать (следующий вариант)", self.next_variant, "Ctrl+R")
        act(m, "Обновить предпросмотр", self.refresh_preview, "F5")

    # ---------- настройки ----------

    def _restore(self):
        q = self.qs
        self.text_edit.setPlainText(q.value("text", ""))
        self.page_box.setCurrentIndex(max(0, self.page_box.findData(q.value("page", "notebook"))))
        self.paper_box.setCurrentIndex(max(0, self.paper_box.findData(q.value("paper", "grid"))))
        margins = q.value("margins", "")
        if margins:
            self.margin_box.setCurrentIndex(max(0, self.margin_box.findData(margins)))
        else:
            self._format_changed()
        self.seed_spin.setValue(int(q.value("seed", sv.DEFAULT_SEED)))
        self.neat_slider.setValue(int(q.value("neatness10", 10)))
        self.size_spin.setValue(float(q.value("size_mm", 0.0)))
        self.pitch_spin.setValue(float(q.value("pitch_mm", 10.0)))
        self.real_paper.setChecked(q.value("real_paper", "false") in (True, "true"))
        self.off_x.setValue(float(q.value("offset_x_mm", 0.0)))
        self.off_y.setValue(float(q.value("offset_y_mm", 0.0)))
        self._update_counter()

    def _save_settings(self):
        q = self.qs
        q.setValue("text", self.text_edit.toPlainText())
        q.setValue("paper", self.paper_box.currentData())
        q.setValue("page", self.page_box.currentData())
        q.setValue("margins", self.margin_box.currentData())
        q.setValue("real_paper", self.real_paper.isChecked())
        q.setValue("offset_x_mm", self.off_x.value())
        q.setValue("offset_y_mm", self.off_y.value())
        q.setValue("seed", self.seed_spin.value())
        q.setValue("neatness10", self.neat_slider.value())
        q.setValue("size_mm", self.size_spin.value())
        q.setValue("pitch_mm", self.pitch_spin.value())
        q.setValue("profile", self.profile_box.currentText())
        q.setValue("profiles_dir", str(self.profiles_dir))

    def closeEvent(self, e):
        self._save_settings()
        super().closeEvent(e)

    def options(self) -> sv.Options:
        size = self.size_spin.value()
        return sv.Options(paper=self.paper_box.currentData(), page=self.page_box.currentData(),
                          seed=self.seed_spin.value(), neatness=self.neat_slider.value() / 10,
                          size_mm=size if size > 0 else None, pitch_mm=self.pitch_spin.value(),
                          show_missing=self.show_missing.isChecked(), margins=self.margin_box.currentData(),
                          real_paper=self.real_paper.isChecked(), offset_x_mm=self.off_x.value(),
                          offset_y_mm=self.off_y.value())

    # ---------- профили ----------

    def reload_profiles(self, select: str | None = None):
        profiles = sv.list_profiles(self.profiles_dir)
        self.profile_box.blockSignals(True)
        self.profile_box.clear()
        for name, path in profiles:
            self.profile_box.addItem(name, str(path))
        if select:
            i = self.profile_box.findText(select)
            if i >= 0:
                self.profile_box.setCurrentIndex(i)
        self.profile_box.blockSignals(False)
        self._profile_changed()

    def _profile_changed(self, *_):
        path = self.profile_box.currentData()
        self.profile = None
        if path:
            try:
                self.profile = Profile.load(path)
            except (ValueError, KeyError, OSError) as e:
                QMessageBox.warning(self, APP_NAME, f"Не удалось открыть профиль:\n{e}")
        self.refresh_preview()

    def import_scans(self):
        dlg = ImportDialog(self, sv.list_profiles(self.profiles_dir), self.profile_box.currentText())
        if dlg.exec() != QDialog.Accepted:
            return
        path, name = dlg.target()
        if path is None:
            path = sv.profile_dir_for(self.profiles_dir, name)
            if (Path(path) / "profile.json").exists():
                QMessageBox.warning(self, APP_NAME, f"Профиль с таким именем уже есть: {name}")
                return
        self._run(sv.import_scans, (path, name, dlg.selected_files()), self._import_done,
                  "Импорт сканов… это может занять минуту")

    def _import_done(self, res: sv.ImportResult):
        self.reload_profiles(res.profile_name)
        ok = res.added or (res.skipped and not res.files_without_markers)
        (QMessageBox.information if ok else QMessageBox.warning)(self, "Импорт сканов", res.summary())

    def show_coverage(self):
        if not self._need_profile():
            return
        QMessageBox.information(self, "Что есть в профиле", sv.coverage_text(self.profile))

    def save_template(self, key: str = "main"):
        title = TEMPLATE_SETS[key].title
        path, _ = QFileDialog.getSaveFileName(self, f"Бланк: {title}", f"бланк_{title}.pdf", "PDF (*.pdf)")
        if path:
            self._run(save_template_pdf, (path, key), lambda n: QMessageBox.information(
                self, APP_NAME, f"Бланк «{title}» сохранён ({n} стр.). Распечатайте в реальном размере, "
                                "заполните ручкой и импортируйте сканы. Дополнительный бланк можно "
                                "заполнять много раз: каждый скан добавляет новые варианты букв."),
                      "Сохранение бланка…")

    def open_profiles_dir(self):
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.profiles_dir)))

    def choose_profiles_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Папка профилей", str(self.profiles_dir))
        if d:
            self.profiles_dir = Path(d)
            self.reload_profiles()

    def _need_profile(self) -> bool:
        if self.profile is None:
            QMessageBox.information(self, APP_NAME, "Сначала импортируйте сканы бланка: Почерк → Импорт сканов бланка.")
            return False
        return True

    # ---------- текст ----------

    def open_text(self):
        path, _ = QFileDialog.getOpenFileName(self, "Текст конспекта", "", "Текст (*.txt *.md);;Все файлы (*)")
        if path:
            raw = Path(path).read_bytes()
            for enc in ("utf-8-sig", "cp1251"):
                try:
                    self.text_edit.setPlainText(raw.decode(enc))
                    return
                except UnicodeDecodeError:
                    continue

    def _update_counter(self):
        self.chars_label.setText(f"{len(self.text_edit.toPlainText())} знаков")

    # ---------- предпросмотр ----------

    def schedule_preview(self, *_):
        self.timer.start()

    def next_variant(self):
        self.seed_spin.setValue(self.seed_spin.value() + 1)

    def refresh_preview(self):
        self.timer.stop()
        text = self.text_edit.toPlainText()
        if self.profile is None:
            self.pages_label.clear()
            self.pages.show_hint("Нет профиля почерка.\n\nПочерк → Сохранить основной бланк, заполните его ручкой, "
                                 "отсканируйте и нажмите «Импорт сканов…».")
            self._set_missing(set())
            return
        if not text.strip():
            self.pages_label.clear()
            self.pages.show_hint("Вставьте текст слева — здесь появятся страницы.")
            self._set_missing(set())
            return
        self._generation += 1
        gen = self._generation
        self.statusBar().showMessage("Генерация страниц…")
        self._start(Task(sv.render_text, text, self.profile, self.options(), sv.PREVIEW_DPI,
                         on_done=lambda r, g=gen: self._preview_done(g, r),
                         on_fail=lambda msg: self.statusBar().showMessage(f"Ошибка: {msg}")))

    def _preview_done(self, gen: int, r: sv.Rendered):
        if gen != self._generation:
            return
        self.pages.set_pages([to_qimage(im) for im in r.images])
        self._set_missing(r.missing)
        n = len(r.images)
        self.pages_label.setText(f"{n} {_plural(n, 'страница', 'страницы', 'страниц')}")
        self.statusBar().clearMessage()

    def _set_missing(self, missing: set[str]):
        self.last_missing = missing
        if missing:
            self.missing_label.setText("Нет образцов для символов (взяты из запасного шрифта): "
                                       + " ".join(sorted(missing)))
        self.missing_label.setVisible(bool(missing))

    # ---------- экспорт и печать ----------

    def save_pdf(self):
        if not self._need_profile() or not self.text_edit.toPlainText().strip():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить конспект", self.qs.value("last_pdf", "конспект.pdf"),
                                              "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self.qs.setValue("last_pdf", path)
        self._run(sv.export_pdf, (self.text_edit.toPlainText(), self.profile, self.options(), path),
                  lambda r: self.statusBar().showMessage(f"Сохранено: {path} ({len(r.images)} стр.)", 8000),
                  "Сохранение PDF…")

    def print_pages(self):
        if not self._need_profile() or not self.text_edit.toPlainText().strip():
            return
        opts = self.options()
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageLayout(QPageLayout(page_size(opts.page), QPageLayout.Portrait, printer.pageLayout().margins()))
        printer.setFullPage(True)  # страница рисуется в реальном размере, без масштабирования
        if QPrintDialog(printer, self).exec() != QDialog.Accepted:
            return
        self._run(sv.render_text, (self.text_edit.toPlainText(), self.profile, opts, sv.PRINT_DPI, True),
                  lambda r: self._paint_to_printer(printer, r), "Подготовка страниц к печати…")

    def _paint_to_printer(self, printer: QPrinter, r: sv.Rendered):
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.warning(self, APP_NAME, "Не удалось начать печать.")
            return
        target = printer.pageLayout().fullRectPixels(printer.resolution())
        for k, im in enumerate(r.images):
            if k:
                printer.newPage()
            painter.drawImage(target, to_qimage(im))
        painter.end()
        self.statusBar().showMessage(f"Отправлено на печать: {len(r.images)} стр.", 8000)

    # ---------- фоновые задачи ----------

    def _start(self, task: Task):
        self._busy_tasks.add(task)  # держим ссылку, пока задача не закончится
        task.signals.finished.connect(self._task_finished)
        self.pool.start(task)

    @Slot(object, object, str)
    def _task_finished(self, task: Task, res, err: str):
        self._busy_tasks.discard(task)
        if err:
            if task.on_fail:
                task.on_fail(err)
        elif task.on_done:
            task.on_done(res)

    def busy(self) -> bool:
        return bool(self._busy_tasks)

    def _run(self, fn, args: tuple, on_done, message: str):
        """Долгое действие с блокировкой окна и сообщением в строке состояния."""
        self.statusBar().showMessage(message)
        self.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)

        def finish():
            QApplication.restoreOverrideCursor()
            self.setEnabled(True)
            self.statusBar().clearMessage()

        def ok(res):
            finish()
            on_done(res)

        def fail(msg):
            finish()
            QMessageBox.critical(self, APP_NAME, msg)

        self._start(Task(fn, *args, on_done=ok, on_fail=fail))


def main(argv: list[str] | None = None) -> int:
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 10))
    if os.environ.get("KONSPEKT_SMOKE"):
        return _smoke(app)
    w = MainWindow(os.environ.get("KONSPEKT_PROFILES"))
    w.show()
    return app.exec()


def _smoke(app: QApplication) -> int:
    """Проверка собранной программы: все части на месте (словари переносов,
    запасной шрифт, OpenCV, PDF), окно открывается."""
    import tempfile

    from .layout import FALLBACK_FONT, Typesetter  # noqa: F401
    import pyphen

    assert FALLBACK_FONT.exists(), FALLBACK_FONT
    assert pyphen.Pyphen(lang="ru_RU").inserted("конспект") != "конспект"
    with tempfile.TemporaryDirectory() as d:
        assert save_template_pdf(Path(d) / "бланк.pdf") > 0
        w = MainWindow(Path(d) / "profiles", QSettings(str(Path(d) / "s.ini"), QSettings.IniFormat))
        w.show()
        QTimer.singleShot(1000, app.quit)
        app.exec()
        w.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
