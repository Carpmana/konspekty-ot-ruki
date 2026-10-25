"""Значки окна: тонкие линии, как в макете. Рисуются из SVG нужного цвета,
поэтому одна и та же картинка годится и для белой, и для синей кнопки."""

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PATHS = {
    "pen": '<path d="M15 4l5 5-9 9H6v-5z"/><path d="M4 21h16"/>',
    "refresh": '<path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 4v5h-5"/>',
    "download": '<path d="M12 4v11"/><path d="M7 10l5 5 5-5"/><path d="M5 20h14"/>',
    "printer": '<path d="M7 9V3h10v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 14h10v7H7z"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    "folder": '<path d="M3 7h6l2 2h10v10H3z"/>',
    "expand": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "left": '<path d="M15 5l-7 7 7 7"/>',
    "right": '<path d="M9 5l7 7-7 7"/>',
    "minus": '<path d="M5 12h14"/>',
    "plus": '<path d="M5 12h14M12 5v14"/>',
    "paper": '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M5 9h14M5 15h14M11 3v18"/>',
    "lines": '<path d="M4 6h10M4 12h16M4 18h7"/>',
    "chevron": '<path d="M6 9l6 6 6-6"/>',
    "check": '<path d="M5 12l5 5 9-10"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16v.5"/>',
}


def svg(name: str, color: str = "#1f2430", width: float = 2.0) -> bytes:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</svg>').encode()


def pixmap(name: str, color: str = "#1f2430", size: int = 16, ratio: float = 2.0) -> QPixmap:
    px = round(size * ratio)
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    QSvgRenderer(QByteArray(svg(name, color))).render(p, QRectF(0, 0, px, px))
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def icon(name: str, color: str = "#1f2430", size: int = 16) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Normal)
    ic.addPixmap(pixmap(name, "#9aa1b2", size), QIcon.Disabled)
    return ic
