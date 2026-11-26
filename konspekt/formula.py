"""Рукописные формулы внутри $...$. Все размеры в миллиметрах."""
from dataclasses import replace
import re

import numpy as np
from typing import NamedTuple

from .layout import InkLine, WordPlan

ALIASES = dict(zip(
    "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega".split(),
    "αβγδεζηθικλμνξοπρστυφχψω"))
ALIASES.update({key.capitalize(): value.upper() for key, value in list(ALIASES.items())})
ALIASES.update(times="×", cdot="·", pm="±", approx="≈", le="≤", ge="≥", neq="≠",
               infty="∞", sum="∑", int="∫", partial="∂", nabla="∇", to="→")


class RuleStyle(NamedTuple):
    id: str
    rise: float  # подъём конца в долях высоты строчной
    sag: float   # прогиб середины относительно прямой


FRACTION_RULES = [
    RuleStyle("rising", .16, .025),
    RuleStyle("bowed", .02, .12),
    RuleStyle("falling", -.11, -.045),
    RuleStyle("arched", .07, -.10),
]


class RootStyle(NamedTuple):
    id: str
    # Крючок от начала штриха до нижней точки, относительно основания знака.
    hook: tuple
    lean: float          # ширина подъёма относительно высоты знака
    bend: float          # изгиб середины восходящего штриха
    roof: tuple[float, float, float, float]  # высоты верхнего росчерка


ROOTS = [
    RootStyle("loop", ((0, -.23), (.07, -.44), (.21, -.48), (.30, -.26), (.43, .05)),
              .22, -.08, (-.015, .045, .018, -.07)),
    RootStyle("sweep", ((0, -.29), (.26, -.54), (.38, -.49), (.47, -.18), (.63, .04)),
              .24, .06, (.025, -.055, -.03, .025)),
    RootStyle("soft", ((0, -.58), (.13, -.55), (.24, -.28), (.35, -.02), (.47, .05)),
              .17, -.05, (-.035, .04, .065, .01)),
    RootStyle("flick", ((0, -.22), (.19, -.31), (.29, -.42), (.39, -.36), (.53, .08)),
              .20, .08, (.03, -.035, .01, -.065)),
]


def rounded_stroke(knots):
    """Скруглить повороты квадратичными кривыми, не выходя за опорные точки."""
    points = [knots[0]]
    for prev, tip, following in zip(knots, knots[1:], knots[2:]):
        start = tuple(.32 * p + .68 * q for p, q in zip(prev, tip))
        end = tuple(.68 * p + .32 * q for p, q in zip(tip, following))
        for t in (0, .25, .5, .75, 1):
            points.append(tuple((1-t)**2 * a + 2*t*(1-t) * b + t*t * c
                                for a, b, c in zip(start, tip, end)))
    points.append(knots[-1])
    return points


def add(dest, part, x, y, scale=1):
    for g in part.glyphs:
        dest.glyphs.append(replace(g, x=x + g.x * scale, y=y + g.y * scale, scale=g.scale * scale))
    for line in part.lines:
        dest.lines.append(InkLine([(x + a * scale, y + b * scale) for a, b in line.points],
                                  line.width_mm * scale))
    dest.width = max(dest.width, x + part.width * scale)


def bounds(box):
    ys = [y for line in box.lines for _, y in line.points] or [0.]
    for g in box.glyphs:
        ys.extend((g.y - g.sample.baseline * g.scale, g.y + (g.sample.height - g.sample.baseline) * g.scale))
    return min(ys), max(ys)


def empty():
    return WordPlan([], [], 0., None)


