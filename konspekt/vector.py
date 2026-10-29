"""Образцы букв как гладкие контуры — так же, как сервисы вроде Calligraphr
собирают шрифт из сканов.

Скан шариковой ручки зернистый: внутри штриха светлые точки, край рваный.
Если печатать сам скан, это видно. Поэтому чернила образца превращаем в
сплошную заливку, обводим её контуром, сглаживаем контур и при печати
заливаем его заново прямо в нужном размере. Получаются цельные линии с
чистым краем, как у шрифта, при любой плотности страницы."""

import cv2
import numpy as np

UPSAMPLE = 2  # контур ищем на сетке вдвое мельче образца: край точнее
SHIFT = 4  # субпиксельная точность заливки
MIN_LEVEL, MAX_LEVEL = 0.15, 0.25  # пределы порога «чернила / бумага»


def solid_mask(alpha: np.ndarray, smoothness: float, scale: int) -> np.ndarray:
    """Сплошная заливка штрихов образца на сетке в UPSAMPLE раз мельче.

    Пропуски шарика и зерно внутри линии закрываются. Порог подбирается
    так, чтобы чернил в заливке было столько же, сколько в скане: линия не
    худеет и не толстеет, тонкие штрихи не пропадают."""
    k = 2 * scale + 1
    a = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    a = cv2.GaussianBlur(a, (0, 0), (0.4 + 0.5 * smoothness) * scale)
    h, w = a.shape
    a = cv2.resize(a, (w * UPSAMPLE, h * UPSAMPLE), interpolation=cv2.INTER_CUBIC)
    ink = float(alpha.sum()) * UPSAMPLE * UPSAMPLE
    if ink <= 0:
        return np.zeros(a.shape, np.uint8)
    t = float(np.quantile(a, 1.0 - min(1.0, ink / a.size)))
    return (a > np.clip(t, MIN_LEVEL, MAX_LEVEL)).astype(np.uint8)


def trace(alpha: np.ndarray, smoothness: float = 0.5, scale: int = 1) -> list[np.ndarray]:
    """Контуры чернил образца (внешние и дырки, как в «о») — в пикселях
    300 dpi, как и остальные размеры образца. scale — во сколько раз alpha
    плотнее 300 dpi."""
    mask = solid_mask(alpha, smoothness, scale)
    unit = scale * UPSAMPLE  # клеток маски на пиксель 300 dpi
    contours, hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if hier is None:
        return []
    out = []
    # Меньше этого — соринка или просвет зерна, а не часть буквы (точка над
    # «ё» или «i» заметно крупнее). Площади в клетках маски.
    min_outer = (2.0 * unit) ** 2
    min_hole = (1.0 * unit) ** 2
    sigma = (0.8 + 1.2 * smoothness) * unit
    for c, (_, _, _, parent) in zip(contours, hier[0]):
        area = cv2.contourArea(c)
        if area < (min_hole if parent >= 0 else min_outer):
            continue
        pts = c[:, 0, :].astype(np.float32)
        pts = _smooth_closed(pts, sigma)
        pts = cv2.approxPolyDP(pts[:, None, :], 0.08 * unit, True)[:, 0, :]
        if len(pts) >= 3:
            # Центр клетки маски, а не её угол; потом — в пиксели 300 dpi.
            out.append(((pts + 0.5) / unit).astype(np.float32))
    return out


def _smooth_closed(pts: np.ndarray, sigma: float) -> np.ndarray:
    """Сглаживает замкнутый контур: лестница пикселей и рваный край
    становятся плавной кривой. Короткие контуры (точки) сглаживаются
    слабее, чтобы не сжимались."""
    n = len(pts)
    s = min(sigma, n / 6.0)
    if s < 0.5:
        return pts
    r = int(3 * s)
    x = np.arange(-r, r + 1, dtype=np.float32)
    k = np.exp(-0.5 * (x / s) ** 2)
    k /= k.sum()
    idx = (np.arange(n)[:, None] + np.arange(-r, r + 1)[None, :]) % n
    return (pts[idx] * k[None, :, None]).sum(axis=1)


def fill(contours: list[np.ndarray], lin: np.ndarray, origin: np.ndarray) -> tuple[np.ndarray, int, int]:
    """Заливает контуры, переведённые на страницу (x' = lin·x + origin), со
    сглаженным краем. Возвращает прозрачность и левый верхний угол."""
    if not contours:
        return np.zeros((1, 1), np.float32), 0, 0
    placed = [c @ lin.T + origin for c in contours]
    allp = np.vstack(placed)
    x0, y0 = np.floor(allp.min(axis=0)).astype(int) - 2
    x1, y1 = np.ceil(allp.max(axis=0)).astype(int) + 2
    canvas = np.zeros((y1 - y0, x1 - x0), np.uint8)
    polys = [np.round((p - [x0, y0]) * (1 << SHIFT)).astype(np.int32) for p in placed]
    cv2.fillPoly(canvas, polys, 255, cv2.LINE_AA, SHIFT)
    return canvas.astype(np.float32) / 255.0, int(x0), int(y0)
