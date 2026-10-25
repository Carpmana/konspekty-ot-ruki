"""Просмотр страниц: одна страница, разворот или все подряд, масштаб,
миниатюры внизу и показ на весь экран.

Страницы рисуются одним виджетом (PagesCanvas), а не стопкой QLabel: так
проще листать с плавным появлением и менять масштаб без пересборки окна.
"""

from PySide6.QtCore import Property, QEasingCurve, QPoint, QPropertyAnimation, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
    QToolButton, QVBoxLayout, QWidget,
)

from . import icons

MODES = [("page", "Страница"), ("pair", "Разворот"), ("all", "Все")]
ZOOMS = [0.5, 0.67, 0.8, 1.0, 1.25, 1.5, 2.0, 3.0]  # доля от «по размеру окна»
GAP = 22  # между страницами и до края
BG = "#e9ebf0"


class PagesCanvas(QWidget):
    """Рисует видимые страницы с тенью. Размер виджета = размер раскладки,
    прокрутку даёт QScrollArea вокруг."""

    double_clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.images: list[QImage] = []
        self.rects: list[tuple[int, QRect]] = []  # (номер страницы, где нарисована)
        self._cache: dict[tuple[int, int, int], QPixmap] = {}
        self._fade = 1.0

    def get_fade(self) -> float:
        return self._fade

    def set_fade(self, v: float) -> None:
        self._fade = v
        self.update()

    fade = Property(float, get_fade, set_fade)

    def set_images(self, images: list[QImage]) -> None:
        self.images = images
        self._cache.clear()

    def place(self, rects: list[tuple[int, QRect]], size: QSize) -> None:
        self.rects = rects
        self.setFixedSize(size)
        self.update()

    def _scaled(self, k: int, size: QSize) -> QPixmap:
        key = (k, size.width(), size.height())
        pm = self._cache.get(key)
        if pm is None:
            if len(self._cache) > 40:
                self._cache.clear()
            ratio = self.devicePixelRatioF()
            pm = QPixmap.fromImage(self.images[k].scaled(size * ratio, Qt.IgnoreAspectRatio,
                                                         Qt.SmoothTransformation))
            pm.setDevicePixelRatio(ratio)
            self._cache[key] = pm
        return pm

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(e.rect(), QColor(BG))
        p.setOpacity(self._fade)
        p.setPen(Qt.NoPen)
        for k, r in self.rects:
            if not r.intersects(e.rect()):
                continue
            for i, a in enumerate((26, 16, 9, 5)):  # мягкая тень снизу
                p.setBrush(QColor(30, 40, 70, a))
                p.drawRoundedRect(r.adjusted(-i, -i + 2, i, i + 4), 3 + i, 3 + i)
            p.drawPixmap(r.topLeft(), self._scaled(k, r.size()))
        p.end()

    def mouseDoubleClickEvent(self, e):
        self.double_clicked.emit()


