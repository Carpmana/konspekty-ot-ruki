"""Окно приложения: настройки слева, текст посередине, страницы справа.

    python -m konspekt.gui

Тяжёлая работа (импорт сканов, генерация страниц) идёт в фоновом потоке,
чтобы окно не зависало. Сами действия — в service.py.
"""

import datetime
import os
import sys
import traceback
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, QSettings, QSizeF, Qt, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import (
    QAction, QColor, QDesktopServices, QFont, QIcon, QImage, QPen, QKeySequence, QPageLayout, QPageSize, QPainter, QPixmap,
)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QSplitter, QToolButton,
    QVBoxLayout, QWidget,
)

from . import service as sv
from .charset import DIGITS, PUNCT, RU_LOWER, RU_UPPER
from .profile import DRAWN_SOURCE, GlyphSample, Profile
from .template import TEMPLATE_SETS, save_template_pdf

APP_NAME = "Конспекты от руки"
PREVIEW_DELAY_MS = 700

ACCENT = "#3156c8"
ASSETS = (Path(__file__).parent / "assets").as_posix()

STYLE = f"""
QMainWindow, QWidget#body {{ background: #f4f5f8; }}
QDialog, QMessageBox {{ background: #ffffff; }}
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
QToolButton#sample {{ background: #ffffff; border: 2px solid #d5d9e3; border-radius: 8px; padding: 4px; }}
QToolButton#sample:checked {{ border-color: {ACCENT}; }}
QToolButton#sample:!checked {{ background: #fbe9e9; border: 2px dashed #c0392b; }}
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
1. вопрос с номером,  = строка по центру,  >> строка справа (дата)
_подчеркнуть_,  [[в рамку]],  -> стрелка,  x^2 степень,  H_2O индекс
Всё это есть в кнопке «Вставить ▾». Пустая строка — отступ."""


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def page_size(key: str, spread: bool = False) -> QPageSize:
    if spread:  # развёрнутый двойной листок 340×205: в принтер узкой стороной, печать альбомная
        w, h = sv.FORMAT_BY_KEY[key].size_mm
        return QPageSize(QSizeF(h, 2 * w), QPageSize.Millimeter, "Двойной листок", QPageSize.ExactMatch)
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


def sample_pixmap(prof: Profile, s: GlyphSample, height: int = 90) -> QPixmap:
    a = prof.image(s)
    gray = np.ascontiguousarray(255 - np.clip(a * 255, 0, 255).astype(np.uint8))
    im = QImage(gray.data, gray.shape[1], gray.shape[0], gray.strides[0], QImage.Format_Grayscale8).copy()
    return QPixmap.fromImage(im).scaledToHeight(height, Qt.SmoothTransformation)


