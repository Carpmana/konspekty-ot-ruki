import numpy as np

from konspekt.shape import edges, entry_point, exit_point, optical_x


def test_edges():
    a = np.zeros((10, 20), np.float32)
    a[2:8, 5:9] = 1.0
    e = edges(a)
    assert list(e.rows) == [2, 3, 4, 5, 6, 7]
    assert (e.left == 5).all() and (e.right == 8).all()


def test_optical_x_uses_closest_strokes():
    prev_right = np.array([np.nan, 10.0, 12.0, np.nan], np.float32)
    next_left = np.array([0.0, 1.0, 3.0, 0.0], np.float32)
    # Ближе всего штрихи в первой общей строке: 10 - 1; во второй 12 - 3.
    assert optical_x(prev_right, next_left, 0.5) == 9.5
    assert optical_x(np.full(3, np.nan), np.zeros(3), 0.5) is None


def test_exit_low_right_entry_left():
    a = np.zeros((60, 60), np.float32)
    a[20:50, 10:13] = 1.0  # вертикальный штрих слева
    a[45:50, 10:40] = 1.0  # хвост внизу вправо — отсюда идёт соединение
    ex = exit_point(a, baseline=50, xh_px=30)
    en = entry_point(a, baseline=50, xh_px=30)
    assert ex[0] == 39 and ex[1] > 44
    assert en[0] == 10
