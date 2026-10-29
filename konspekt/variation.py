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

    def snapshot(self) -> dict:
        return {k: deque(v, maxlen=v.maxlen) for k, v in self.recent.items()}

    def restore(self, state: dict) -> None:
        """Забыть выборы для отброшенной попытки (слово не влезло)."""
        self.recent.clear()
        self.recent.update(state)


class LeftEdge:
    """Где человек начинает очередную строку у левого края.

    Никто не ставит ручку каждый раз в одну и ту же клетку. Начало строки
    медленно «плывёт» на протяжении страницы (рука смещается вместе с
    тетрадью), от строки к строке немного дрожит, а изредка строка
    начинается заметно правее. Левее красного поля люди почти не заходят,
    поэтому отступ влево ограничен."""

    def __init__(self, rng: np.random.Generator, amount: float = 1.0):
        self.rng = rng
        self.amount = max(0.0, amount)
        self.drift = SmoothNoise(rng, 2.6 * self.amount, wavelengths=(23.0, 9.0, 4.0))
        self.jitter = AR1(rng, 1.0 * self.amount, keep=0.45)
        self.line = 0

    def next(self, left_room: float = 99.0) -> float:
        """Сдвиг начала следующей строки, мм (плюс — правее)."""
        a = self.amount
        off = self.drift(float(self.line)) + self.jitter.next()
        if a > 0 and self.rng.random() < 0.07:
            off += self.rng.uniform(1.5, 3.5) * min(a, 1.5)  # начал строку с запасом
        self.line += 1
        if off < 0:
            # Влево рука уходит неохотно: сжимаем и не пускаем за поле.
            off = max(0.6 * off, -left_room)
        return float(off)