class SamplesDialog(QDialog):
    """Все варианты одного символа. Щелчок по образцу отключает его (рамка
    становится красной пунктирной) или возвращает обратно."""

    def __init__(self, parent, prof: Profile, start: str = ""):
        super().__init__(parent)
        self.prof = prof
        self.enabled = {s.id: s.enabled for s in prof.samples}
        self.suspect = {s.id for s in prof.find_crossed()}
        self.setWindowTitle(f"Образцы букв — {prof.name}")
        self.resize(720, 520)
        lay = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Символ:"))
        self.text_box = QComboBox()
        texts = sorted({s.text for s in prof.samples}, key=lambda t: (len(t), t.lower(), t))
        for t in texts:
            n = sum(1 for s in prof.samples if s.text == t)
            self.text_box.addItem(f"{t}   ({n})", t)
        row.addWidget(self.text_box, 1)
        self.crossed_btn = QPushButton("Отключить похожие на зачёркнутые")
        self.crossed_btn.clicked.connect(self._disable_suspects)
        row.addWidget(self.crossed_btn)
        lay.addLayout(row)
        lay.addWidget(QLabel("Щёлкните по неудачному или зачёркнутому образцу, чтобы программа его не брала. "
                             "Щёлкните ещё раз, чтобы вернуть.", objectName="hint", wordWrap=True))

        self.grid_box = QWidget()
        self.grid = QGridLayout(self.grid_box)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(self.grid_box)
        lay.addWidget(area, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        first_suspect = next((s.text for s in prof.samples if s.id in self.suspect), "")
        i = self.text_box.findData(start or first_suspect)
        self.text_box.setCurrentIndex(max(i, 0))
        self.text_box.currentIndexChanged.connect(self._show)
        self._show()

    def buttons_for_current(self) -> list[QToolButton]:
        return [self.grid.itemAt(i).widget() for i in range(self.grid.count())]

    def _show(self, *_):
        while self.grid.count():
            old = self.grid.takeAt(0).widget()
            old.setParent(None)
            old.deleteLater()
        text = self.text_box.currentData()
        for k, s in enumerate(s for s in self.prof.samples if s.text == text):
            b = QToolButton(objectName="sample")
            b.setCheckable(True)
            b.setChecked(self.enabled[s.id])
            pm = sample_pixmap(self.prof, s)
            b.setIcon(pm)
            b.setIconSize(pm.size())
            tip = s.source or ""
            if s.id in self.suspect:
                tip = "Похоже на зачёркнутый. " + tip
            b.setToolTip(tip)
            b.setProperty("sample_id", s.id)
            b.toggled.connect(lambda on, sid=s.id: self.enabled.__setitem__(sid, on))
            self.grid.addWidget(b, k // 5, k % 5)

    def _disable_suspects(self):
        for sid in self.suspect:
            self.enabled[sid] = False
        self._show()
        n = len(self.suspect)
        QMessageBox.information(self, APP_NAME, f"Отключено образцов: {n}. Нажмите «Сохранить»."
                                if n else "Зачёркнутых образцов не найдено.")

    def changed(self) -> int:
        return sum(1 for s in self.prof.samples if s.enabled != self.enabled[s.id])

    def _save(self):
        for s in self.prof.samples:
            s.enabled = self.enabled[s.id]
        self.prof.measure()
        self.prof.save()
        self.accept()


class DrawCanvas(QWidget):
    """Клетка тетради, в которой букву рисуют мышью, тачпадом или пером.
    Координаты штрихов хранятся в миллиметрах клетки."""

    BASELINE_MM = 16.0
    HEIGHT_MM = 25.0

    def __init__(self, x_height_mm: float, stroke_mm: float, ink: tuple[int, int, int]):
        super().__init__()
        self.xh = x_height_mm
        self.stroke_mm = stroke_mm
        self.ink = QColor(*ink)
        self.width_mm = 30.0
        self.strokes: list[list[tuple[float, float]]] = []
        self.setMinimumSize(420, 300)
        self.setCursor(Qt.CrossCursor)
        self.setAttribute(Qt.WA_AcceptTouchEvents, False)

    def set_chars(self, n: int):
        self.width_mm = 20.0 + 12.0 * max(1, n)
        self.update()

    def _scale(self) -> float:
        return min(self.width() / self.width_mm, self.height() / self.HEIGHT_MM)

    def _offset(self) -> float:
        return max(0.0, (self.width() - self.width_mm * self._scale()) / 2)

    def _to_mm(self, pos) -> tuple[float, float]:
        k = self._scale()
        return (pos.x() - self._offset()) / k, pos.y() / k

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.strokes.append([self._to_mm(e.position())])
            self.update()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton and self.strokes:
            self.strokes[-1].append(self._to_mm(e.position()))
            self.update()

    def undo(self):
        if self.strokes:
            self.strokes.pop()
            self.update()

    def clear(self):
        self.strokes = []
        self.update()

    def paintEvent(self, e):
        k = self._scale()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(self._offset(), 0)
        p.fillRect(0, 0, int(self.width_mm * k), int(self.HEIGHT_MM * k), QColor("#ffffff"))
        p.setPen(QPen(QColor("#d4def2"), 1))
        x = 0.0
        while x <= self.width_mm:
            p.drawLine(int(x * k), 0, int(x * k), int(self.HEIGHT_MM * k))
            x += 5.0
        y = 0.0
        while y <= self.HEIGHT_MM:
            p.drawLine(0, int(y * k), int(self.width_mm * k), int(y * k))
            y += 5.0
        b = self.BASELINE_MM
        for yy, color, style in ((b, "#3156c8", Qt.SolidLine), (b - self.xh, "#3156c8", Qt.DashLine),
                                 (b - 2 * self.xh, "#9fb1e3", Qt.DotLine), (b + self.xh, "#9fb1e3", Qt.DotLine)):
            p.setPen(QPen(QColor(color), 2, style))
            p.drawLine(0, int(yy * k), int(self.width_mm * k), int(yy * k))
        pen = QPen(self.ink, max(self.stroke_mm * k, 1.5), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        for st in self.strokes:
            if len(st) == 1:
                p.drawPoint(int(st[0][0] * k), int(st[0][1] * k))
            for (x0, y0), (x1, y1) in zip(st, st[1:]):
                p.drawLine(int(x0 * k), int(y0 * k), int(x1 * k), int(y1 * k))
        p.end()


class DrawDialog(QDialog):
    """Дорисовать варианты букв без сканера: нарисовать, сохранить, удалить неудачный."""

    def __init__(self, parent, prof: Profile, start: str = ""):
        super().__init__(parent)
        self.prof = prof
        self.setWindowTitle(f"Нарисовать буквы — {prof.name}")
        self.resize(760, 640)
        lay = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Буква или сочетание:"))
        self.text_box = QComboBox()
        self.text_box.setEditable(True)
        self.text_box.addItems(list(RU_LOWER + RU_UPPER + DIGITS + PUNCT))
        self.text_box.setCurrentText(start or "а")
        row.addWidget(self.text_box, 1)
        self.count_label = QLabel(objectName="hint")
        row.addWidget(self.count_label)
        lay.addLayout(row)
        lay.addWidget(QLabel("Пишите в клетке мышью, на тачпаде или пером: строчные стоят на синей линии и "
                             "доходят до пунктира. Неудачный штрих — «Отменить штрих». Сохраните несколько "
                             "вариантов одной буквы, программа будет их чередовать.", objectName="hint",
                             wordWrap=True))

        p = prof.params
        self.canvas = DrawCanvas(p.x_height_mm, p.stroke_mm, p.ink_color)
        lay.addWidget(self.canvas, 1)

        buttons = QHBoxLayout()
        undo = QPushButton("Отменить штрих")
        undo.setShortcut(QKeySequence.Undo)
        undo.clicked.connect(self.canvas.undo)
        clear = QPushButton("Стереть")
        clear.clicked.connect(self.canvas.clear)
        self.save_btn = QPushButton("Сохранить вариант", objectName="primary")
        self.save_btn.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_Return))
        self.save_btn.clicked.connect(self.save_variant)
        buttons.addWidget(undo)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        buttons.addWidget(self.save_btn)
        lay.addLayout(buttons)

        lay.addWidget(QLabel("Варианты этой буквы. Нарисованный щелчком удаляется, "
                             "со скана — отключается или возвращается:", objectName="hint", wordWrap=True))
        self.strip_box = QWidget()
        self.strip = QHBoxLayout(self.strip_box)
        self.strip.setAlignment(Qt.AlignLeft)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(self.strip_box)
        area.setFixedHeight(130)
        lay.addWidget(area)

        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.button(QDialogButtonBox.Close).setText("Готово")
        close.rejected.connect(self.accept)
        lay.addWidget(close)

        self.text_box.currentTextChanged.connect(self._text_changed)
        self._text_changed()

    def text(self) -> str:
        return self.text_box.currentText().strip()

    def _text_changed(self, *_):
        self.canvas.clear()
        self.canvas.set_chars(len(self.text()))
        self._show_variants()

    def strip_buttons(self) -> list[QToolButton]:
        return [self.strip.itemAt(i).widget() for i in range(self.strip.count())]

    def _show_variants(self):
        while self.strip.count():
            old = self.strip.takeAt(0).widget()
            old.setParent(None)
            old.deleteLater()
        found = [s for s in self.prof.samples if s.text == self.text()]
        on = sum(1 for s in found if s.enabled)
        self.count_label.setText(f"вариантов: {on}")
        for s in found:
            b = QToolButton(objectName="sample")
            b.setCheckable(True)
            b.setChecked(s.enabled)
            pm = sample_pixmap(self.prof, s, 80)
            b.setIcon(pm)
            b.setIconSize(pm.size())
            b.setProperty("sample_id", s.id)
            drawn = s.source == DRAWN_SOURCE
            b.setToolTip("Нарисован здесь: щелчок удаляет" if drawn else f"Со скана: {s.source}")
            b.clicked.connect(lambda _=False, sid=s.id, d=drawn: self._variant_clicked(sid, d))
            self.strip.addWidget(b)

    def _variant_clicked(self, sid: str, drawn: bool):
        if drawn:
            self.prof.remove(sid)
        else:
            s = next(x for x in self.prof.samples if x.id == sid)
            s.enabled = not s.enabled
            self.prof.measure()
        self.prof.save()
        self._show_variants()

    def save_variant(self):
        if not self.text() or not self.canvas.strokes:
            return
        sv.add_drawn_sample(self.prof, self.text(), self.canvas.strokes, DrawCanvas.BASELINE_MM)
        self.canvas.clear()
        self._show_variants()


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
        blank = QPushButton("Бланк ▾")
        blank.setToolTip("Сохранить бланк образцов для заполнения ручкой")
        blank_menu = QMenu(blank)
        for key, ts in TEMPLATE_SETS.items():
            blank_menu.addAction(f"{ts.title.capitalize()} бланк…", lambda k=key: self.save_template(k))
        blank.setMenu(blank_menu)
        row.addWidget(imp, 1)
        row.addWidget(blank)
        sl.addLayout(row)
        row2 = QHBoxLayout()
        samples = QPushButton("Образцы букв…")
        samples.setToolTip("Посмотреть варианты каждой буквы и отключить неудачные или зачёркнутые (Ctrl+B)")
        samples.clicked.connect(self.edit_samples)
        draw = QPushButton("Нарисовать…")
        draw.setToolTip("Дописать варианты букв мышью или на тачпаде, удалить и переделать неудачные (Ctrl+D)")
        draw.clicked.connect(self.draw_letters)
        row2.addWidget(samples, 1)
        row2.addWidget(draw, 1)
        sl.addLayout(row2)

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
        self.tired_slider = QSlider(Qt.Horizontal)
        self.tired_slider.setRange(0, 10)
        self.tired_slider.setToolTip("К концу конспекта почерк становится крупнее, размашистее и небрежнее, "
                                     "строки уползают вверх — как у уставшей руки")
        sl.addWidget(QLabel("Рука устаёт к концу"))
        sl.addWidget(self.tired_slider)
        self.fix_slider = QSlider(Qt.Horizontal)
        self.fix_slider.setRange(0, 10)
        self.fix_slider.setToolTip("Изредка перед словом пишется описка и зачёркивается. 0 — без исправлений")
        sl.addWidget(QLabel("Исправления (зачёркнутые описки)"))
        sl.addWidget(self.fix_slider)
        fends = QHBoxLayout()
        fends.addWidget(QLabel("нет", objectName="hint"))
        fends.addStretch(1)
        fends.addWidget(QLabel("часто", objectName="hint"))
        sl.addLayout(fends)
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
        self.spread_box = QCheckBox("Двойной листок целиком\n(2 страницы рядом, с оборотом)")
        self.spread_box.setToolTip("Развёрнутый двойной листок 340×205 мм вставляется в принтер узкой стороной. "
                                   "Сначала печатаются страницы 4 и 1, потом листок переворачивают — 2 и 3.")
        sl.addWidget(self.spread_box)
        self.nested_box = QCheckBox("Листки вкладывать друг в друга\n(как тетрадь)")
        self.nested_box.setToolTip("Включено: листок 1 внешний, в нём начало и конец конспекта, середина — "
                                   "на самом внутреннем листке. Выключено: листки идут стопкой, "
                                   "на листке 1 страницы 1–4, на листке 2 — 5–8.")
        self.nested_box.setChecked(True)
        sl.addWidget(self.nested_box)
        self.flip_back = QCheckBox("Оборот вверх ногами")
        self.flip_back.setToolTip("Включите, если на обороте текст вышел перевёрнутым: "
                                  "зависит от того, как принтер берёт листок.")
        sl.addWidget(self.flip_back)
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
        insert_btn = QPushButton("Вставить ▾")
        insert_btn.setToolTip("Дата, тема, вопрос с номером, подчёркивание, рамка, стрелка, степень")
        self.insert_menu = QMenu(insert_btn)
        insert_btn.setMenu(self.insert_menu)
        top.addWidget(insert_btn)
        dictate_btn = QPushButton("Диктовать")
        dictate_btn.setToolTip("Голосовой ввод Windows (Win+H): говорите, текст появится в поле")
        dictate_btn.clicked.connect(self.dictate)
        top.addWidget(dictate_btn)
        open_btn = QPushButton("Открыть файл…")
        open_btn.setToolTip("Текст (.txt) или документ Word (.docx)")
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
                    self.neat_slider.valueChanged, self.tired_slider.valueChanged, self.fix_slider.valueChanged,
                    self.size_spin.valueChanged, self.pitch_spin.valueChanged,
                    self.show_missing.toggled, self.text_edit.textChanged):
            sig.connect(self.schedule_preview)
        self.text_edit.textChanged.connect(self._update_counter)
        self.page_box.currentIndexChanged.connect(self._format_changed)
        self.paper_box.currentIndexChanged.connect(self._lining_changed)
        self.real_paper.toggled.connect(self._update_print_mode)
        self.spread_box.toggled.connect(self._update_print_mode)
        self.spread_box.toggled.connect(self.schedule_preview)
        self.nested_box.toggled.connect(self.schedule_preview)
        self.page_box.currentIndexChanged.connect(self._update_print_mode)
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
        notebook = self.page_box.currentData() == "notebook"
        self.spread_box.setVisible(notebook)
        self.flip_back.setVisible(notebook and self.spread_box.isChecked())
        self.nested_box.setVisible(notebook and self.spread_box.isChecked())

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
        act(m, "Образцы букв…", self.edit_samples, "Ctrl+B")
        act(m, "Нарисовать буквы…", self.draw_letters, "Ctrl+D")
        m.addSeparator()
        act(m, "Открыть папку профилей", self.open_profiles_dir)
        act(m, "Выбрать папку профилей…", self.choose_profiles_dir)

        m = self.menuBar().addMenu("Вставить")
        self._fill_insert_menu(m, act)
        self._fill_insert_menu(self.insert_menu, act, shortcuts=False)

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
        self.tired_slider.setValue(int(q.value("tiredness10", 3)))
        self.fix_slider.setValue(int(q.value("corrections10", 0)))
        self.size_spin.setValue(float(q.value("size_mm", 0.0)))
        self.pitch_spin.setValue(float(q.value("pitch_mm", 10.0)))
        self.real_paper.setChecked(q.value("real_paper", "false") in (True, "true"))
        self.off_x.setValue(float(q.value("offset_x_mm", 0.0)))
        self.off_y.setValue(float(q.value("offset_y_mm", 0.0)))
        self.spread_box.setChecked(q.value("spread", "false") in (True, "true"))
        self.flip_back.setChecked(q.value("flip_back", "false") in (True, "true"))
        self.nested_box.setChecked(q.value("nested", "true") in (True, "true"))
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
        q.setValue("spread", self.spread_box.isChecked())
        q.setValue("flip_back", self.flip_back.isChecked())
        q.setValue("nested", self.nested_box.isChecked())
        q.setValue("seed", self.seed_spin.value())
        q.setValue("neatness10", self.neat_slider.value())
        q.setValue("tiredness10", self.tired_slider.value())
        q.setValue("corrections10", self.fix_slider.value())
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
                          offset_y_mm=self.off_y.value(), spread=self.spread_box.isChecked(),
                          nested=self.nested_box.isChecked(), tiredness=self.tired_slider.value() / 10,
                          corrections=self.fix_slider.value() / 200)

    # ---------- профили ----------

    def reload_profiles(self, select: str | None = None):
        self.profile_errors = []
        profiles = sv.list_profiles(self.profiles_dir, self.profile_errors)
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
            except Exception as e:
                QMessageBox.warning(self, APP_NAME, f"Не удалось открыть профиль:\n{e}")
        if self.profile is not None:
            self._offer_crossed()
        self.refresh_preview()

    def _offer_crossed(self):
        """Спрашивает один раз про образцы, похожие на зачёркнутые."""
        found = self.profile.find_crossed()
        key = "crossed_answered/" + self.profile.name
        ids = " ".join(sorted(s.id for s in found))
        if not found or self.qs.value(key, "") == ids:
            return
        letters = " ".join(sorted({s.text for s in found}))
        answer = QMessageBox.question(
            self, APP_NAME,
            f"В почерке «{self.profile.name}» есть образцы, похожие на зачёркнутые: {letters}.\n\n"
            "Отключить их, чтобы программа их не писала? Вернуть можно в «Образцы букв…».")
        if answer == QMessageBox.Yes:
            sv.disable_crossed(self.profile)
        else:
            self.qs.setValue(key, ids)

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

    def draw_letters(self):
        if not self._need_profile():
            return
        DrawDialog(self, self.profile).exec()
        self.refresh_preview()

    def edit_samples(self):
        if not self._need_profile():
            return
        dlg = SamplesDialog(self, self.profile)
        if dlg.exec() == QDialog.Accepted:
            self.refresh_preview()

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
        path, _ = QFileDialog.getOpenFileName(self, "Текст конспекта", "",
                                              "Текст и Word (*.txt *.md *.docx);;Все файлы (*)")
        if path:
            try:
                self.text_edit.setPlainText(sv.read_text_file(path))
            except Exception as e:  # битый или не тот файл
                QMessageBox.warning(self, APP_NAME, f"Не удалось открыть файл:\n{e}")

    # ---------- вставки ----------

    def _fill_insert_menu(self, m: QMenu, act, shortcuts: bool = True):
        def key(k):
            return k if shortcuts else None

        today = datetime.date.today
        act(m, "Дата справа (словами)", lambda: self.insert_line(">> " + sv.date_words(today())))
        act(m, "Дата справа (цифрами)", lambda: self.insert_line(">> " + today().strftime("%d.%m.%Y")))
        act(m, "«Классная работа» по центру", lambda: self.insert_line("= Классная работа"))
        act(m, "«Домашняя работа» по центру", lambda: self.insert_line("= Домашняя работа"))
        act(m, "Тема по центру", lambda: self.insert_line("= Тема: ", select_end=True))
        act(m, "Вопрос с номером", self.insert_question, key("Ctrl+Shift+N"))
        m.addSeparator()
        act(m, "Подчеркнуть выделенное", lambda: self.wrap_selection("_", "_"), key("Ctrl+U"))
        act(m, "Обвести выделенное рамкой", lambda: self.wrap_selection("[[", "]]"), key("Ctrl+Shift+B"))
        act(m, "Стрелка →", lambda: self.text_edit.insertPlainText(" -> "))
        act(m, "Степень (x²)", lambda: self.wrap_selection("^{", "}"))
        act(m, "Индекс (x₂)", lambda: self.wrap_selection("_{", "}"))

    def insert_line(self, line: str, select_end: bool = False):
        """Вставляет отдельную строку там, где курсор."""
        c = self.text_edit.textCursor()
        c.movePosition(c.MoveOperation.StartOfBlock)
        has_text = bool(c.block().text().strip())
        c.insertText(line + ("\n" if has_text else ""))
        if has_text:
            c.movePosition(c.MoveOperation.PreviousBlock)
            c.movePosition(c.MoveOperation.EndOfBlock)
        self.text_edit.setTextCursor(c)
        self.text_edit.setFocus()

    def insert_question(self):
        c = self.text_edit.textCursor()
        before = self.text_edit.toPlainText()[:c.position()]
        self.insert_line(f"{sv.next_question_number(before)}. ")

    def wrap_selection(self, left: str, right: str):
        c = self.text_edit.textCursor()
        text = c.selectedText().strip()
        c.insertText(f"{left}{text}{right}")
        if not text:
            c.movePosition(c.MoveOperation.Left, n=len(right))
        self.text_edit.setTextCursor(c)
        self.text_edit.setFocus()

    def dictate(self):
        """Голосовой ввод Windows: в поле текста нажимаем за пользователя Win+H."""
        self.text_edit.setFocus()
        if sys.platform != "win32":
            QMessageBox.information(self, APP_NAME, "Голосовой ввод работает в Windows: Win+H.")
            return

        def press():
            try:
                import ctypes
                user32 = ctypes.windll.user32
                VK_LWIN, VK_H, UP = 0x5B, 0x48, 0x0002
                user32.keybd_event(VK_LWIN, 0, 0, 0)
                user32.keybd_event(VK_H, 0, 0, 0)
                user32.keybd_event(VK_H, 0, UP, 0)
                user32.keybd_event(VK_LWIN, 0, UP, 0)
            except (AttributeError, OSError):
                pass
        QTimer.singleShot(150, press)
        self.statusBar().showMessage("Говорите — текст появится в поле. Если панель не открылась, нажмите Win+H.",
                                     10000)

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
            if getattr(self, "profile_errors", None):
                self.pages.show_hint("Профиль почерка не открылся:\n\n" + "\n".join(self.profile_errors)
                                     + f"\n\nПапка профилей: {self.profiles_dir}")
            else:
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
        images = [to_qimage(im) for im in r.images]
        if r.is_spread:  # линия сгиба только на экране, на печать не идёт
            for qi in images:
                p = QPainter(qi)
                p.setPen(QPen(QColor(120, 130, 150), 1, Qt.DashLine))
                p.drawLine(qi.width() // 2, 0, qi.width() // 2, qi.height())
                p.end()
        self.pages.set_pages(images)
        self._set_missing(r.missing)
        n = len(r.images)
        if r.is_spread:
            k = n // 2
            how = ("вложить друг в друга, листок 1 снаружи" if self.nested_box.isChecked() and k > 1
                   else "сложить стопкой по порядку" if k > 1 else "сначала наружная сторона, потом внутренняя")
            self.pages_label.setText(f"{k} {_plural(k, 'двойной листок', 'двойных листка', 'двойных листков')}: {how}")
        else:
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
        orient = QPageLayout.Landscape if opts.use_spread else QPageLayout.Portrait
        printer.setPageLayout(QPageLayout(page_size(opts.page, opts.use_spread), orient,
                                          printer.pageLayout().margins()))
        printer.setFullPage(True)  # страница рисуется в реальном размере, без масштабирования
        if QPrintDialog(printer, self).exec() != QDialog.Accepted:
            return
        self._run(sv.render_text, (self.text_edit.toPlainText(), self.profile, opts, sv.PRINT_DPI, True),
                  lambda r: self._paint_to_printer(printer, r), "Подготовка страниц к печати…")

    def _paint_to_printer(self, printer: QPrinter, r: sv.Rendered, ask_flip: bool = True):
        if not r.is_spread:
            if self._paint_images(printer, r.images):
                self.statusBar().showMessage(f"Отправлено на печать: {len(r.images)} стр.", 8000)
            return
        # Двойные листки печатаются по одному: снаружи, переворот, внутри, следующий листок.
        sheets = r.sheets()
        n = len(sheets)

        def ask(title: str, text: str) -> bool:
            return not ask_flip or QMessageBox.information(
                self, title, text, QMessageBox.Ok | QMessageBox.Cancel) == QMessageBox.Ok

        for i, (outer, inner) in enumerate(sheets):
            head = f"Листок {i + 1} из {n}"
            if i and not ask(head, f"Вставьте чистый двойной листок развёрнутым, как первый.\n\n"
                                   f"Напечатается: {r.labels[outer]}.\n\n"
                                   "Совет: подпишите карандашом в уголке номер листка — так их не перепутать."):
                return
            if not self._paint_images(printer, [r.images[outer]]):
                return
            if inner is None:
                continue
            im = r.images[inner].rotate(180) if self.flip_back.isChecked() else r.images[inner]
            if not ask(head, f"Наружная сторона напечатана.\n\n"
                             "Дайте чернилам высохнуть, переверните этот же листок чистой стороной "
                             "и вставьте его снова тем же краем вперёд.\n\n"
                             f"Напечатается: {r.labels[inner]}."):
                return
            if not self._paint_images(printer, [im]):
                return
        done = f"Готово: {n} {_plural(n, 'двойной листок', 'двойных листка', 'двойных листков')}."
        if n > 1 and self.nested_box.isChecked():
            done += ("\n\nСоберите тетрадь: листок 1 снаружи, в него вложите листок 2"
                     + (", в него листок 3" if n > 2 else "")
                     + (" и так далее" if n > 3 else "") + ". Сложите пополам — страницы пойдут по порядку.")
        elif n > 1:
            done += "\n\nСложите листки стопкой по номерам: листок 1 сверху."
        self.statusBar().showMessage(done.split("\n")[0], 8000)
        if ask_flip and n > 1:
            QMessageBox.information(self, "Печать на двойной листок", done)

    def _paint_images(self, printer: QPrinter, images) -> bool:
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.warning(self, APP_NAME, "Не удалось начать печать.")
            return False
        target = printer.pageLayout().fullRectPixels(printer.resolution())
        for k, im in enumerate(images):
            if k:
                printer.newPage()
            painter.drawImage(target, to_qimage(im))
        painter.end()
        return True

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


def apply_light_theme(app: QApplication):
    """Всегда светлое оформление: в тёмной теме Windows окна-вопросы были
    тёмными с тёмным текстом и не читались."""
    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):
        hints.setColorScheme(Qt.ColorScheme.Light)
    app.setPalette(app.style().standardPalette())


def main(argv: list[str] | None = None) -> int:
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(f"{ASSETS}/icon.png"))
    app.setStyle("Fusion")
    apply_light_theme(app)
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 10))
        try:  # своя иконка на панели задач, а не значок Python
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Carpmana.Konspekt")
        except (AttributeError, OSError):
            pass
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
