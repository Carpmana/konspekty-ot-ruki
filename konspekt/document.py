"""Исходный текст конспекта и его разбиение на блоки.

Простая разметка (как в Markdown):
    # Заголовок
    - пункт списка (также «* » и «• »)
    1. вопрос с номером (также «1) »)
    = строка по центру (например, «= Классная работа»)
    >> строка справа (дата на полях)
    _несколько слов_ — подчеркнуть, [[слова]] — обвести рамкой
    -> или → — стрелка, x^2 — степень, H_2O — индекс
    пустая строка — дополнительный отступ
Каждая непустая строка — отдельный абзац: в конспектах переносы строк
обычно значимы.
"""

import re
from dataclasses import dataclass

HEADING = "heading"
PARAGRAPH = "paragraph"
ITEM = "item"
GAP = "gap"
NUMBERED = "numbered"
CENTER = "center"
RIGHT = "right"

_NUMBER = re.compile(r"(\d{1,3}[.)])\s+(.*)")


@dataclass(frozen=True)
class Block:
    kind: str
    text: str = ""
    marker: str = ""  # номер вопроса: «1.»

    @property
    def words(self) -> list[str]:
        return self.text.split()


def parse(text: str) -> list[Block]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    blocks: list[Block] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            if blocks and blocks[-1].kind != GAP:
                blocks.append(Block(GAP))
            continue
        if line.startswith("#"):
            blocks.append(Block(HEADING, line.lstrip("#").strip()))
        elif line[:2] in ("- ", "* ", "• "):
            blocks.append(Block(ITEM, line[2:].strip()))
        elif line.startswith(">>"):
            blocks.append(Block(RIGHT, line[2:].strip()))
        elif line[:2] == "= ":
            blocks.append(Block(CENTER, line[2:].strip()))
        elif m := _NUMBER.fullmatch(line):
            blocks.append(Block(NUMBERED, m.group(2).strip(), m.group(1)))
        else:
            blocks.append(Block(PARAGRAPH, line))
    while blocks and blocks[-1].kind == GAP:
        blocks.pop()
    return blocks
