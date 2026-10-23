"""Перевод миллиметров в пиксели и обратно."""

MM_PER_INCH = 25.4

A4_MM = (210.0, 297.0)
A5_MM = (148.0, 210.0)


def mm_to_px(mm: float, dpi: float) -> float:
    return mm * dpi / MM_PER_INCH


def px_to_mm(px: float, dpi: float) -> float:
    return px * MM_PER_INCH / dpi
