"""Форма образца: контуры слева и справа и точки для соединений.

Расстояние между буквами в почерке определяется не прямоугольниками вокруг
букв, а тем, как близко подходят друг к другу сами штрихи. Поэтому соседние
буквы расставляются по контурам («оптический» интервал), а соединительный
штрих тянется от нижнего правого края одной буквы к левому краю следующей.
"""

from dataclasses import dataclass

import numpy as np

ROW_MM = 0.1  # шаг сетки строк при сравнении контуров
INK = 0.3


@dataclass
class Edges:
    """Контуры образца по строкам: координаты в пикселях образца."""

    rows: np.ndarray  # номера строк, где есть чернила
    left: np.ndarray
    right: np.ndarray


def edges(alpha: np.ndarray) -> Edges:
    mask = alpha > INK
    rows = np.nonzero(mask.any(axis=1))[0]
    sub = mask[rows]
    left = sub.argmax(axis=1)
    right = sub.shape[1] - 1 - sub[:, ::-1].argmax(axis=1)
    return Edges(rows, left.astype(np.float32), right.astype(np.float32))


def band_profile(e: Edges, baseline: float, scale: float, x0: float, dy: float,
                 lo: int, hi: int, side: str) -> np.ndarray:
    """Контур в миллиметрах на общей сетке строк [lo, hi) вокруг базовой линии.
    Где чернил нет — NaN."""
    out = np.full(hi - lo, np.nan, np.float32)
    idx = np.round(((e.rows - baseline) * scale + dy) / ROW_MM).astype(int) - lo
    ok = (idx >= 0) & (idx < hi - lo)
    if side == "right":
        vals = x0 + e.right[ok] * scale
        tmp = np.full(hi - lo, -np.inf, np.float32)
        np.maximum.at(tmp, idx[ok], vals)
        out[np.isfinite(tmp)] = tmp[np.isfinite(tmp)]
    else:
        vals = e.left[ok] * scale
        tmp = np.full(hi - lo, np.inf, np.float32)
        np.minimum.at(tmp, idx[ok], vals)
        out[np.isfinite(tmp)] = tmp[np.isfinite(tmp)]
    return out


def optical_x(prev_right: np.ndarray, next_left: np.ndarray, gap: float) -> float | None:
    """Где поставить левый край картинки следующего образца, чтобы ближайшие
    точки штрихов оказались на расстоянии gap. None — контуры не пересекаются
    по высоте (например, точка после буквы)."""
    both = ~np.isnan(prev_right) & ~np.isnan(next_left)
    if not both.any():
        return None
    return float(np.max(prev_right[both] - next_left[both]) + gap)


def exit_point(alpha: np.ndarray, baseline: float, xh_px: float) -> tuple[float, float] | None:
    """Выход штриха: самая правая точка в нижней части строчной полосы —
    оттуда в прописи идёт соединение к следующей букве."""
    return _extreme(alpha, baseline - 0.45 * xh_px, baseline + 0.1 * xh_px, rightmost=True)


def entry_point(alpha: np.ndarray, baseline: float, xh_px: float) -> tuple[float, float] | None:
    """Вход штриха: самая левая точка в строчной полосе."""
    return _extreme(alpha, baseline - 0.9 * xh_px, baseline + 0.05 * xh_px, rightmost=False)


def _extreme(alpha: np.ndarray, y0: float, y1: float, rightmost: bool) -> tuple[float, float] | None:
    h = alpha.shape[0]
    a, b = int(max(0, np.floor(y0))), int(min(h, np.ceil(y1)))
    if b <= a:
        return None
    ys, xs = np.nonzero(alpha[a:b] > INK)
    if xs.size == 0:
        return None
    x = xs.max() if rightmost else xs.min()
    sel = np.abs(xs - x) <= 2
    return float(x), float(np.median(ys[sel]) + a)