class Formula:
    def __init__(self, source, setter, style):
        self.tokens = re.findall(r"\\[A-Za-z]+|\\.|.", source)
        self.i = 0
        self.setter = setter
        self.style = style
        self.xh = setter.xh_mm

    def sample_path(self, symbol):
        variants = self.setter.p.variants(symbol)
        if not variants:
            return None
        sample = self.setter.picker.pick("formula:sample:" + symbol, variants)
        mask = self.setter.p.image(sample) > .35
        columns = np.flatnonzero(mask.any(axis=0))
        if len(columns) < 4:
            return None
        x = np.linspace(columns[0], columns[-1], min(48, len(columns)))
        y = np.interp(x, columns, [np.median(np.flatnonzero(mask[:, col])) for col in columns])
        return (x - x[0]) / (x[-1] - x[0]), (y - y.mean()) / (x[-1] - x[0])

    def rule_points(self, x, y, width, style):
        # Мягкая дуга. У длинных черт прогиб ограничен высотой почерка.
        amplitude = min(self.xh, .55 * width) * self.setter.s.neatness
        return [(x + t * width, y + amplitude * (-style.rise * t + 4 * style.sag * t * (1 - t)))
                for t in (0, .2, .4, .6, .8, 1)]

    def atom(self, depth):
        if depth > 24 or self.i >= len(self.tokens):
            raise ValueError("Ожидался аргумент формулы")
        token = self.tokens[self.i]
        self.i += 1
        if token == "{":
            group = self.row(depth + 1)
            if self.i >= len(self.tokens) or self.tokens[self.i] != "}":
                raise ValueError("Не закрыта группа")
            self.i += 1
            return group
        if token == "}":
            raise ValueError("Лишняя скобка")
        if token == "=":
            # Скан может потерять один из штрихов на направляющей бланка.
            # В формулах сохраняем обе линии и просвет даже у толстой ручки.
            width = self.xh * self.setter.rng.uniform(1.0, 1.25)
            stroke = self.setter._stroke()
            gap = max(.38 * self.xh, 2 * stroke * self.setter.s.weight)
            style = self.setter.picker.pick("formula:equals", FRACTION_RULES)
            upper = self.rule_points(0, -.5 * self.xh - gap / 2, width, style)
            dx = self.setter.rng.uniform(0, .06 * self.xh)
            lower = [(x + dx, y + gap) for x, y in upper]
            return WordPlan([], [], width + dx, None, [InkLine(upper, stroke), InkLine(lower, stroke)])
        if token == r"\frac":
            num, den = self.argument(depth), self.argument(depth)
            box = empty()
            scale = .84
            w = scale * max(num.width, den.width) + .6 * self.xh
            y, gap = -.45 * self.xh, .2 * self.xh
            style = self.setter.picker.pick("formula:bar", FRACTION_RULES)
            rule = self.rule_points(0, y, w, style)
            sample = self.sample_path("―")
            if sample is not None:
                sx, sy = sample
                rule = list(zip(sx * w, y + np.clip(sy * w, -.22*self.xh, .22*self.xh)))
            heights = [py for _, py in rule]
            add(box, num, (w - scale*num.width)/2, min(heights) - gap - scale*bounds(num)[1], scale)
            add(box, den, (w - scale*den.width)/2, max(heights) + gap - scale*bounds(den)[0], scale)
            box.lines.append(InkLine(rule, self.setter._stroke()))
            box.width = w
            return box
        if token == r"\sqrt":
            term = self.argument(depth)
            box = empty()
            top, bottom = bounds(term)
            h = self.xh
            sample = self.sample_path("√")
            if sample is not None:
                sx, sy = sample
                valley = int(sy.argmax())
                if np.ptp(sy) > .08 and valley < len(sy) - 2:
                    target = sy.min() + .16 * np.ptp(sy)
                    tops = np.flatnonzero(sy[valley+1:] <= target)
                    if len(tops):
                        corner = min(valley + 1 + int(tops[0]), len(sx)-2)
                        shoulder = .85*h + .18*(bottom-top)
                        add(box, term, shoulder + .18*h, 0)
                        box.width += .2*h
                        xs = np.interp(sx, [0, sx[corner], 1], [0, shoulder, box.width])
                        ys = top - .30*h + (sy - sy.min()) / np.ptp(sy) * (bottom - top + .30*h)
                        ys[corner:] = np.minimum(ys[corner:], top - .14*h)
                        box.lines.append(InkLine(list(zip(xs, ys)), self.setter._stroke()))
                        return box
            style = self.setter.picker.pick("formula:root", ROOTS)
            hook = [(px * h, bottom + py * h) for px, py in style.hook]
            foot_x, foot_y = hook[-1]
            roof_y = top - .30 * h - max(style.roof) * h
            height = foot_y - roof_y
            run = .30 * h + style.lean * height
            shoulder = foot_x + run
            add(box, term, shoulder + .18 * h, 0)
            box.width += .20 * h
            # Изгиб подъёма масштабируется вместе с высотой подкоренной дроби.
            stem = [(foot_x + run * (.28 + style.bend), foot_y - .28 * height),
                    (foot_x + run * (.72 + .5 * style.bend), foot_y - .73 * height)]
            span = box.width - shoulder
            roof = [(shoulder + t * span, roof_y + offset * h)
                    for t, offset in zip((0, .25, .64, 1), style.roof)]
            # Короткая точка перед плечом ограничивает скругление даже у длинной крыши.
            stem.append((shoulder - .08 * h, roof[0][1] + .17 * h))
            roof.insert(1, (shoulder + min(.18 * h, .1 * span), roof[0][1] - .012 * h))
            box.lines.append(InkLine(rounded_stroke(hook + stem + roof), self.setter._stroke()))
            return box
        if token.startswith("\\"):
            name = token[1:]
            if len(name) > 1 and name not in ALIASES:
                raise ValueError("Неизвестная команда")
            token = ALIASES.get(name, name)
        if token.isspace():
            return WordPlan([], [], self.xh*.45, None)
        return self.setter.build_word(token, self.style)

    def argument(self, depth):
        while self.i < len(self.tokens) and self.tokens[self.i].isspace():
            self.i += 1
        return self.atom(depth + 1)

    def row(self, depth=0):
        box = empty()
        while self.i < len(self.tokens) and self.tokens[self.i] != "}":
            part = self.atom(depth)
            start = box.width
            add(box, part, start, 0)
            end = box.width
            while self.i < len(self.tokens) and self.tokens[self.i] in ("^", "_"):
                sup = self.tokens[self.i] == "^"
                self.i += 1
                script = self.argument(depth)
                y = bounds(part)[0] + .15*self.xh if sup else bounds(part)[1] + .4*self.xh
                add(box, script, end, y, .64)
            box.width += self.xh*.12
        return box


def build(source, setter, style, max_width):
    parser = Formula(source[1:-1], setter, style)
    try:
        box = parser.row()
        if parser.i != len(parser.tokens):
            raise ValueError("Лишняя скобка")
    except ValueError:
        return setter.build_word(source, style)
    top, bottom = bounds(box)
    scale = min(1., max_width/max(.1, box.width),
                (setter.s.page_mm[1] - setter.s.margin_top_mm - setter.s.margin_bottom_mm - 2*setter.s.line_pitch_mm)
                / max(1., bottom-top))
    pitch = setter.s.line_pitch_mm
    descender = .22 * pitch
    scale = min(scale, .90 * pitch / max(.1, bottom-top))
    shift = min(0., descender - bottom * scale)
    shift = max(shift, -.68 * pitch - top * scale)
    if scale < 1 or shift:
        fitted = empty()
        add(fitted, box, 0., shift, scale)
        box = fitted
    box.trace = source
    return box
