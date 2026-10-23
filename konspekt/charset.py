"""Что именно просим написать в бланке образцов.

Строчные буквы нужны в нескольких вариантах: именно разнообразие реальных
образцов даёт живой вид. Частые короткие слова пишутся целиком, чтобы
сохранить настоящие соединения букв.
"""

from dataclasses import dataclass

RU_LOWER = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
RU_UPPER = RU_LOWER.upper()
LAT_LOWER = "abcdefghijklmnopqrstuvwxyz"
DIGITS = "0123456789"
PUNCT = ".,:;!?-()\"«»—→+=%/"

# Частые слова и буквосочетания (однобуквенные слова уже есть среди букв).
COMMON_WORDS = [
    "на", "не", "что", "это", "то", "по", "как", "для", "при", "от", "из",
    "или", "но", "его", "их", "все", "так", "же", "есть", "был", "она",
    "они", "ст", "ен", "ов", "пр", "ни", "ти", "ос", "ра", "ло", "ть",
]

# Стили: body — обычный текст, heading — печатные заглавные для заголовков.
BODY = "body"
HEADING = "heading"


@dataclass(frozen=True)
class SampleRequest:
    text: str
    style: str = BODY

    @property
    def is_word(self) -> bool:
        return len(self.text) > 1


def sample_requests() -> list[SampleRequest]:
    reqs: list[SampleRequest] = []
    for ch in RU_LOWER:
        reqs += [SampleRequest(ch)] * 3
    for ch in RU_UPPER:
        reqs += [SampleRequest(ch)] * 2
    for ch in DIGITS:
        reqs += [SampleRequest(ch)] * 2
    for ch in PUNCT:
        reqs += [SampleRequest(ch)] * 2
    for ch in LAT_LOWER:
        reqs.append(SampleRequest(ch))
    for ch in RU_UPPER:
        reqs.append(SampleRequest(ch, HEADING))
    seen = set()
    for w in COMMON_WORDS:
        if w in seen:
            continue
        seen.add(w)
        reqs += [SampleRequest(w)] * (2 if len(w) <= 3 else 1)
    return reqs


# Буквы по убыванию частоты в русских текстах.
RU_BY_FREQUENCY = "оеаинтсрвлкмдпуяыьгзбчйхжшюцщэфъё"

EXTRA_CLUSTERS = [
    "ст", "но", "то", "на", "ен", "ов", "ни", "ра", "во", "ко", "ал", "пр",
    "ро", "ре", "ли", "ер", "не", "ть", "по", "ог", "од", "ан", "ен", "ет",
    "ия", "ие", "ой", "ый", "ых", "ое", "ая", "ие", "ся", "ть", "ие",
]

EXTRA_WORDS = [
    "который", "также", "является", "можно", "только", "если", "когда",
    "чтобы", "между", "после", "более", "очень", "время", "человек",
    "поэтому", "например", "система", "процесс", "свойства", "виды",
    "основа", "функция", "развитие", "значение", "определение",
    "внимание", "память", "мышление", "условия", "пример", "результат",
    "состояние", "характер", "деятельность", "восприятие", "ощущение",
]


def extra_requests() -> list[SampleRequest]:
    """Дополнительный бланк: ещё варианты частых букв, частые сочетания и
    слова целиком. Чем больше настоящих образцов, тем меньше повторов."""
    reqs: list[SampleRequest] = []
    for i, ch in enumerate(RU_BY_FREQUENCY):
        n = 3 if i < 12 else 2 if i < 22 else 1
        reqs += [SampleRequest(ch)] * n
    for ch in RU_UPPER:
        reqs.append(SampleRequest(ch))
    seen: set[str] = set()
    for w in EXTRA_CLUSTERS:
        if w not in seen:
            seen.add(w)
            reqs += [SampleRequest(w)] * 2
    for w in EXTRA_WORDS:
        reqs.append(SampleRequest(w))
    return reqs
