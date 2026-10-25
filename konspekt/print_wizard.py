"""Пошаговая печать: картинка показывает, как положить
листок, куда он уходит, как его перевернуть и сложить.

Страница ничего не знает про почерк: MainWindow передаёт ей шаги (PrintStep),
а печать делает функция шага.
"""

import math
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from . import icons

ACCENT = "#1b7a57"
EDGE = QColor("#f08a24")  # край, который идёт в принтер первым
INK = QColor("#2d3446")


@dataclass
class PrintStep:
    title: str
    text: str
    scene: str  # insert | print | flip | fold | done
    image: QImage | None = None  # что печатается или уже напечатано на листке
    button: str = "Дальше"
    action: Callable[[], bool] | None = None  # печать; False — остаться на шаге
    spread: bool = True  # двойной листок (иначе одна страница)
    mini: QImage | None = None  # миниатюра того, что напечатается на этом шаге (для плана)


class PrintScene(QWidget):
    """Анимация шага. Всё рисуется QPainter'ом, по кругу раз в 2,6 секунды."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(360, 360)
        self.scene = "insert"
        self.image: QImage | None = None
        self.spread = True
        self.face_up = True
        self.t = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setDuration(2600)
        self.anim.setLoopCount(-1)
        self.anim.valueChanged.connect(self._tick)
        self.anim.start()

    def _tick(self, v):
        self.t = float(v)
        self.update()

    def show_step(self, scene: str, image: QImage | None, spread: bool) -> None:
        self.scene, self.image, self.spread = scene, image, spread
        self.anim.setCurrentTime(0)
        self.update()

    # ---------- рисование ----------

    def _sheet_size(self) -> tuple[float, float]:
        # двойной листок 205×340 идёт узкой стороной вперёд; тетрадный листок 170×205
        return (138.0, 229.0) if self.spread else (160.0, 193.0)

    def _paper(self, p: QPainter, r: QRectF, image: QImage | None, grid: bool = False) -> None:
        p.save()
        p.setPen(Qt.NoPen)
        for i, a in enumerate((30, 18, 9)):
            p.setBrush(QColor(20, 30, 60, a))
            p.drawRoundedRect(r.adjusted(-i, -i + 3, i, i + 5), 3 + i, 3 + i)
        p.setBrush(QColor("#ffffff"))
        p.drawRect(r)
        if image is not None:
            p.setClipRect(r)
            if self.spread and image.width() > image.height():
                # сторона двойного листка лежит в лотке повёрнутой
                p.translate(r.center())
                p.rotate(-90)
                p.drawImage(QRectF(-r.height() / 2, -r.width() / 2, r.height(), r.width()), image)
            else:
                p.drawImage(r, image)
        elif grid:
            p.setPen(QPen(QColor(205, 222, 242), 1))
            step = 7.0
            x = r.left() + step
            while x < r.right():
                p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
                x += step
            y = r.top() + step
            while y < r.bottom():
                p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
                y += step
        p.restore()

    def _edge(self, p: QPainter, r: QRectF) -> None:
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(EDGE)
        p.drawRoundedRect(QRectF(r.left() - 4, r.top() - 5, r.width() + 8, 6), 3, 3)
        p.restore()

    def _printer(self, p: QPainter, cx: float, blink: bool) -> QRectF:
        body = QRectF(cx - 135, 18, 270, 86)
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 30, 60, 40))
        p.drawRoundedRect(body.adjusted(-2, 4, 2, 8), 16, 16)
        p.setBrush(INK)
        p.drawRoundedRect(body, 14, 14)
        p.setBrush(QColor("#11151f"))
        p.drawRoundedRect(QRectF(body.left() + 40, body.bottom() - 22, body.width() - 80, 8), 4, 4)
        p.setBrush(QColor("#7be08f") if blink else QColor("#3d6b47"))
        p.drawEllipse(QPointF(body.right() - 24, body.top() + 22), 4.5, 4.5)
        p.restore()
        return body

    def _caption(self, p: QPainter, text: str, y: float) -> None:
        p.save()
        f = QFont(self.font())
        f.setPointSizeF(9.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#b4600f"))
        p.drawText(QRectF(0, y, self.width(), 22), Qt.AlignHCenter, text)
        p.restore()

    @staticmethod
    def _ease(u: float) -> float:
        u = max(0.0, min(1.0, u))
        return u * u * (3 - 2 * u)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        cx = self.width() / 2
        t = self.t
        w, h = self._sheet_size()
        base = QRectF(cx - w / 2, 150, w, h)
        blink = int(t * 6) % 2 == 0

        if self.scene in ("fold", "done"):
            self._fold(p, cx, t)
            p.end()
            return

        if self.scene == "print":
            # листок уходит в принтер, потом всё сначала
            u = self._ease(t / 0.6)
            r = base.translated(0, -125 * u)
            p.setOpacity(1.0 if t < 0.8 else max(0.0, 1 - (t - 0.8) / 0.2))
            self._paper(p, r, self.image)
            self._edge(p, r)
            p.setOpacity(1.0)
            self._printer(p, cx, blink)
        elif self.scene == "flip":
            self._printer(p, cx, False)
            u = self._ease((t - 0.12) / 0.5)
            c = math.cos(math.pi * u)
            sx = max(abs(c), 0.02)
            p.save()
            p.setTransform(QTransform().translate(cx, 0).scale(sx, 1), False)
            r = QRectF(-w / 2, base.top(), w, h)
            if c >= 0:
                self._paper(p, r, self.image)
            else:
                self._paper(p, r, None, grid=True)
            self._edge(p, r)
            p.restore()
            self._caption(p, "оранжевый край снова вперёд", base.bottom() + 12)
        else:  # insert
            self._printer(p, cx, False)
            bob = 6 * math.sin(2 * math.pi * t)
            r = base.translated(0, bob)
            self._paper(p, r, None, grid=True)
            self._edge(p, r)
            # стрелка к принтеру
            p.save()
            p.setPen(QPen(EDGE, 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            ay = 128 + bob
            p.drawLine(QPointF(cx, ay + 14), QPointF(cx, ay - 6))
            path = QPainterPath(QPointF(cx - 7, ay + 1))
            path.lineTo(cx, ay - 7)
            path.lineTo(cx + 7, ay + 1)
            p.drawPath(path)
            p.restore()
            self._caption(p, "этим краем в принтер", base.bottom() + 12)
        p.end()

    def _fold(self, p: QPainter, cx: float, t: float) -> None:
        """Развёрнутый листок складывается пополам: левая половина уходит
        под правую, сверху остаётся страница 1."""
        img = self.image
        W, H = 260.0, 157.0
        top = 110.0
        left = QRectF(cx - W / 2, top, W / 2, H)
        right = QRectF(cx, top, W / 2, H)
        u = self._ease((t - 0.15) / 0.5)
        c = math.cos(math.pi * u)
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 30, 60, 30))
        p.drawRect(right.adjusted(-2, 3, 2, 6))
        p.restore()
        if c < 0:
            self._half(p, left, img, 0, c)  # уже под правой половиной
        self._half(p, right, img, 1, 1.0)
        if c >= 0:
            self._half(p, left, img, 0, c)
        self._caption(p, "сложите пополам", top + H + 24)

    def _half(self, p: QPainter, r: QRectF, img: QImage | None, side: int, sx: float) -> None:
        p.save()
        hinge = r.right() if side == 0 else r.left()
        p.setTransform(QTransform().translate(hinge, 0).scale(max(abs(sx), 0.02) * (1 if sx >= 0 else -1), 1)
                       .translate(-hinge, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawRect(r)
        if img is not None and sx >= 0:
            src = QRectF(side * img.width() / 2, 0, img.width() / 2, img.height())
            p.drawImage(r, img, src)
        p.setPen(QPen(QColor(200, 205, 215), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r)
        p.restore()


class PrintPage(QWidget):
    """Шаг «Печать»: слева план (все заходы в принтер) и настройки печати,
    справа текущий шаг крупно, с анимацией.

    Пока печать не начата, план показывает, что будет, а кнопка начинает
    печать (start_requested). Во время печати кнопка выполняет шаг."""

    start_requested = Signal()
    back_requested = Signal()
    finished = Signal(bool)  # True — дошли до конца

    def __init__(self, settings: QWidget | None = None, face_up: bool = True):
        super().__init__()
        self.setObjectName("printPage")
        self.steps: list[PrintStep] = []
        self.index = 0
        self.running = False
        self.printed = 0  # сколько заходов в принтер уже сделано
        self.rows: list[tuple[QFrame, QLabel, QLabel, QLabel, QLabel]] = []

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        left = QFrame(objectName="planPanel")
        left.setFixedWidth(400)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(20, 20, 16, 16)
        ll.setSpacing(4)
        ll.addWidget(QLabel("План печати", objectName="planTitle"))
        self.plan_sub = QLabel(objectName="hint")
        ll.addWidget(self.plan_sub)
        ll.addSpacing(8)
        box = QWidget()
        self.list_layout = QVBoxLayout(box)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(6)
        self.list_layout.addStretch(1)
        self.list_scroll = QScrollArea(objectName="planList")
        self.list_scroll.setWidget(box)
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QFrame.NoFrame)
        self.list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ll.addWidget(self.list_scroll, 1)

        self.settings_box = QFrame(objectName="printSettings")
        sl = QVBoxLayout(self.settings_box)
        sl.setContentsMargins(0, 12, 0, 0)
        sl.setSpacing(6)
        if settings is not None:
            sl.addWidget(settings)
        face = QHBoxLayout()
        face.addWidget(QLabel("Принтер печатает на стороне,\nкоторая в лотке"))
        face.addStretch(1)
        self.face_box = QComboBox()
        self.face_box.addItem("сверху", True)
        self.face_box.addItem("снизу", False)
        self.face_box.setCurrentIndex(0 if face_up else 1)
        self.face_box.setToolTip("Посмотрите на напечатанный листок: текст вышел на стороне, которая лежала "
                                 "в лотке сверху или снизу? От этого зависит, как переворачивать листок.")
        self.face_box.currentIndexChanged.connect(lambda *_: self._show())
        face.addWidget(self.face_box)
        sl.addLayout(face)
        ll.addWidget(self.settings_box)
        lay.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(30, 24, 30, 24)
        rl.setSpacing(10)
        rl.addStretch(1)
        self.title = QLabel(objectName="stepTitle")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setWordWrap(True)
        rl.addWidget(self.title)
        self.text = QLabel(objectName="stepText")
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setWordWrap(True)
        rl.addWidget(self.text)
        self.scene = PrintScene()
        self.scene.setFixedSize(480, 420)
        self.scene.face_up = face_up
        rl.addWidget(self.scene, 0, Qt.AlignHCenter)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.back_btn = QPushButton("Назад")
        self.back_btn.clicked.connect(self._back)
        self.next_btn = QPushButton(objectName="primary")
        self.next_btn.clicked.connect(self._next)
        for b in (self.back_btn, self.next_btn):
            b.setMinimumHeight(40)
            b.setMinimumWidth(120)
            buttons.addWidget(b)
        self.next_btn.setMinimumWidth(230)
        buttons.addStretch(1)
        rl.addLayout(buttons)
        rl.addStretch(1)
        lay.addWidget(right, 1)
        self.set_plan([], False)

    @property
    def face_up(self) -> bool:
        return bool(self.face_box.currentData())

    def set_plan(self, steps: list[PrintStep], running: bool, subtitle: str = "") -> None:
        """Новый план. running=False — только показать, что будет."""
        self.steps, self.running, self.index, self.printed = steps, running, 0, 0
        self.plan_sub.setText(subtitle)
        for row in self.rows:
            self.list_layout.removeWidget(row[0])
            row[0].hide()
            row[0].deleteLater()
        self.rows = []
        for i, st in enumerate(steps):
            row = QFrame(objectName="planStep")
            hl = QHBoxLayout(row)
            hl.setContentsMargins(12, 10, 12, 10)
            hl.setSpacing(12)
            dot = QLabel(objectName="planDot")
            dot.setFixedSize(34, 34)
            dot.setAlignment(Qt.AlignCenter)
            hl.addWidget(dot)
            texts = QVBoxLayout()
            texts.setSpacing(1)
            t1 = QLabel(st.title, objectName="planStepTitle")
            t1.setWordWrap(True)
            t2 = QLabel(objectName="hint")
            t2.setWordWrap(True)
            texts.addWidget(t1)
            texts.addWidget(t2)
            hl.addLayout(texts, 1)
            mini = QLabel(objectName="planMini")
            if st.mini is not None:
                pm = QPixmap.fromImage(st.mini.scaled(192, 116, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                pm.setDevicePixelRatio(2)
                mini.setPixmap(pm)
            hl.addWidget(mini)
            self.list_layout.insertWidget(i, row)
            self.rows.append((row, dot, t1, t2, mini))
        self.settings_box.setVisible(not running)
        self._show()

    def _text(self, st: PrintStep) -> str:
        return st.text.replace("{лицом}", "вниз" if self.face_up else "вверх")

    def _short(self, st: PrintStep) -> str:
        """Подпись в плане — первая фраза описания."""
        t = self._text(st)
        return t.split(". ")[0].rstrip(".") if t else ""

    def _show(self) -> None:
        self.scene.face_up = self.face_up
        if not self.steps:
            self.title.setText("Нечего печатать")
            self.text.setText("Вставьте текст на шаге «Текст» — здесь появится план печати.")
            self.next_btn.setEnabled(False)
            self.back_btn.setText("Назад")
            return
        self.next_btn.setEnabled(True)
        cur = self.index if self.running else -1
        for i, (row, dot, t1, t2, mini) in enumerate(self.rows):
            state = "on" if i == cur else "done" if i < cur else ""
            for w in (row, dot):
                w.setProperty("state", state)
                w.style().unpolish(w)
                w.style().polish(w)
            dot.setText("✓" if i < cur else str(i + 1))
            t2.setText(self._short(self.steps[i]))
        st = self.steps[self.index]
        self.title.setText(st.title)
        self.text.setText(self._text(st))
        self.scene.show_step(st.scene, st.image, st.spread)
        if not self.running:
            self.next_btn.setText("Начать печать…")
            self.next_btn.setIcon(icons.icon("printer", "#ffffff"))
            self.back_btn.setText("Назад")
            return
        self.back_btn.setText("Остановить" if self.index == 0 else "Назад")
        self.next_btn.setText(st.button)
        if st.action is not None:
            self.next_btn.setIcon(icons.icon("printer", "#ffffff"))
        else:
            self.next_btn.setIcon(icons.icon("check" if self.index == len(self.steps) - 1 else "right", "#ffffff"))
        self.list_scroll.ensureWidgetVisible(self.rows[self.index][0], 0, 40)

    def _back(self) -> None:
        if not self.running:
            self.back_requested.emit()
        elif self.index == 0:
            self.stop()
        else:
            self.index -= 1
            self._show()

    def stop(self, done: bool = False) -> None:
        self.running = False
        self.index = 0
        self.settings_box.show()
        self._show()
        self.finished.emit(done)

    def _next(self) -> None:
        if not self.running:
            self.start_requested.emit()
            return
        st = self.steps[self.index]
        if st.action is None:
            self._advance()
            return
        # пока страницы уходят на принтер, показываем, как листок затягивается
        self.next_btn.setEnabled(False)
        self.back_btn.setEnabled(False)
        self.next_btn.setText("Отправляю на принтер…")
        self.next_btn.setIcon(QIcon())
        self.scene.show_step("print", st.image, st.spread)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QTimer.singleShot(60, self._do_print)

    def _do_print(self) -> None:
        st = self.steps[self.index]
        try:
            ok = st.action()
        finally:
            QApplication.restoreOverrideCursor()
        if not ok:
            self.next_btn.setEnabled(True)
            self.back_btn.setEnabled(True)
            self._show()
            return
        self.printed += 1
        QTimer.singleShot(1400, self._after_print)

    def _after_print(self) -> None:
        self.next_btn.setEnabled(True)
        self.back_btn.setEnabled(True)
        self._advance()

    def _advance(self) -> None:
        if self.index >= len(self.steps) - 1:
            self.stop(done=True)
            return
        self.index += 1
        self._show()
