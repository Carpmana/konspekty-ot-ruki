"""Окно приложения: настройки слева, текст посередине, страницы справа.

    python -m konspekt.gui

Тяжёлая работа (импорт сканов, генерация страниц) идёт в фоновом потоке,
чтобы окно не зависало. Сами действия — в service.py.
"""

import datetime
import os
import sys
import time
import traceback
from pathlib import Path

import numpy as np
from PySide6.QtCore import (
    QEasingCurve, QObject, QProcess, QPropertyAnimation, QRectF, QRunnable, QSettings, QSize, QSizeF, Qt, QThreadPool,
    QTimer, QUrl, Signal, Slot,
)
from PySide6.QtGui import (
    QAction, QColor, QDesktopServices, QFont, QIcon, QImage, QPen, QKeySequence, QPageLayout, QPageSize, QPainter, QPixmap,
)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton, QRadioButton, QScrollArea, QSizePolicy,
    QSlider, QSpinBox, QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from . import icons, service as sv
from . import updates
from .charset import DIGITS, PUNCT, RU_LOWER, RU_UPPER
from .layout import Settings as LayoutSettings, typeset
from .profile import DRAWN_SOURCE, RAISE_LIMITS_MM, SCALE_LIMITS, GlyphSample, Profile
from .render import render_page
from .print_wizard import PrintPage, PrintStep
from .template import TEMPLATE_SETS, save_template_pdf
from .viewer import PagesView

APP_NAME = "Конспекты от руки"
PREVIEW_DELAY_MS = 700

ACCENT = "#1b7a57"
ASSETS = (Path(__file__).parent / "assets").as_posix()

