"""Контролируемые случайности почерка.

Главное отличие от «шрифта с искажениями»: соседние значения связаны.
Базовая линия плывёт плавной волной, наклон меняется от слова к слову
постепенно, а не скачет от буквы к букве.
"""

from collections import defaultdict, deque

import numpy as np


class SmoothNoise:
    """Плавная кривая из нескольких синусоид со случайными фазами."""

    def __init__(self, rng: np.random.Generator, amplitude: float, wavelengths=(90.0, 37.0, 16.0)):
        self.terms = [(amplitude * w / sum(wavelengths), 2 * np.pi / w, rng.uniform(0, 2 * np.pi))
                      for w in wavelengths]

    def __call__(self, x: float) -> float:
        return float(sum(a * np.sin(k * x + ph) for a, k, ph in self.terms))


class AR1:
    """Процесс с памятью: следующее значение близко к предыдущему."""

    def __init__(self, rng: np.random.Generator, sigma: float, keep: float = 0.65):
        self.rng, self.sigma, self.keep, self.value = rng, sigma, keep, 0.0

    def next(self, scale: float = 1.0) -> float:
        self.value = self.keep * self.value + self.rng.normal(0, self.sigma * scale)
        return self.value


class VariantPicker:
    """Выбирает вариант образца, избегая недавно использованных."""

    def __init__(self, rng: np.random.Generator, memory: int = 1):
        self.rng = rng
        self.recent: dict[str, deque] = defaultdict(lambda: deque(maxlen=memory))

    def pick(self, key: str, variants: list):
        recent = self.recent[key]
        fresh = [v for v in variants if v.id not in recent] or variants
        choice = fresh[int(self.rng.integers(len(fresh)))]
        recent.append(choice.id)
        return choice
