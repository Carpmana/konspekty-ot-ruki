"""Исходный текст конспекта и его разбиение на блоки.

Простая разметка (как в Markdown):
    # Заголовок
    - пункт списка (также «* » и «• »)
    пустая строка — дополнительный отступ
Каждая непустая строка — отдельный абзац: в конспектах переносы строк
обычно значимы.
"""

from dataclasses import dataclass

HEADING = "heading"
PARAGRAPH = "paragraph"
ITEM = "item"
GAP = "gap"


@dataclass(frozen=True)
class Block:
    kind: str
    text: str = ""

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
        else:
            blocks.append(Block(PARAGRAPH, line))
    while blocks and blocks[-1].kind == GAP:
        blocks.pop()
    return blocks