STYLE = f"""
QMainWindow, QWidget#body {{ background: #f3f5f8; }}
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
QPlainTextEdit {{ border: none; background: #ffffff; font-size: 11.5pt; selection-background-color: #cbe8da; }}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: #ffffff; border: 1px solid #d5d9e3; border-radius: 6px; padding: 4px 8px; min-height: 22px; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({ASSETS}/arrow-down.svg); width: 10px; height: 6px; }}
QComboBox QAbstractItemView {{ border: 1px solid #d5d9e3; selection-background-color: #e1f0e8;
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
QPushButton#primary:hover {{ background: #14603f; }}
QPushButton:disabled {{ color: #9aa1b2; }}
QPushButton#primary:disabled {{ background: #8ea3e0; border-color: #8ea3e0; color: #ffffff; }}
QSlider::groove:horizontal {{ height: 4px; background: #dfe3ec; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #ffffff; border: 2px solid {ACCENT}; width: 14px; height: 14px;
                              margin: -6px 0; border-radius: 8px; }}
QRadioButton, QCheckBox {{ spacing: 8px; }}
QToolButton#sample {{ background: #ffffff; border: 2px solid #d5d9e3; border-radius: 8px; padding: 4px; }}
QToolButton#sample:checked {{ border-color: {ACCENT}; }}
QToolButton#sample:!checked {{ background: #fbe9e9; border: 2px dashed #c0392b; }}
QToolButton#help {{ background: #ffffff; border: 1px solid #c9cfdc; border-radius: 9px; color: #6b7385;
                    font-weight: 600; min-width: 16px; max-width: 16px; min-height: 16px; max-height: 16px; padding: 0; }}
QToolButton#help:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QLabel#missing {{ background: #fff4c2; color: #5a4a00; padding: 8px 10px; border-radius: 8px; }}
QStatusBar {{ background: #ffffff; border-top: 1px solid #e3e6ee; color: #6b7385; }}
QSplitter::handle {{ background: transparent; }}
QLabel#logo {{ background: {ACCENT}; border-radius: 9px; }}
QPushButton#sectionHead {{ text-align: left; border: none; background: transparent; padding: 9px 10px;
                          font-weight: 600; border-radius: 8px; icon-size: 16px; }}
QPushButton#sectionHead:hover {{ background: #eaf4ef; }}
QLabel#sectionSummary {{ color: #6b7385; font-size: 9pt; }}
QFrame#card QFrame#cardHead {{ border: none; border-bottom: 1px solid #eef0f4; border-radius: 0; background: transparent; }}
QLabel#cardFoot {{ color: #6b7385; font-size: 9pt; padding: 6px 14px; border-top: 1px solid #eef0f4; }}
QPushButton#small {{ padding: 3px 10px; }}
QToolButton#iconButton {{ border: 1px solid #d5d9e3; border-radius: 6px; background: #ffffff; padding: 4px; }}
QToolButton#iconButton:hover {{ background: #eef1f8; }}
QFrame#viewerBar {{ background: #ffffff; border: none; border-bottom: 1px solid #eef0f4; border-radius: 0; }}
QFrame#seg {{ background: #eceef3; border: none; border-radius: 8px; }}
QPushButton#segButton {{ border: none; background: transparent; padding: 4px 11px; border-radius: 6px;
                        color: #4a5265; font-size: 9pt; }}
QPushButton#segButton:hover {{ background: #e2e6ef; }}
QPushButton#segButton:checked {{ background: #ffffff; color: #1f2430; font-weight: 600; }}
QToolButton#viewerTool {{ border: none; border-radius: 6px; padding: 5px; }}
QToolButton#viewerTool:hover {{ background: #eef1f8; }}
QLabel#viewerLabel {{ font-size: 9.5pt; }}
QFrame#viewerSep {{ background: #e3e6ee; border: none; }}
QPushButton#viewerFit {{ padding: 4px 10px; font-size: 9pt; }}
QPushButton#viewerFit:checked {{ background: #e1f0e8; border-color: {ACCENT}; }}
QScrollArea#pagesArea, QScrollArea#pagesArea > QWidget {{ background: #e9ebf0; border: none; }}
QLabel#viewerHint {{ color: #6b7385; font-size: 12pt; background: transparent; }}
QListWidget#thumbs {{ background: #fafbfc; border: none; border-top: 1px solid #eef0f4; padding: 4px 8px;
                     outline: none; }}
QListWidget#thumbs::item {{ color: #6b7385; border-radius: 6px; padding: 3px; }}
QListWidget#thumbs::item:selected {{ background: #e1f0e8; color: #1f2430; }}
QDialog#fullView {{ background: #e9ebf0; }}
QFrame#rail {{ background: #1d2230; }}
QToolButton#railButton {{ color: #aab3c5; background: transparent; border: none; border-radius: 12px;
                         font-size: 9pt; padding: 6px 0; }}
QToolButton#railButton:hover {{ background: #2a3142; color: #ffffff; }}
QToolButton#railButton:checked {{ background: #2f3a52; color: #ffffff; }}
QWidget#page {{ background: #f3f5f8; }}
QFrame#planPanel {{ background: #f3f5f8; border-right: 1px solid #e4e8ef; }}
QWidget#printPage {{ background: #f7f8fb; }}
QLabel#planTitle {{ font-size: 13pt; font-weight: 600; }}
QScrollArea#planList, QScrollArea#planList > QWidget > QWidget {{ background: transparent; }}
QFrame#planStep {{ border-radius: 12px; background: transparent; border: 1px solid transparent; }}
QFrame#planStep[state="on"] {{ background: #ffffff; border-color: #cfe6dc; }}
QFrame#planStep[state="done"] QLabel {{ color: #8a92a3; }}
QLabel#planDot {{ border-radius: 10px; background: #e8edf3; color: #4d5568; font-weight: 600; }}
QLabel#planDot[state="on"] {{ background: {ACCENT}; color: #ffffff; }}
QLabel#planDot[state="done"] {{ background: #cfe6dc; color: {ACCENT}; }}
QLabel#planStepTitle {{ font-weight: 600; }}
QFrame#printSettings {{ border-top: 1px solid #e4e8ef; }}
QLabel#stepTitle {{ font-size: 17pt; font-weight: 600; }}
QLabel#stepText {{ color: #4d5568; font-size: 10.5pt; }}
QDialog#welcome {{ background: #f7f8fb; }}
QLabel#welcomeTitle {{ font-size: 17pt; font-weight: 600; }}
QFrame#welcomeStep {{ background: #ffffff; border: 1px solid #e3e6ee; border-radius: 12px; }}
QFrame#welcomeDemo {{ background: #e9f4ee; border: 1px solid #cfe6dc; border-radius: 12px; }}
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


def step_pixmap(n: int, state: str, size: int = 30) -> QPixmap:
    """Кружок с номером шага на полосе слева: пройденный — зелёный с галочкой."""
    ratio = 2
    pm = QPixmap(size * ratio, size * ratio)
    pm.fill(Qt.transparent)
    pm.setDevicePixelRatio(ratio)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(1.5, 1.5, size - 3, size - 3)
    color = QColor("#ffffff") if state == "on" else QColor("#aab3c5")
    if state == "done":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1f8a62"))
        p.drawEllipse(r)
        p.drawPixmap(QRectF(7, 7, size - 14, size - 14).toRect(), icons.pixmap("check", "#ffffff", size - 14))
    else:
        p.setPen(QPen(color, 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(r)
        f = QFont()
        f.setPixelSize(13)
        f.setBold(True)
        p.setFont(f)
        p.drawText(r, Qt.AlignCenter, str(n))
    p.end()
    return pm


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


class Section(QWidget):
    """Раздел боковой панели: заголовок с кратким итогом справа,
    по щелчку плавно сворачивается."""

    toggled = Signal(bool)

    def __init__(self, title: str, icon: str, opened: bool = True):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.head = QPushButton(objectName="sectionHead")
        self.head.setCheckable(True)
        self.head.setChecked(opened)
        self.head.setIcon(icons.icon(icon, ACCENT))
        self.head.setText(title)
        hl = QHBoxLayout(self.head)
        hl.setContentsMargins(0, 0, 10, 0)
        hl.addStretch(1)
        self.summary = QLabel(objectName="sectionSummary")
        self.summary.setAttribute(Qt.WA_TransparentForMouseEvents)
        hl.addWidget(self.summary)
        self.arrow = QLabel()
        self.arrow.setAttribute(Qt.WA_TransparentForMouseEvents)
        hl.addWidget(self.arrow)
        lay.addWidget(self.head)
        self.body = QWidget(objectName="sectionBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(10, 4, 8, 14)
        self.body_layout.setSpacing(6)
        lay.addWidget(self.body)
        self.anim = QPropertyAnimation(self.body, b"maximumHeight", self)
        self.anim.setDuration(180)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.finished.connect(self._anim_done)
        self.head.toggled.connect(self.set_open)
        self.body.setVisible(opened)
        self._set_arrow(opened)

    def _set_arrow(self, on: bool):
        self.arrow.setPixmap(icons.pixmap("chevron" if on else "right", "#6b7385", 12))
        self.summary.setVisible(not on)

    def is_open(self) -> bool:
        return self.head.isChecked()

    def set_summary(self, text: str):
        self.summary.setText(text)

    def set_open(self, on: bool):
        self.head.blockSignals(True)
        self.head.setChecked(on)
        self.head.blockSignals(False)
        self._set_arrow(on)
        full = self.body.sizeHint().height()
        self.anim.stop()
        if on:
            self.body.setMaximumHeight(0)
            self.body.show()
            self.anim.setStartValue(0)
            self.anim.setEndValue(full)
        else:
            self.anim.setStartValue(self.body.height())
            self.anim.setEndValue(0)
        self.anim.start()
        self.toggled.emit(on)

    def _anim_done(self):
        if self.head.isChecked():
            self.body.setMaximumHeight(16777215)
        else:
            self.body.hide()


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


SLIDER_HELP = {
    "Аккуратность": (
        "Насколько ровно пишет «рука».\n\n"
        "Левее — буквы стоят ровнее, строка почти не волнится, наклон меняется мало, как при старательном письме.\n"
        "Правее — строка гуляет сильнее, буквы разного размера и наклона, как при быстром конспекте на паре.\n\n"
        "Середина — как в ваших образцах."),
    "Рука устаёт к концу": (
        "Как у живого человека к концу длинного конспекта: почерк постепенно становится крупнее и "
        "размашистее, буквы небрежнее, строки чуть уползают вверх.\n\n"
        "0 — первая и последняя страница написаны одинаково. Заметно на конспектах от 3–4 страниц."),
    "Исправления (зачёркнутые описки)": (
        "Изредка перед словом программа пишет описку (лишнюю или переставленную букву, недописанное слово) "
        "и зачёркивает её одной-двумя линиями, а дальше пишет правильно.\n\n"
        "0 — без исправлений. «Часто» — несколько на страницу. Так текст меньше похож на распечатку."),
    "Живой левый край": (
        "Человек не начинает каждую строку в одной и той же клетке: начало строк немного гуляет и "
        "медленно плывёт по странице, изредка строка начинается правее.\n\n"
        "«Ровно» — все строки от одной линии. За красное поле текст не заходит при любом положении."),
    "Гладкость линии": (
        "Шариковая ручка пишет с пропусками (шарик не провернулся) и зернистой линией, и сканер это "
        "сохраняет.\n\n"
        "Поэтому буквы обводятся гладким контуром и печатаются сплошной линией с чистым краем, как "
        "шрифт. Правее — изгибы плавнее. Толщина линии не меняется.\n"
        "0 — буквы точно как в скане, с зерном ручки. Ваши образцы при этом не меняются, только то, "
        "как они печатаются."),
    "Толщина линии": (
        "Насколько толстой линией пишутся буквы, соединения и подчёркивания.\n\n"
        "Посередине — как на скане вашей ручкой. Влево — тоньше (примерно на треть), вправо — толще, до двух раз. "
        "Меняется плавно и сразу видно в предпросмотре. Образцы при этом не меняются."),
    "Размер": (
        "Во сколько раз крупнее или мельче писать эту букву в тексте. 100% — как в образцах.\n\n"
        "Пригодится, если какая-то буква в бланке вышла заметно больше или меньше остальных. "
        "Размер отдельного варианта меняется в процентах под ним."),
}


def slider_weight(v: int) -> float:
    """Положение ползунка толщины (−10…10) → множитель толщины линии.
    Посередине 1 (как на скане), вправо до двух раз толще, влево до 0,6:
    тоньше тонкие штрихи начинают рваться."""
    return 2.0 ** (v / 10) if v >= 0 else 2.0 ** (0.07 * v)


def help_button(title: str, parent: QWidget | None = None) -> QToolButton:
    """Кнопка «?»: по щелчку объясняет, для чего настройка."""
    b = QToolButton(parent, objectName="help")
    b.setText("?")
    b.setCursor(Qt.PointingHandCursor)
    b.setToolTip("Что это?")
    b.setProperty("help_for", title)
    b.clicked.connect(lambda: QMessageBox.information(b.window(), title, SLIDER_HELP[title]))
    return b


def slider_title(title: str) -> QHBoxLayout:
    """Подпись ползунка с кнопкой «?» справа от неё."""
    row = QHBoxLayout()
    row.setSpacing(6)
    row.addWidget(QLabel(title))
    row.addWidget(help_button(title))
    row.addStretch(1)
    return row


def sample_pixmap(prof: Profile, s: GlyphSample, height: int = 90) -> QPixmap:
    return alpha_pixmap(prof.image(s), height)


def alpha_pixmap(a: np.ndarray, height: int = 90) -> QPixmap:
    gray = np.ascontiguousarray(255 - np.clip(a * 255, 0, 255).astype(np.uint8))
    im = QImage(gray.data, gray.shape[1], gray.shape[0], gray.strides[0], QImage.Format_Grayscale8).copy()
    return QPixmap.fromImage(im).scaledToHeight(height, Qt.SmoothTransformation)


class ImportPreviewDialog(QDialog):
    """Вырезанные из сканов буквы перед сохранением в почерк.

    Буквы, которые упираются в край клетки (вылезли за уголки и, скорее
    всего, обрезаны), сразу не отмечены. Щелчок по букве — брать её или нет.
    Не взятые сохраняются отключёнными, их можно вернуть в «Редакторе букв»."""

    COLUMNS = 6

    def __init__(self, parent, preview: sv.ImportPreview):
        super().__init__(parent)
        self.preview = preview
        self.keep = [not e.clipped for e in preview.samples]
        self.setWindowTitle(f"Проверка букв — {preview.profile_name}")
        self.resize(900, 680)
        lay = QVBoxLayout(self)
        n_clipped = sum(1 for e in preview.samples if e.clipped)
        head = f"Вырезано букв и слов: {len(preview.samples)}. Щелчок по образцу — не брать его, второй щелчок — взять."
        if n_clipped:
            head += (f" {n_clipped} упираются в край клетки, похоже, обрезаны; они в красной рамке и "
                     "не будут взяты, если их не отметить.")
        lay.addWidget(QLabel(head, objectName="hint", wordWrap=True))
        self.only_bad = QCheckBox("Показать только обрезанные")
        self.only_bad.setVisible(bool(n_clipped))
        self.only_bad.toggled.connect(self._filter)
        lay.addWidget(self.only_bad)

        box = QWidget()
        self.grid = QGridLayout(box)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.tiles: list[QWidget] = []
        for i, e in enumerate(preview.samples):
            tile = QWidget()
            tl = QVBoxLayout(tile)
            tl.setContentsMargins(0, 0, 0, 0)
            tl.setSpacing(2)
            b = QToolButton(objectName="sample")
            b.setCheckable(True)
            b.setChecked(self.keep[i])
            pm = alpha_pixmap(e.alpha, 56)
            if pm.width() > 110:
                pm = pm.scaledToWidth(110, Qt.SmoothTransformation)
            b.setIcon(pm)
            b.setIconSize(pm.size())
            b.setToolTip(("Упирается в край клетки — возможно, обрезана. " if e.clipped else "") + e.source)
            b.toggled.connect(lambda on, k=i: self._toggle(k, on))
            tl.addWidget(b, 0, Qt.AlignHCenter)
            tl.addWidget(QLabel(e.cell.request.text, objectName="hint", alignment=Qt.AlignHCenter))
            self.tiles.append(tile)
        self._filter()
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(box)
        lay.addWidget(area, 1)

        self.count_label = QLabel(objectName="hint")
        lay.addWidget(self.count_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Сохранить в почерк")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._update_count()

    def _toggle(self, k: int, on: bool):
        self.keep[k] = on
        self._update_count()

    def _update_count(self):
        off = self.keep.count(False)
        self.count_label.setText(f"Не будут взяты: {off}" if off else "Будут взяты все")

    def _filter(self, *_):
        while self.grid.count():
            self.grid.takeAt(0)
        shown = [t for t, e in zip(self.tiles, self.preview.samples) if e.clipped or not self.only_bad.isChecked()]
        for k, t in enumerate(shown):
            self.grid.addWidget(t, k // self.COLUMNS, k % self.COLUMNS)
        for t in self.tiles:
            t.setVisible(t in shown)


class SamplesDialog(QDialog):
    """Редактор букв: все варианты одного символа и их размеры.

    Щелчок по образцу отключает его (рамка становится красной пунктирной) или
    возвращает. «Удалить» убирает неудачный вариант совсем. Ползунки меняют
    размер и высоту буквы в строке, у каждого варианта есть свой размер.
    Снизу — строка, написанная с учётом всех правок. Всё применяется только
    по «Сохранить»."""

    PREVIEW_DPI = 150

    def __init__(self, parent, prof: Profile, start: str = ""):
        super().__init__(parent)
        self.prof = prof
        self.enabled = {s.id: s.enabled for s in prof.samples}
        self.deleted: set[str] = set()
        self.adjust = {k: dict(v) for k, v in prof.letter_adjust.items()}
        self.vscale = dict(prof.variant_scale)
        self._saved_state = ({s.id: s.enabled for s in prof.samples}, {k: dict(v) for k, v in self.adjust.items()},
                             dict(self.vscale))
        self.suspect = {s.id for s in prof.find_crossed()}
        self.setWindowTitle(f"Редактор букв — {prof.name}")
        self.resize(820, 680)
        lay = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Буква:"))
        self.text_box = QComboBox()
        row.addWidget(self.text_box, 1)
        self.crossed_btn = QPushButton("Отключить похожие на зачёркнутые")
        self.crossed_btn.clicked.connect(self._disable_suspects)
        row.addWidget(self.crossed_btn)
        lay.addLayout(row)
        lay.addWidget(QLabel("Щелчок по образцу отключает его (программа его не берёт), второй щелчок "
                             "возвращает. «Удалить» убирает неудачный вариант совсем. Процент под образцом — "
                             "размер именно этого варианта.", objectName="hint", wordWrap=True))

        self.grid_box = QWidget()
        self.grid = QGridLayout(self.grid_box)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(self.grid_box)
        lay.addWidget(area, 1)
        drow = QHBoxLayout()
        self.deleted_label = QLabel(objectName="hint")
        self.undelete_btn = QPushButton("Вернуть удалённые")
        self.undelete_btn.clicked.connect(self._undelete)
        drow.addWidget(self.deleted_label, 1)
        drow.addWidget(self.undelete_btn)
        lay.addLayout(drow)

        size_box = QFrame(objectName="card")
        sg = QGridLayout(size_box)
        sg.setContentsMargins(12, 8, 12, 8)
        self.size_title = QLabel(objectName="cardTitle")
        sg.addWidget(self.size_title, 0, 0, 1, 3)
        sg.addLayout(slider_title("Размер"), 1, 0)
        self.scale_slider = QSlider(Qt.Horizontal)
        lo, hi = (round(100 * v) for v in SCALE_LIMITS)
        self.scale_slider.setRange(lo, hi)
        self.scale_slider.setToolTip("Во сколько раз крупнее или мельче писать эту букву, 100% — как в образцах")
        sg.addWidget(self.scale_slider, 1, 1)
        self.scale_label = QLabel()
        self.scale_label.setMinimumWidth(48)
        sg.addWidget(self.scale_label, 1, 2)
        sg.addWidget(QLabel("Выше / ниже"), 2, 0)
        self.raise_spin = QDoubleSpinBox()
        self.raise_spin.setRange(*RAISE_LIMITS_MM)
        self.raise_spin.setSingleStep(0.1)
        self.raise_spin.setDecimals(1)
        self.raise_spin.setSuffix(" мм")
        self.raise_spin.setToolTip("Плюс — буква стоит выше строки, минус — ниже. Для букв, которые «прыгают»")
        sg.addWidget(self.raise_spin, 2, 1)
        reset = QPushButton("Сбросить")
        reset.setToolTip("Вернуть размер и высоту буквы и всех её вариантов как в образцах")
        reset.clicked.connect(self._reset_letter)
        sg.addWidget(reset, 2, 2)
        lay.addWidget(size_box)

        prow = QHBoxLayout()
        prow.addWidget(QLabel("Проверка:"))
        self.check_edit = QLineEdit()
        self.check_edit.setToolTip("Слова, на которых видно, как буква смотрится в строке. Можно написать свои")
        prow.addWidget(self.check_edit, 1)
        lay.addLayout(prow)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(110)
        self.preview.setStyleSheet("background: #ffffff; border: 1px solid #e3e6ee; border-radius: 8px;")
        lay.addWidget(self.preview)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(150)
        self.preview_timer.timeout.connect(self._render_preview)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self._fill_texts()
        first_suspect = next((s.text for s in prof.samples if s.id in self.suspect), "")
        i = self.text_box.findData(start or first_suspect)
        self.text_box.setCurrentIndex(max(i, 0))
        self.text_box.currentIndexChanged.connect(self._show)
        self.scale_slider.valueChanged.connect(self._letter_changed)
        self.raise_spin.valueChanged.connect(self._letter_changed)
        self.check_edit.textEdited.connect(lambda *_: self.preview_timer.start())
        self._show()

    # ---------- список букв ----------

    def _fill_texts(self):
        current = self.text_box.currentData()
        texts = sorted({s.text for s in self.prof.samples}, key=lambda t: (len(t), t.lower(), t))
        self.text_box.blockSignals(True)
        self.text_box.clear()
        for t in texts:
            ids = [s.id for s in self.prof.samples if s.text == t and s.id not in self.deleted]
            on = sum(1 for sid in ids if self.enabled[sid])
            mark = "  • изменена" if t in self.adjust or any(sid in self.vscale for sid in ids) else ""
            self.text_box.addItem(f"{t}   ({on} из {len(ids)}){mark}", t)
        if current is not None:
            self.text_box.setCurrentIndex(max(0, self.text_box.findData(current)))
        self.text_box.blockSignals(False)

    def current_text(self) -> str:
        return self.text_box.currentData() or ""

    def buttons_for_current(self) -> list[QToolButton]:
        return [w for w in self.grid_box.findChildren(QToolButton) if w.property("sample_id")]

    def _show(self, *_):
        while self.grid.count():
            old = self.grid.takeAt(0).widget()
            old.setParent(None)
            old.deleteLater()
        text = self.current_text()
        found = [s for s in self.prof.samples if s.text == text and s.id not in self.deleted]
        for k, s in enumerate(found):
            tile = QWidget()
            tl = QVBoxLayout(tile)
            tl.setContentsMargins(0, 0, 0, 0)
            tl.setSpacing(3)
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
            b.toggled.connect(lambda on, sid=s.id: self._toggle(sid, on))
            tl.addWidget(b, 0, Qt.AlignHCenter)
            low = QHBoxLayout()
            low.setSpacing(3)
            sp = QSpinBox()
            sp.setRange(*(round(100 * v) for v in SCALE_LIMITS))
            sp.setSingleStep(5)
            sp.setSuffix("%")
            sp.setValue(round(100 * self.vscale.get(s.id, 1.0)))
            sp.setToolTip("Размер этого варианта")
            sp.setProperty("scale_for", s.id)
            sp.valueChanged.connect(lambda v, sid=s.id: self._variant_scale(sid, v))
            dl = QToolButton()
            dl.setText("Удалить")
            dl.setToolTip("Удалить этот вариант из почерка (после «Сохранить»)")
            dl.setProperty("delete_for", s.id)
            dl.clicked.connect(lambda _=False, sid=s.id: self.delete_sample(sid))
            low.addWidget(sp)
            low.addWidget(dl)
            tl.addLayout(low)
            self.grid.addWidget(tile, k // 4, k % 4)
        a = self.adjust.get(text, {})
        for w in (self.scale_slider, self.raise_spin):
            w.blockSignals(True)
        self.scale_slider.setValue(round(100 * a.get("scale", 1.0)))
        self.raise_spin.setValue(a.get("raise_mm", 0.0))
        for w in (self.scale_slider, self.raise_spin):
            w.blockSignals(False)
        self.scale_label.setText(f"{self.scale_slider.value()}%")
        self.size_title.setText(f"Вся буква «{text}» в тексте")
        n = len(self.deleted)
        self.deleted_label.setText(f"Будет удалено вариантов: {n}" if n else "")
        self.undelete_btn.setVisible(bool(n))
        self.check_edit.setText(self._check_words(text))
        self.preview_timer.start()

    @staticmethod
    def _check_words(text: str) -> str:
        if len(text) > 1 or not text.isalpha():
            return f"было {text} это"
        if text.isupper():
            return f"{text}ня и {text}ом"
        return f"н{text}м {text}{text}о и {text}"

    # ---------- правки ----------

    def _toggle(self, sid: str, on: bool):
        self.enabled[sid] = on
        self.preview_timer.start()

    def _variant_scale(self, sid: str, percent: int):
        if percent == 100:
            self.vscale.pop(sid, None)
        else:
            self.vscale[sid] = percent / 100
        self.preview_timer.start()

    def _letter_changed(self, *_):
        text = self.current_text()
        a = {"scale": self.scale_slider.value() / 100, "raise_mm": round(self.raise_spin.value(), 2)}
        a = {k: v for k, v in a.items() if v != {"scale": 1.0, "raise_mm": 0.0}[k]}
        if a:
            self.adjust[text] = a
        else:
            self.adjust.pop(text, None)
        self.scale_label.setText(f"{self.scale_slider.value()}%")
        self.preview_timer.start()

    def _reset_letter(self):
        text = self.current_text()
        self.adjust.pop(text, None)
        for s in self.prof.samples:
            if s.text == text:
                self.vscale.pop(s.id, None)
        self._fill_texts()
        self._show()

    def delete_sample(self, sid: str):
        self.deleted.add(sid)
        self._fill_texts()
        self._show()

    def _undelete(self):
        self.deleted.clear()
        self._fill_texts()
        self._show()

    def _disable_suspects(self):
        for sid in self.suspect:
            self.enabled[sid] = False
        self._show()
        n = len(self.suspect)
        QMessageBox.information(self, APP_NAME, f"Отключено образцов: {n}. Нажмите «Сохранить»."
                                if n else "Зачёркнутых образцов не найдено.")

    def changed(self) -> int:
        en, adj, vs = self._saved_state
        n = sum(1 for sid, on in self.enabled.items() if sid not in self.deleted and en.get(sid) != on)
        n += len(self.deleted)
        n += sum(1 for k in set(adj) | set(self.adjust) if adj.get(k) != self.adjust.get(k))
        n += sum(1 for k in set(vs) | set(self.vscale) if vs.get(k) != self.vscale.get(k))
        return n

    def _apply(self):
        """Переносит правки в профиль (удалённые пока только отключены)."""
        for s in self.prof.samples:
            s.enabled = self.enabled[s.id] and s.id not in self.deleted
        self.prof.letter_adjust = {k: dict(v) for k, v in self.adjust.items()}
        self.prof.variant_scale = dict(self.vscale)

    def _restore(self):
        en, adj, vs = self._saved_state
        for s in self.prof.samples:
            s.enabled = en[s.id]
        self.prof.letter_adjust = {k: dict(v) for k, v in adj.items()}
        self.prof.variant_scale = dict(vs)

    def _render_preview(self):
        words = self.check_edit.text().strip()
        if not words:
            self.preview.clear()
            return
        self._apply()
        try:
            settings = LayoutSettings(page_size_mm=(120.0, 19.0), paper="grid", dpi=self.PREVIEW_DPI, margin_line=False,
                                    margin_left_mm=4.0, margin_right_mm=4.0, margin_top_mm=0.0, indent_mm=0.0,
                                    seed=5, live_edge=0.0, paper_texture=False)
            layout = typeset(words, self.prof, settings)
            im = render_page(layout.pages[0], self.prof, settings)
        finally:
            self._restore()
        pm = QPixmap.fromImage(to_qimage(im))
        self.preview.setPixmap(pm.scaledToWidth(min(pm.width() * 2, 760), Qt.SmoothTransformation))

    def reject(self):
        self._restore()
        super().reject()

    def _save(self):
        self._apply()
        for sid in self.deleted:
            self.prof.remove(sid, measure=False)
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


WELCOME_STEPS = [
    ("Распечатайте бланк",
     "5 листов A4 с клетками для букв. Печатайте в реальном размере (масштаб 100%)."),
    ("Заполните ручкой",
     "Той ручкой, которой пишете конспекты. В каждую клетку одну букву или слово, буквы ставьте на "
     "пунктир. Пишите как обычно, не красивее: программа повторит именно ваш почерк."),
    ("Отсканируйте или сфотографируйте",
     "Подойдёт телефон: ровный свет, лист целиком, видны все четыре чёрных квадрата по углам."),
    ("Импортируйте сканы",
     "Укажите фото или PDF и назовите почерк, например «Мой почерк». Импорт занимает около минуты, "
     "потом можно проверить вырезанные буквы."),
]


class WelcomeDialog(QDialog):
    """Подсказка при первом запуске: как получить свой почерк."""

    def __init__(self, parent: "MainWindow"):
        super().__init__(parent)
        self.main = parent
        self.setObjectName("welcome")
        self.setWindowTitle("С чего начать")
        self.setFixedWidth(680)
        lay = QVBoxLayout(self)
        lay.setSizeConstraint(QVBoxLayout.SetMinimumSize)
        lay.setContentsMargins(26, 22, 26, 18)
        lay.setSpacing(12)
        lay.addWidget(QLabel("Программа пишет вашим почерком", objectName="welcomeTitle"))
        sub = QLabel("Для этого ей нужны образцы ваших букв. Это делается один раз, "
                     "примерно за полчаса, и дальше любой текст пишется вашей рукой.", objectName="stepText")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        self.step_buttons: list[QPushButton] = []
        for i, (title, text) in enumerate(WELCOME_STEPS):
            card = QFrame(objectName="welcomeStep")
            cl = QHBoxLayout(card)
            cl.setContentsMargins(14, 12, 14, 12)
            cl.setSpacing(14)
            dot = QLabel(str(i + 1), objectName="planDot")
            dot.setProperty("state", "on")
            dot.setFixedSize(28, 28)
            dot.setAlignment(Qt.AlignCenter)
            cl.addWidget(dot, 0, Qt.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(3)
            col.addWidget(QLabel(title, objectName="planStepTitle"))
            lab = QLabel(text, objectName="hint")
            lab.setWordWrap(True)
            lab.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
            col.addWidget(lab)
            cl.addLayout(col, 1)
            if i == 0:
                b = QPushButton("Сохранить бланк…")
                b.clicked.connect(lambda: self.main.save_template("main"))
            elif i == 3:
                b = QPushButton("Импорт сканов…", objectName="primary")
                b.clicked.connect(self._import)
            else:
                b = None
            if b is not None:
                cl.addWidget(b, 0, Qt.AlignVCenter)
                self.step_buttons.append(b)
            lay.addWidget(card)
        demo = QFrame(objectName="welcomeDemo")
        dl = QHBoxLayout(demo)
        dl.setContentsMargins(14, 12, 14, 12)
        dtext = QLabel("<b>Хотите сначала посмотреть?</b><br>Пример почерка (рукописный шрифт) и пример "
                       "конспекта: можно сразу попробовать вид, настройки и печать.")
        dtext.setWordWrap(True)
        dtext.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        dl.addWidget(dtext, 1)
        self.demo_btn = QPushButton("Попробовать на примере")
        self.demo_btn.clicked.connect(self._demo)
        dl.addWidget(self.demo_btn, 0, Qt.AlignVCenter)
        lay.addWidget(demo)
        row = QHBoxLayout()
        self.show_box = QCheckBox("Показывать при запуске, пока нет своего почерка")
        self.show_box.setChecked(self.main.qs.value("show_welcome", "true") in (True, "true"))
        self.show_box.toggled.connect(lambda on: self.main.qs.setValue("show_welcome", on))
        row.addWidget(self.show_box)
        row.addStretch(1)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)

    def _import(self):
        self.accept()
        self.main.import_scans()

    def _demo(self):
        self.accept()
        self.main.try_demo()


class MainWindow(QMainWindow):
    def __init__(self, profiles_dir: str | Path | None = None, settings: QSettings | None = None,
                 blank: bool = False):
        super().__init__()
        self.blank = blank  # второе окно: начинается с пустого текста и не затирает текст главного
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 820)
        self.qs = settings or QSettings("Konspekt", "Konspekt")
        self._update_failed = False  # прошлое обновление не встало: не предлагаем его снова при запуске
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

        # панели настроек справа на шагах «Текст» и «Вид»
        self.sections: dict[str, Section] = {}

        def panel():
            box = QWidget(objectName="sidebarBox")
            lay = QVBoxLayout(box)
            lay.setContentsMargins(10, 8, 10, 14)
            lay.setSpacing(2)
            return box, lay

        text_side, text_side_l = panel()
        view_side, view_side_l = panel()

        def section(title, icon, target):
            sec = Section(title, icon, self.qs.value(f"open_{icon}", "true") in (True, "true"))
            sec.toggled.connect(lambda on, k=icon: self.qs.setValue(f"open_{k}", on))
            target.addWidget(sec)
            self.sections[title] = sec
            return sec.body_layout

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

        sl = section("Почерк", "pen", text_side_l)
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
        samples = QPushButton("Редактор букв…")
        samples.setToolTip("Варианты каждой буквы: удалить или отключить неудачные, поменять размер "
                           "и высоту буквы в строке (Ctrl+B)")
        samples.clicked.connect(self.edit_samples)
        draw = QPushButton("Нарисовать…")
        draw.setToolTip("Дописать варианты букв мышью или на тачпаде, удалить и переделать неудачные (Ctrl+D)")
        draw.clicked.connect(self.draw_letters)
        row2.addWidget(samples, 1)
        row2.addWidget(draw, 1)
        sl.addLayout(row2)
        self.ink_box = QComboBox()
        for key, title in sv.INKS:
            self.ink_box.addItem(title, key)
        self.ink_box.setToolTip("Каким цветом печатать почерк, чем бы ни были написаны образцы")
        field("Цвет ручки", self.ink_box)

        sl = section("Бумага", "paper", view_side_l)
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

        sl = section("Письмо", "lines", view_side_l)
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(1, 9999)
        self.seed_spin.setPrefix("Вариант ")
        self.seed_spin.setToolTip("Другое число — другое оформление того же текста")
        sl.addWidget(self.seed_spin)
        self.neat_slider = QSlider(Qt.Horizontal)
        self.neat_slider.setRange(5, 15)  # десятые: 0.5 … 1.5
        self.neat_slider.setToolTip("Насколько небрежно пишется текст")
        sl.addLayout(slider_title("Аккуратность"))
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
        sl.addLayout(slider_title("Рука устаёт к концу"))
        sl.addWidget(self.tired_slider)
        self.fix_slider = QSlider(Qt.Horizontal)
        self.fix_slider.setRange(0, 10)
        self.fix_slider.setToolTip("Изредка перед словом пишется описка и зачёркивается. 0 — без исправлений")
        sl.addLayout(slider_title("Исправления (зачёркнутые описки)"))
        sl.addWidget(self.fix_slider)
        fends = QHBoxLayout()
        fends.addWidget(QLabel("нет", objectName="hint"))
        fends.addStretch(1)
        fends.addWidget(QLabel("часто", objectName="hint"))
        sl.addLayout(fends)
        self.edge_slider = QSlider(Qt.Horizontal)
        self.edge_slider.setRange(0, 10)
        self.edge_slider.setToolTip("Человек не начинает каждую строку в одной и той же клетке: начало строк "
                                    "немного гуляет и плывёт по странице. 0 — почти ровный край")
        sl.addLayout(slider_title("Живой левый край"))
        sl.addWidget(self.edge_slider)
        eends = QHBoxLayout()
        eends.addWidget(QLabel("ровно", objectName="hint"))
        eends.addStretch(1)
        eends.addWidget(QLabel("свободно", objectName="hint"))
        sl.addLayout(eends)
        self.smooth_slider = QSlider(Qt.Horizontal)
        self.smooth_slider.setRange(0, 10)
        self.smooth_slider.setToolTip("Буквы печатаются сплошной гладкой линией, как шрифт. Чем правее, тем "
                                      "плавнее изгибы. 0 — точно как в скане, с зерном ручки")
        sl.addLayout(slider_title("Гладкость линии"))
        sl.addWidget(self.smooth_slider)
        smends = QHBoxLayout()
        smends.addWidget(QLabel("как в скане", objectName="hint"))
        smends.addStretch(1)
        smends.addWidget(QLabel("гладко", objectName="hint"))
        sl.addLayout(smends)
        self.weight_slider = QSlider(Qt.Horizontal)
        self.weight_slider.setRange(-10, 10)  # см. slider_weight
        self.weight_slider.setToolTip("Толщина линии букв. Посередине — как на скане")
        sl.addLayout(slider_title("Толщина линии"))
        sl.addWidget(self.weight_slider)
        wends = QHBoxLayout()
        wends.addWidget(QLabel("тоньше", objectName="hint"))
        wends.addStretch(1)
        wends.addWidget(QLabel("как на скане", objectName="hint"))
        wends.addStretch(1)
        wends.addWidget(QLabel("толще", objectName="hint"))
        sl.addLayout(wends)
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

        print_settings = QWidget()
        sl = QVBoxLayout(print_settings)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)
        sl.addWidget(QLabel("НАСТРОЙКИ ПЕЧАТИ", objectName="section"))
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
        text_side_l.addStretch(1)
        view_side_l.addStretch(1)

        def side_scroll(box):
            sc = QScrollArea(objectName="sidebar")
            sc.setWidget(box)
            sc.setWidgetResizable(True)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            fr = QFrame(objectName="sidebarFrame")
            fl = QVBoxLayout(fr)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.addWidget(sc)
            fr.setFixedWidth(300)
            return fr

        def page_head(title, subtitle_label, buttons):
            head = QFrame(objectName="header")
            hl = QHBoxLayout(head)
            hl.setContentsMargins(22, 10, 18, 10)
            hl.setSpacing(10)
            titles = QVBoxLayout()
            titles.setSpacing(0)
            titles.addWidget(QLabel(title, objectName="title"))
            titles.addWidget(subtitle_label)
            hl.addLayout(titles)
            hl.addStretch(1)
            for b in buttons:
                b.setMinimumHeight(34)
                hl.addWidget(b)
            return head

        def page(head, *widgets):
            w = QWidget(objectName="page")
            pl = QVBoxLayout(w)
            pl.setContentsMargins(0, 0, 0, 0)
            pl.setSpacing(0)
            pl.addWidget(head)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(0)
            for wd, stretch in widgets:
                row.addWidget(wd, stretch)
            pl.addLayout(row, 1)
            return w

        # текст
        text_card = QFrame(objectName="card")
        tl = QVBoxLayout(text_card)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        top_box = QFrame(objectName="cardHead")
        top = QHBoxLayout(top_box)
        top.setContentsMargins(14, 8, 10, 8)
        top.setSpacing(6)
        top.addStretch(1)
        insert_btn = QPushButton("Вставить ▾", objectName="small")
        insert_btn.setToolTip("Дата, тема, вопрос с номером, подчёркивание, рамка, стрелка, степень")
        self.insert_menu = QMenu(insert_btn)
        insert_btn.setMenu(self.insert_menu)
        top.addWidget(insert_btn)
        dictate_btn = QToolButton(objectName="iconButton")
        dictate_btn.setIcon(icons.icon("mic"))
        dictate_btn.setToolTip("Диктовать: голосовой ввод Windows (Win+H), текст появится в поле")
        dictate_btn.clicked.connect(self.dictate)
        top.addWidget(dictate_btn)
        open_btn = QToolButton(objectName="iconButton")
        open_btn.setIcon(icons.icon("folder"))
        open_btn.setToolTip("Открыть файл: текст (.txt) или документ Word (.docx)")
        open_btn.clicked.connect(self.open_text)
        top.addWidget(open_btn)
        tl.addWidget(top_box)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(PLACEHOLDER)
        tl.addWidget(self.text_edit, 1)
        self.chars_label = QLabel(objectName="cardFoot")
        tl.addWidget(self.chars_label)

        # страницы
        preview = QFrame(objectName="card")
        pl = QVBoxLayout(preview)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        self.pages = PagesView(loupe=True)
        pl.addWidget(self.pages, 1)
        self.missing_label = QLabel(objectName="missing")
        self.missing_label.setWordWrap(True)
        self.missing_label.hide()
        pl.addWidget(self.missing_label)

        def padded(w):
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(16, 16, 16, 16)
            bl.addWidget(w)
            return box

        # шаг 1: текст
        to_view = QPushButton("Дальше: вид", objectName="primary")
        to_view.setIcon(icons.icon("right", "#ffffff"))
        to_view.setLayoutDirection(Qt.RightToLeft)
        to_view.clicked.connect(lambda: self.go_step(1))
        self.text_sub = QLabel(objectName="subtitle")
        text_page = page(page_head("Текст конспекта", self.text_sub, [to_view]),
                         (padded(text_card), 1), (side_scroll(text_side), 0))

        # шаг 2: вид
        self.regen_btn = QPushButton("Другой вариант")
        self.regen_btn.setIcon(icons.icon("refresh"))
        self.regen_btn.setToolTip("Тот же текст, но написанный по-другому (Ctrl+R)")
        self.regen_btn.clicked.connect(self.next_variant)
        self.pdf_btn = QPushButton("Сохранить PDF")
        self.pdf_btn.setIcon(icons.icon("download"))
        self.pdf_btn.setToolTip("Ctrl+S")
        self.pdf_btn.clicked.connect(self.save_pdf)
        self.print_btn = QPushButton("Дальше: печать", objectName="primary")
        self.print_btn.setIcon(icons.icon("right", "#ffffff"))
        self.print_btn.setLayoutDirection(Qt.RightToLeft)
        self.print_btn.clicked.connect(lambda: self.go_step(2))
        self.pages_label = QLabel(objectName="subtitle")
        view_page = page(page_head("Как будет выглядеть", self.pages_label,
                                   [self.regen_btn, self.pdf_btn, self.print_btn]),
                         (padded(preview), 1), (side_scroll(view_side), 0))

        # шаг 3: печать
        self.print_page = PrintPage(print_settings, self.qs.value("face_up", "true") in (True, "true"))
        self.print_page.start_requested.connect(self.print_pages)
        self.print_page.back_requested.connect(lambda: self.go_step(1))
        self.print_page.finished.connect(self._print_finished)
        self.print_page.face_box.currentIndexChanged.connect(
            lambda *_: self.qs.setValue("face_up", self.print_page.face_up))
        self.print_sub = QLabel(objectName="subtitle")
        print_page = page(page_head("Печать", self.print_sub, []), (self.print_page, 1))

        self.stack = QStackedWidget()
        for w in (text_page, view_page, print_page):
            self.stack.addWidget(w)

        # полоса шагов слева
        rail = QFrame(objectName="rail")
        rail.setFixedWidth(96)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(10, 16, 10, 16)
        rl.setSpacing(8)
        logo = QLabel(objectName="logo")
        logo.setFixedSize(40, 40)
        logo.setAlignment(Qt.AlignCenter)
        logo.setPixmap(icons.pixmap("pen", "#ffffff", 20))
        logo.setToolTip(APP_NAME)
        rl.addWidget(logo, 0, Qt.AlignHCenter)
        rl.addSpacing(16)
        self.step_buttons: list[QToolButton] = []
        for i, title in enumerate(("Текст", "Вид", "Печать")):
            b = QToolButton(objectName="railButton")
            b.setText(title)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIconSize(QSize(30, 30))
            b.setFixedSize(76, 70)
            b.setCheckable(True)
            b.setToolTip(f"Шаг {i + 1}: {title.lower()} (Ctrl+{i + 1})")
            b.clicked.connect(lambda _=False, k=i: self.go_step(k))
            rl.addWidget(b, 0, Qt.AlignHCenter)
            self.step_buttons.append(b)
        rl.addStretch(1)

        body = QWidget(objectName="body")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        bl.addWidget(rail)
        bl.addWidget(self.stack, 1)
        self._step_anim = None
        self.go_step(0, animate=False)
        self.setCentralWidget(body)

        for sig in (self.paper_box.currentIndexChanged, self.page_box.currentIndexChanged, self.ink_box.currentIndexChanged,
                    self.margin_box.currentIndexChanged, self.seed_spin.valueChanged,
                    self.neat_slider.valueChanged, self.tired_slider.valueChanged, self.fix_slider.valueChanged,
                    self.edge_slider.valueChanged, self.smooth_slider.valueChanged, self.weight_slider.valueChanged,
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
        for sig in (self.profile_box.currentIndexChanged, self.page_box.currentIndexChanged,
                    self.paper_box.currentIndexChanged, self.seed_spin.valueChanged, self.neat_slider.valueChanged,
                    self.real_paper.toggled, self.spread_box.toggled):
            sig.connect(self._update_summaries)
        self._update_print_mode()

    def _update_summaries(self, *_):
        """Итог свёрнутого раздела и подпись под названием программы."""
        page = self.page_box.currentText().split(" ")
        fmt = {"notebook": "листок", "A4": "A4", "A5": "A5"}.get(self.page_box.currentData(), page[0])
        paper = self.paper_box.currentText().lower()
        neat = self.neat_slider.value()
        how = "аккуратно" if neat < 9 else "небрежно" if neat > 11 else "обычно"
        if self.real_paper.isChecked():
            pr = "двойной листок" if self.spread_box.isChecked() and self.page_box.currentData() == "notebook" \
                else "на листок"
        else:
            pr = "на чистый лист"
        name = self.profile_box.currentText() or "нет"
        for title, text in (("Почерк", name), ("Бумага", f"{fmt}, {paper}"),
                            ("Письмо", f"вариант {self.seed_spin.value()}, {how}"), ("Печать", pr)):
            if title in self.sections:
                self.sections[title].set_summary(text)
        self.text_sub.setText(f"Почерк: {name}")

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
        act(m, "Новый конспект", self.new_text, QKeySequence.New)
        act(m, "Новое окно", self.new_window, "Ctrl+Alt+N")
        m.addSeparator()
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
        act(m, "Редактор букв…", self.edit_samples, "Ctrl+B")
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
        m.addSeparator()
        act(m, "Шаг 1: текст", lambda: self.go_step(0), "Ctrl+1")
        act(m, "Шаг 2: вид", lambda: self.go_step(1), "Ctrl+2")
        act(m, "Шаг 3: печать", lambda: self.go_step(2), "Ctrl+3")

        m = self.menuBar().addMenu("Справка")
        act(m, "С чего начать…", self.show_welcome)
        act(m, "Попробовать на примере почерка", self.try_demo)
        m.addSeparator()
        act(m, "Проверить обновления…", lambda: self.check_updates(silent=False))
        act(m, "О программе", self.show_about)

    # ---------- настройки ----------

    def _restore(self):
        q = self.qs
        if not self.blank:
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
        self.edge_slider.setValue(int(q.value("live_edge10", 5)))
        self.smooth_slider.setValue(int(q.value("smooth10", 5)))
        self.weight_slider.setValue(int(q.value("weight10", 0)))
        self.ink_box.setCurrentIndex(max(0, self.ink_box.findData(q.value("ink", ""))))
        self.size_spin.setValue(float(q.value("size_mm", 0.0)))
        self.pitch_spin.setValue(float(q.value("pitch_mm", 10.0)))
        self.real_paper.setChecked(q.value("real_paper", "false") in (True, "true"))
        self.off_x.setValue(float(q.value("offset_x_mm", 0.0)))
        self.off_y.setValue(float(q.value("offset_y_mm", 0.0)))
        self.spread_box.setChecked(q.value("spread", "false") in (True, "true"))
        self.flip_back.setChecked(q.value("flip_back", "false") in (True, "true"))
        self.nested_box.setChecked(q.value("nested", "true") in (True, "true"))
        mode = q.value("view_mode", "all")
        if mode in ("page", "pair", "all"):
            self.pages.set_mode(mode)
        self._update_counter()
        self._update_summaries()

    def _save_settings(self):
        q = self.qs
        if not self.blank:
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
        q.setValue("view_mode", self.pages.mode())
        q.setValue("seed", self.seed_spin.value())
        q.setValue("neatness10", self.neat_slider.value())
        q.setValue("tiredness10", self.tired_slider.value())
        q.setValue("corrections10", self.fix_slider.value())
        q.setValue("live_edge10", self.edge_slider.value())
        q.setValue("smooth10", self.smooth_slider.value())
        q.setValue("weight10", self.weight_slider.value())
        q.setValue("ink", self.ink_box.currentData())
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
                          corrections=self.fix_slider.value() / 200, live_edge=self.edge_slider.value() / 5,
                          flip_back=self.flip_back.isChecked(), smoothness=self.smooth_slider.value() / 10,
                          ink=self.ink_box.currentData(), weight=slider_weight(self.weight_slider.value()))

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
        self._update_summaries()
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
            "Отключить их, чтобы программа их не писала? Вернуть можно в «Редакторе букв…».")
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
        self._run(sv.scan_import, (path, name, dlg.selected_files()), self._import_scanned,
                  "Импорт сканов… это может занять минуту")

    def _import_scanned(self, preview: sv.ImportPreview):
        keep = None
        if preview.samples:
            check = ImportPreviewDialog(self, preview)
            if check.exec() != QDialog.Accepted:
                return
            keep = check.keep
        self._run(sv.finish_import, (preview, keep), self._import_done, "Сохранение букв в почерк…")

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

    def own_profiles(self) -> list[tuple[str, Path]]:
        """Профили, кроме примера почерка."""
        return [p for p in sv.list_profiles(self.profiles_dir) if p[0] != sv.DEMO_NAME]

    def should_welcome(self) -> bool:
        return not self.own_profiles() and self.qs.value("show_welcome", "true") in (True, "true")

    def show_welcome(self):
        dlg = WelcomeDialog(self)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.open()
        return dlg

    def try_demo(self):
        """Создаёт (если ещё нет) пример почерка и открывает его с примером конспекта."""
        def done(path):
            self.reload_profiles(sv.DEMO_NAME)
            if not self.text_edit.toPlainText().strip():
                self.text_edit.setPlainText(sv.DEMO_TEXT)
            self.go_step(1)
        self.pages.show_hint("Готовлю пример почерка…")
        self._run(sv.make_demo_profile, (self.profiles_dir,), done,
                  "Готовлю пример почерка… это займёт около минуты")

    def _need_profile(self) -> bool:
        if self.profile is None:
            QMessageBox.information(self, APP_NAME, "Сначала импортируйте сканы бланка: Почерк → Импорт сканов бланка.")
            return False
        return True

    # ---------- текст ----------

    def new_text(self):
        """Пустое поле; прежний текст возвращается через Ctrl+Z."""
        c = self.text_edit.textCursor()
        c.select(c.SelectionType.Document)
        c.removeSelectedText()
        self.text_edit.setTextCursor(c)
        self.text_edit.setFocus()

    def new_window(self) -> bool:
        """Ещё одно окно программы для второго конспекта — отдельный процесс."""
        if getattr(sys, "frozen", False):
            program, args = sys.executable, ["--new"]
        else:
            program, args = sys.executable, ["-m", "konspekt.gui", "--new"]
        res = QProcess.startDetached(program, args)
        ok = res[0] if isinstance(res, tuple) else bool(res)
        if not ok:
            QMessageBox.warning(self, APP_NAME, "Не удалось открыть новое окно.")
        return ok

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
            self.last_rendered = None
            self._update_plan()
            if getattr(self, "profile_errors", None):
                self.pages.show_hint("Профиль почерка не открылся:\n\n" + "\n".join(self.profile_errors)
                                     + f"\n\nПапка профилей: {self.profiles_dir}")
            else:
                self.pages.show_hint("Нет профиля почерка.\n\nРаспечатайте бланк («Бланк ▾»), заполните его ручкой, "
                                     "отсканируйте и нажмите «Импорт сканов…».\n\nПошагово: Справка → С чего начать. "
                                     "Посмотреть сразу: Справка → Попробовать на примере почерка.")
            self._set_missing(set())
            return
        if not text.strip():
            self.pages_label.clear()
            self.last_rendered = None
            self._update_plan()
            self.pages.show_hint("Вставьте текст на шаге «Текст» — здесь появятся страницы.")
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
        self.pages.set_pages(images, r.dpi, r.is_spread)
        self._set_missing(r.missing)
        n = len(r.images)
        if r.is_spread:
            k = n // 2
            how = ("вложить друг в друга, листок 1 снаружи" if self.nested_box.isChecked() and k > 1
                   else "сложить стопкой по порядку" if k > 1 else "сначала наружная сторона, потом внутренняя")
            self.pages_label.setText(f"{k} {_plural(k, 'двойной листок', 'двойных листка', 'двойных листков')}: {how}")
        else:
            self.pages_label.setText(f"{n} {_plural(n, 'страница', 'страницы', 'страниц')} · "
                                     f"{self.page_box.currentText().lower()}, {self.paper_box.currentText().lower()}")
        self.last_rendered = r
        self._update_plan()
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
        """Выбор принтера и начало печати по шагам (страница «Печать»)."""
        if not self._need_profile() or not self.text_edit.toPlainText().strip():
            return
        self.go_step(2)
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
        if ask_flip:
            self.go_step(2)
            self.print_page.set_plan(self.print_steps(printer, r), True, self._plan_subtitle(r, printer))
            return
        # Без шагов (проверки): все стороны подряд, как их печатал бы человек.
        if not r.is_spread:
            self._paint_images(printer, r.images)
            return
        for outer, inner in r.sheets():
            if not self._paint_images(printer, [r.images[outer]]):
                return
            if inner is not None and not self._paint_images(printer, [r.images[inner]]):
                return

    def _plan_subtitle(self, r: sv.Rendered, printer: QPrinter | None = None) -> str:
        if r.is_spread:
            n = len(r.sheets())
            sides = sum(1 + (inner is not None) for _, inner in r.sheets())
            text = (f"{n} {_plural(n, 'двойной листок', 'двойных листка', 'двойных листков')} · "
                    f"{sides} {_plural(sides, 'заход', 'захода', 'заходов')} в принтер")
        else:
            n = len(r.images)
            text = f"{n} {_plural(n, 'страница', 'страницы', 'страниц')}"
        return text + (f" · {printer.printerName()}" if printer is not None and printer.printerName() else "")

    def _print_finished(self, done: bool):
        if self.print_page.printed:
            self.statusBar().showMessage("Печать: готово." if done else "Печать остановлена.", 8000)
        self._update_plan()

    def _update_plan(self):
        """План печати по последнему предпросмотру: видно, что и как будет печататься."""
        if self.print_page.running:
            return
        r = getattr(self, "last_rendered", None)
        if r is None or not r.images:
            self.print_page.set_plan([], False, "")
            self.print_sub.setText("")
            return
        self.print_page.set_plan(self.print_steps(None, r), False, self._plan_subtitle(r))
        self.print_sub.setText(self._plan_subtitle(r))

    def print_steps(self, printer: QPrinter | None, r: sv.Rendered) -> list[PrintStep]:
        """Шаги печати с картинками. Без принтера — только план, без действий."""
        def small(im) -> QImage:  # для анимации и плана хватит маленькой копии
            q = im if isinstance(im, QImage) else to_qimage(im)
            return q.scaledToWidth(min(q.width(), 700), Qt.SmoothTransformation)

        def job(images):
            return None if printer is None else (lambda: self._paint_images(printer, images))

        if not r.is_spread:
            n = len(r.images)
            first = small(r.images[0])
            count = f"{n} {_plural(n, 'страницу', 'страницы', 'страниц')}"
            if self.real_paper.isChecked():
                sheet = "тетрадный листок" if self.page_box.currentData() == "notebook" else "лист"
                return [
                    PrintStep(f"Положите {sheet} в лоток",
                              "Верхним краем вперёд, как на картинке. "
                              + (f"Листки по одному: напечатается {count}." if n > 1 else "Напечатается одна страница."),
                              "insert", first, "Печатать", job(r.images), spread=False, mini=first),
                    PrintStep("Проверьте, легли ли строки в клетки",
                              "Если текст съехал, поправьте «Сдвиг под принтер» и напечатайте снова.",
                              "done", first, "Готово", spread=False),
                ]
            return [
                PrintStep("Положите чистую бумагу в лоток",
                          f"Клетка и поля напечатаются вместе с текстом. Напечатается {count}.",
                          "insert", first, "Печатать", job(r.images), spread=False, mini=first),
                PrintStep("Готово", "Листы выйдут по порядку, первая страница сверху.", "done", first, "Готово",
                          spread=False),
            ]
        steps = []
        sheets = r.sheets()
        n = len(sheets)
        for i, (outer, inner) in enumerate(sheets):
            head = f"Листок {i + 1}: " if n > 1 else ""
            more = " Подпишите карандашом в уголке номер листка." if n > 1 else ""
            outer_img = small(r.images[outer])
            steps.append(PrintStep(
                head + ("положите чистый двойной листок" if i == 0 else "положите следующий чистый листок"),
                "Развёрнутым, узкой стороной в лоток, как на картинке. Напечатается: "
                + r.labels[outer].split(": ", 1)[-1] + "." + more,
                "insert", outer_img, "Печатать наружную сторону", job([r.images[outer]]), mini=outer_img))
            if inner is None:
                continue
            steps.append(PrintStep(
                head + "переверните листок",
                "Напечатанной стороной {лицом}, оранжевым краем снова вперёд. Дайте чернилам высохнуть. "
                "Напечатается: " + r.labels[inner].split(": ", 1)[-1] + ".",
                "flip", outer_img, "Печатать внутреннюю сторону", job([r.images[inner]]),
                mini=small(r.images[inner])))
        if n > 1 and self.nested_box.isChecked():
            done = ("Листок 1 снаружи, в него вложите листок 2" + (", в него листок 3" if n > 2 else "")
                    + (" и так далее" if n > 3 else "") + ". Сложите пополам — страницы пойдут по порядку.")
        elif n > 1:
            done = "Сложите листки стопкой по номерам, листок 1 сверху, и согните пополам."
        else:
            done = "Страницы пойдут по порядку, как в тетради."
        steps.append(PrintStep("Сложите пополам", done, "fold", small(r.images[sheets[0][0]]), "Готово"))
        for st in steps:
            st.title = st.title[:1].upper() + st.title[1:]
        return steps

    # ---------- шаги ----------

    def go_step(self, k: int, animate: bool = True):
        """Шаг 1 «Текст», 2 «Вид», 3 «Печать» (k = 0, 1, 2)."""
        if self.stack.currentIndex() != k or not animate:
            self.stack.setCurrentIndex(k)
            if animate:  # новая страница проявляется
                w = self.stack.currentWidget()
                eff = QGraphicsOpacityEffect(w)
                w.setGraphicsEffect(eff)
                self._step_anim = QPropertyAnimation(eff, b"opacity", self)
                self._step_anim.setDuration(200)
                self._step_anim.setStartValue(0.2)
                self._step_anim.setEndValue(1.0)
                self._step_anim.finished.connect(lambda w=w: w.setGraphicsEffect(None))
                self._step_anim.start()
        for i, b in enumerate(self.step_buttons):
            state = "on" if i == k else "done" if i < k else ""
            b.setChecked(i == k)
            b.setIcon(QIcon(step_pixmap(i + 1, state)))
        if k == 0:
            self.text_edit.setFocus()
        elif k == 2:
            self._update_plan()

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

    # ---------- обновления ----------

    def show_about(self):
        ver = updates.current_version() or "из исходников"
        QMessageBox.about(self, APP_NAME, f"<b>{APP_NAME}</b><br>Версия: {ver}<br><br>"
                          f'<a href="{updates.RELEASES_PAGE}">Страница программы на GitHub</a>')

    def check_updates(self, silent: bool = True):
        """Спрашивает GitHub о последней версии. silent — проверка при запуске:
        без интернета и когда обновлений нет, ничего не показываем."""
        if not silent:
            self.statusBar().showMessage("Проверяю обновления…")

        def fail(msg):
            if not silent:
                self.statusBar().clearMessage()
                QMessageBox.information(self, APP_NAME, "Не удалось проверить обновления: нет связи с GitHub.\n\n"
                                        "Программа работает и без интернета, проверить можно позже.")

        self._start(Task(updates.fetch_latest, on_done=lambda rel: self._update_info(rel, silent), on_fail=fail))

    def _update_info(self, rel: updates.Release, silent: bool):
        self.statusBar().clearMessage()
        current = updates.current_version()
        newer = updates.is_newer(rel.version, current)
        if silent and (not newer or self._update_failed or self.qs.value("skip_version", "") == rel.version):
            return
        if current and not newer:
            QMessageBox.information(self, APP_NAME, f"У вас последняя версия ({current}).")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Обновление")
        box.setIcon(QMessageBox.Information)
        if current:
            box.setText(f"<b>Вышла новая версия {rel.version}</b><br>У вас установлена {current}.<br><br>"
                        "Обновить сейчас? Профили почерков и настройки сохранятся.")
        else:
            box.setText(f"Последняя версия на GitHub — {rel.version}.<br>"
                        "Эта копия запущена из исходников и сама не обновляется.")
        if rel.notes:
            box.setDetailedText(rel.notes)
        update = box.addButton("Обновить" if current else "Открыть страницу", QMessageBox.AcceptRole)
        box.addButton("Позже", QMessageBox.RejectRole)
        skip = box.addButton("Пропустить эту версию", QMessageBox.DestructiveRole) if current else None
        box.exec()
        if box.clickedButton() is skip:
            self.qs.setValue("skip_version", rel.version)
        elif box.clickedButton() is update:
            if current and updates.in_temp():
                self._explain_temp_copy()
            elif rel.download_url and updates.can_self_update():
                self._download_update(rel)
            else:
                QDesktopServices.openUrl(QUrl(rel.page_url))

    def _explain_temp_copy(self):
        QMessageBox.information(
            self, "Обновление",
            "Программа запущена прямо из архива, без распаковки. Такую копию обновить нельзя: "
            "при следующем запуске из архива Windows снова достанет из него старую версию.<br><br>"
            "Распакуйте архив Konspekt-windows.zip (правой кнопкой → «Извлечь все…») и запускайте "
            "Konspekt.exe из распакованной папки. Профили почерков при этом сохранятся.")

    def check_update_result(self) -> None:
        """Обновление, начатое в прошлый раз, могло не встать: программа снова
        запущена из архива, ярлык ведёт на другую копию или старую папку не
        удалось заменить. Тогда не предлагаем ту же версию по кругу, а говорим,
        в чём дело."""
        expected = str(self.qs.value("update_pending", "") or "")
        if not expected:
            return
        expected_dir = str(self.qs.value("update_dir", "") or "")
        self.qs.remove("update_pending")
        self.qs.remove("update_dir")
        current = updates.current_version()
        outcome = updates.update_outcome(expected, expected_dir, current)
        if outcome == "ok":
            self.statusBar().showMessage(f"Программа обновлена до версии {current}.", 8000)
            return
        self._update_failed = True
        here = updates.app_dir()
        if updates.in_temp():
            text = ("Программа снова запущена прямо из архива, поэтому открылась старая версия "
                    f"{current}, а не {expected}.<br><br>Распакуйте архив Konspekt-windows.zip "
                    "(правой кнопкой → «Извлечь все…») и запускайте Konspekt.exe из распакованной папки.")
        elif outcome == "other_copy":
            text = (f"Версия {expected} установлена в папку<br><b>{expected_dir}</b>,<br>"
                    f"а сейчас запущена другая, старая копия ({current}) из папки<br><b>{here}</b>.<br><br>"
                    "Запускайте Konspekt.exe из первой папки (или поправьте ярлык), "
                    "а старую копию можно удалить. Профили почерков общие, они не пропадут.")
        else:
            text = (f"Не получилось обновиться до версии {expected}: осталась версия {current}.<br><br>"
                    "Закройте все окна программы и папку с ней в Проводнике и попробуйте ещё раз "
                    "(«Справка → Проверить обновления»). Если снова не выйдет, скачайте новую версию "
                    f'<a href="{updates.RELEASES_PAGE}">со страницы программы</a> и распакуйте вместо старой.')
        box = QMessageBox(QMessageBox.Warning, "Обновление не установилось", text, QMessageBox.Ok, self)
        box.setTextFormat(Qt.RichText)
        box.exec()

    def _download_update(self, rel: updates.Release):
        dlg = QProgressDialog(f"Скачиваю версию {rel.version}…", "Отмена", 0, 1000, self)
        dlg.setWindowTitle("Обновление")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        state = {"done": 0, "total": rel.size}

        def progress(done, total):  # из фонового потока: только записываем
            state["done"], state["total"] = done, total

        poll = QTimer(dlg)
        started = time.monotonic()

        def show():  # сколько скачано и сколько примерно осталось: при медленном интернете это долго
            done, total = state["done"], state["total"]
            dlg.setValue(int(1000 * done / max(total, 1)))
            text = f"Скачиваю версию {rel.version}…\n{done / 2**20:.0f} из {total / 2**20:.0f} МБ"
            speed = done / max(time.monotonic() - started, 1e-3)
            if done > 2**20 and total > done:
                left = (total - done) / speed
                text += f", осталось около {_duration(left)}"
            dlg.setLabelText(text)

        poll.timeout.connect(show)
        poll.start(200)

        def done(new_dir):
            poll.stop()
            dlg.close()
            QMessageBox.information(self, "Обновление", "Новая версия скачана. Программа закроется "
                                    "и сразу откроется уже обновлённой.")
            self._save_settings()
            # после перезапуска сверим: встала ли новая версия (см. check_update_result)
            self.qs.setValue("update_pending", rel.version)
            self.qs.setValue("update_dir", str(updates.app_dir()))
            self.qs.sync()
            try:
                updates.start_finish(new_dir)
            except OSError as e:
                QMessageBox.critical(self, APP_NAME, f"Не удалось запустить обновление: {e}")
                return
            QApplication.quit()

        def fail(msg):
            poll.stop()
            dlg.close()
            if not dlg.wasCanceled():
                QMessageBox.warning(self, APP_NAME, f"Не удалось скачать обновление: {msg}\n\n"
                                    "Можно скачать вручную со страницы программы на GitHub.")

        self._start(Task(updates.download, rel, progress, dlg.wasCanceled, on_done=done, on_fail=fail))
        dlg.show()

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


def _duration(seconds: float) -> str:
    m = round(seconds / 60)
    if m < 1:
        return "минуты"
    if m < 60:
        return f"{m} мин"
    return f"{m // 60} ч {m % 60} мин"


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
    if os.environ.get(UPDATE_SELFTEST):
        return _update_selftest(app)
    args = sys.argv if argv is None else argv
    if updates.FINISH_ARG in args:
        return _finish_update(*args[args.index(updates.FINISH_ARG) + 1:][:2])
    w = MainWindow(os.environ.get("KONSPEKT_PROFILES"), blank="--new" in args)
    if w.blank:
        w.setWindowTitle(f"{APP_NAME} — новый конспект")
    w.show()
    if not w.blank and w.should_welcome():
        QTimer.singleShot(400, w.show_welcome)
    if not w.blank and updates.current_version():
        updates.cleanup_leftovers()
        QTimer.singleShot(800, w.check_update_result)
        QTimer.singleShot(1500, w.check_updates)
    return app.exec()


def _finish_update(target: str, pid: str) -> int:
    """Вторая половина обновления: эту программу запустили из временной папки,
    она заменяет собой старую и запускает её."""
    try:
        exe = updates.finish_update(target, pid)
    except OSError as e:
        QMessageBox.critical(None, APP_NAME, f"Не удалось обновить программу: {e}\n\n"
                             "Закройте все окна программы и попробуйте ещё раз. Старая версия осталась на месте.")
        exe = Path(target) / "Konspekt.exe"
    updates.spawn([str(exe)])
    return 0


UPDATE_SELFTEST = "KONSPEKT_UPDATE_SELFTEST"


def _update_selftest(app: QApplication) -> int:
    """Проверка самообновления в Actions: тот же путь, что после кнопки
    «Обновить», только без окон-вопросов. В переменной — файл для записи хода."""
    import tempfile

    log = Path(os.environ.pop(UPDATE_SELFTEST))  # новая программа не должна обновляться снова

    def note(*parts):
        with open(log, "a", encoding="utf-8") as f:
            f.write(" ".join(str(p) for p in parts) + "\n")

    QMessageBox.information = staticmethod(lambda *a, **k: note("окно:", a[2] if len(a) > 2 else a))
    QMessageBox.warning = QMessageBox.critical = staticmethod(
        lambda *a, **k: (note("ошибка:", a[2] if len(a) > 2 else a), app.exit(1)))
    note("версия", updates.current_version(), "папка", updates.app_dir(),
         "можно обновлять", updates.can_self_update())
    d = tempfile.mkdtemp(prefix="konspekt-selftest-")
    w = MainWindow(Path(d) / "profiles", QSettings(str(Path(d) / "s.ini"), QSettings.IniFormat))
    w.show()
    try:
        rel = updates.fetch_latest(timeout=30)
    except OSError as e:
        note("ошибка: нет связи", e)
        return 1
    note("на GitHub", rel.version, rel.download_url, rel.size)
    QTimer.singleShot(0, lambda: w._download_update(rel))
    code = app.exec()
    note("старая программа закрылась, код", code)
    return code


def _smoke(app: QApplication) -> int:
    """Проверка собранной программы: все части на месте (словари переносов,
    запасной шрифт, OpenCV, PDF), окно открывается."""
    import tempfile

    from .layout import FALLBACK_FONT, Typesetter  # noqa: F401
    import pyphen

    assert FALLBACK_FONT.exists(), FALLBACK_FONT
    assert pyphen.Pyphen(lang="ru_RU").inserted("конспект") != "конспект"
    import cv2
    assert cv2.ximgproc.thinning(np.zeros((8, 8), np.uint8)).shape == (8, 8)
    assert cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50) is not None
    assert updates.current_version(), "сборка не записала номер версии"
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