class PagesView(QWidget):
    """Окно просмотра: панель управления сверху, страницы, миниатюры снизу."""

    def __init__(self, fullscreen_button: bool = True):
        super().__init__()
        self.setObjectName("pagesView")
        self._images: list[QImage] = []
        self._dpi = 110
        self._spread = False  # каждая картинка — целая сторона двойного листка
        self._mode = "all"
        self._zoom = 1.0
        self._current = 0  # первая страница текущей группы (для «Страница» и «Разворот»)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        bar = QFrame(objectName="viewerBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 7, 10, 7)
        bl.setSpacing(6)
        seg = QFrame(objectName="seg")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons: dict[str, QPushButton] = {}
        for key, title in MODES:
            b = QPushButton(title, objectName="segButton")
            b.setCheckable(True)
            bold = b.font()
            bold.setBold(True)
            b.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(title) + 26)
            b.clicked.connect(lambda _=False, k=key: self.set_mode(k))
            self.mode_group.addButton(b)
            self.mode_buttons[key] = b
            sl.addWidget(b)
        bl.addWidget(seg)
        bl.addStretch(1)

        def tool(name, tip, slot):
            b = QToolButton(objectName="viewerTool")
            b.setIcon(icons.icon(name))
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.clicked.connect(slot)
            bl.addWidget(b)
            return b

        self.prev_btn = tool("left", "Предыдущая (PageUp)", lambda: self.step(-1))
        self.pos_label = QLabel(objectName="viewerLabel")
        self.pos_label.setAlignment(Qt.AlignCenter)
        self.pos_label.setMinimumWidth(64)
        bl.addWidget(self.pos_label)
        self.next_btn = tool("right", "Следующая (PageDown)", lambda: self.step(1))
        sep = QFrame(objectName="viewerSep")
        sep.setFixedSize(1, 20)
        bl.addWidget(sep)
        tool("minus", "Мельче (Ctrl + колесо мыши)", lambda: self.zoom_by(-1))
        self.zoom_label = QLabel(objectName="viewerLabel")
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_label.setMinimumWidth(44)
        bl.addWidget(self.zoom_label)
        tool("plus", "Крупнее (Ctrl + колесо мыши)", lambda: self.zoom_by(1))
        self.fit_btn = QPushButton("По размеру", objectName="viewerFit")
        self.fit_btn.setToolTip("Страницы целиком в окне")
        self.fit_btn.clicked.connect(self.fit)
        bl.addWidget(self.fit_btn)
        self.full_btn = None
        if fullscreen_button:
            self.full_btn = tool("expand", "На весь экран (двойной щелчок по странице)", self.open_fullscreen)
        lay.addWidget(bar)

        self.area = QScrollArea(objectName="pagesArea")
        self.area.setFrameShape(QFrame.NoFrame)
        self.area.setAlignment(Qt.AlignCenter)
        self.area.setWidgetResizable(False)
        self.canvas = PagesCanvas()
        self.canvas.double_clicked.connect(self.open_fullscreen)
        self.area.setWidget(self.canvas)
        self.area.viewport().installEventFilter(self)
        self.area.verticalScrollBar().valueChanged.connect(self._scrolled)
        lay.addWidget(self.area, 1)

        self._hint = QLabel(self.area)
        self._hint.setAlignment(Qt.AlignCenter)
        self._hint.setWordWrap(True)
        self._hint.setObjectName("viewerHint")

        self.thumbs = QListWidget(objectName="thumbs")
        self.thumbs.setFlow(QListWidget.LeftToRight)
        self.thumbs.setViewMode(QListWidget.IconMode)
        self.thumbs.setWrapping(False)
        self.thumbs.setMovement(QListWidget.Static)
        self.thumbs.setSelectionMode(QListWidget.MultiSelection)
        self.thumbs.setIconSize(QSize(56, 68))
        self.thumbs.setFixedHeight(104)
        self.thumbs.setSpacing(4)
        self.thumbs.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.thumbs.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.thumbs.itemClicked.connect(lambda it: self.go_to(self.thumbs.row(it)))
        lay.addWidget(self.thumbs)

        self._anim = QPropertyAnimation(self.canvas, b"fade", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        for key, d in ((QKeySequence.MoveToPreviousPage, -1), (QKeySequence.MoveToNextPage, 1)):
            sc = QShortcut(key, self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda d=d: self.step(d))

        self.mode_buttons[self._mode].setChecked(True)
        self.show_hint("")

    # ---------- данные ----------

    def show_hint(self, text: str) -> None:
        self.set_pages([])
        self._hint.setText(text)
        self._hint.show()
        self._place_hint()

    def set_pages(self, images: list[QImage], dpi: int = 110, spread: bool = False) -> None:
        same_count = len(images) == len(self._images) and spread == self._spread
        self._images, self._dpi, self._spread = images, dpi, spread
        self.canvas.set_images(images)
        self._hint.setVisible(not images)
        if not same_count:
            self._current = min(self._current, max(0, len(images) - 1))
        self._fill_thumbs()
        self._layout(keep_scroll=same_count)

    def page_count(self) -> int:
        return len(self._images)

    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.mode_buttons[mode].setChecked(True)
        self._current = self._group_start(self._current)
        self._layout()
        self._fade_in()

    # ---------- раскладка ----------

    def _group_size(self) -> int:
        if self._mode == "pair" and not self._spread:
            return 2
        return 1

    def _group_start(self, k: int) -> int:
        n = self._group_size()
        return k - k % n

    def _visible(self) -> list[int]:
        if self._mode == "all":
            return list(range(len(self._images)))
        return list(range(self._current, min(len(self._images), self._current + self._group_size())))

    def _fit_scale(self) -> float:
        """Масштаб «по размеру окна»: пикселей экрана на пиксель картинки."""
        if not self._images:
            return 1.0
        vw = max(100, self.area.viewport().width() - 2 * GAP)
        vh = max(100, self.area.viewport().height() - 2 * GAP)
        im = self._images[0]
        if self._mode == "all":
            return min(vw, 900 * (2 if self._spread else 1)) / im.width()
        n = len(self._visible()) or 1
        return min(vw / (im.width() * n), vh / im.height())

    def _layout(self, keep_scroll: bool = False) -> None:
        if not self._images:
            self.canvas.place([], QSize(1, 1))
            self._update_controls()
            return
        s = self._fit_scale() * self._zoom
        vis = self._visible()
        rects = []
        vw = self.area.viewport().width()
        if self._mode == "all":
            w = max(1, round(self._images[0].width() * s))
            total_w = max(vw, w + 2 * GAP)
            y = GAP
            for k in vis:
                h = round(self._images[k].height() * s)
                rects.append((k, QRect((total_w - w) // 2, y, w, h)))
                y += h + GAP
            size = QSize(total_w, y)
        else:
            sizes = [QSize(round(self._images[k].width() * s), round(self._images[k].height() * s)) for k in vis]
            row_w = sum(z.width() for z in sizes)
            row_h = max(z.height() for z in sizes)
            total_w = max(vw, row_w + 2 * GAP)
            total_h = max(self.area.viewport().height(), row_h + 2 * GAP)
            x = (total_w - row_w) // 2
            for k, z in zip(vis, sizes):  # страницы разворота вплотную, как в тетради
                rects.append((k, QRect(x, (total_h - row_h) // 2, z.width(), z.height())))
                x += z.width()
            size = QSize(total_w, total_h)
        old = self.area.verticalScrollBar().value()
        self.canvas.place(rects, size)
        if keep_scroll:
            self.area.verticalScrollBar().setValue(old)
        self._update_controls()

    def _place_hint(self) -> None:
        self._hint.setGeometry(self.area.rect().adjusted(40, 40, -40, -40))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_hint()
        self._layout(keep_scroll=True)

    def eventFilter(self, obj, e):
        if obj is self.area.viewport() and e.type() == e.Type.Wheel and e.modifiers() & Qt.ControlModifier:
            self.zoom_by(1 if e.angleDelta().y() > 0 else -1)
            return True
        return super().eventFilter(obj, e)

    # ---------- листание и масштаб ----------

    def step(self, d: int) -> None:
        if not self._images:
            return
        n = self._group_size()
        target = self._current + d * n
        if self._mode == "all":
            target = self._current_in_all() + d
        self.go_to(max(0, min(len(self._images) - 1, target)))

    def go_to(self, k: int) -> None:
        if not 0 <= k < len(self._images):
            return
        if self._mode == "all":
            for page, r in self.canvas.rects:
                if page == k:
                    self.area.verticalScrollBar().setValue(r.top() - GAP // 2)
            self._select_thumb(k)
            return
        start = self._group_start(k)
        if start != self._current:
            self._current = start
            self._layout()
            self._fade_in()

    def zoom_by(self, d: int) -> None:
        i = min(range(len(ZOOMS)), key=lambda j: abs(ZOOMS[j] - self._zoom))
        self._zoom = ZOOMS[max(0, min(len(ZOOMS) - 1, i + d))]
        self._layout()

    def fit(self) -> None:
        self._zoom = 1.0
        self._layout()

    def _current_in_all(self) -> int:
        y = self.area.verticalScrollBar().value() + self.area.viewport().height() // 3
        for k, r in self.canvas.rects:
            if r.bottom() + GAP >= y:
                return k
        return max(0, len(self._images) - 1)

    def _scrolled(self, *_):
        if self._mode == "all" and self._images:
            self._update_controls()

    def _fade_in(self) -> None:
        self._anim.stop()
        self._anim.setStartValue(0.15)
        self._anim.setEndValue(1.0)
        self._anim.start()

    # ---------- подписи и миниатюры ----------

    def _update_controls(self) -> None:
        n = len(self._images)
        for w in (self.prev_btn, self.next_btn, self.fit_btn):
            w.setEnabled(n > 0)
        if not n:
            self.pos_label.setText("")
            self.zoom_label.setText("")
            return
        if self._mode == "all":
            cur = self._current_in_all()
            vis = [cur]
        else:
            vis = self._visible()
            cur = vis[0]
        self.pos_label.setText((f"{vis[0] + 1}–{vis[-1] + 1}" if len(vis) > 1 else f"{vis[0] + 1}") + f" из {n}")
        # 100% — реальный размер бумаги на экране (96 точек на дюйм)
        pct = self._fit_scale() * self._zoom * 96 / self._dpi * 100
        self.zoom_label.setText(f"{round(pct)}%")
        self._select_thumb(cur, len(vis))

    def _fill_thumbs(self) -> None:
        self.thumbs.clear()
        self.thumbs.setVisible(len(self._images) > 1)
        if self._spread:
            self.thumbs.setIconSize(QSize(112, 68))
        else:
            self.thumbs.setIconSize(QSize(56, 68))
        for k, im in enumerate(self._images):
            pm = QPixmap.fromImage(im.scaled(self.thumbs.iconSize() * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            pm.setDevicePixelRatio(2)
            ic = QIcon(pm)
            ic.addPixmap(pm, QIcon.Selected)  # без синего оттенка у выбранной миниатюры
            it = QListWidgetItem(ic, str(k + 1))
            it.setTextAlignment(Qt.AlignHCenter)
            self.thumbs.addItem(it)

    def _select_thumb(self, k: int, count: int = 1) -> None:
        self.thumbs.blockSignals(True)
        self.thumbs.clearSelection()
        for j in range(k, min(k + count, self.thumbs.count())):
            self.thumbs.item(j).setSelected(True)
        if 0 <= k < self.thumbs.count():
            self.thumbs.scrollToItem(self.thumbs.item(k))
        self.thumbs.blockSignals(False)

    # ---------- весь экран ----------

    def open_fullscreen(self) -> None:
        if not self._images or self.full_btn is None:
            return
        dlg = QDialog(self.window())
        dlg.setWindowTitle("Просмотр")
        dlg.setObjectName("fullView")
        dl = QVBoxLayout(dlg)
        dl.setContentsMargins(0, 0, 0, 0)
        v = PagesView(fullscreen_button=False)
        dl.addWidget(v)
        close = QPushButton("Закрыть (Esc)", v)
        close.clicked.connect(dlg.accept)
        v.findChild(QFrame, "viewerBar").layout().addWidget(close)
        v.set_pages(self._images, self._dpi, self._spread)
        v.set_mode("pair" if self._mode == "all" and not self._spread else self._mode)
        v.go_to(self._current_in_all() if self._mode == "all" else self._current)
        dlg.showMaximized()
        dlg.exec()
