from konspekt import document as doc


def test_parse_kinds():
    blocks = doc.parse("# Заголовок\r\nАбзац  один\n\n\n- пункт\n* второй\n• третий\n\n")
    assert [b.kind for b in blocks] == [doc.HEADING, doc.PARAGRAPH, doc.GAP, doc.ITEM, doc.ITEM, doc.ITEM]
    assert blocks[0].text == "Заголовок"
    assert blocks[1].words == ["Абзац", "один"]


def test_empty_text():
    assert doc.parse("  \n\n") == []


def test_parse_numbered_center_right():
    blocks = doc.parse(">> 23.10.2026\n= Классная работа\n1. Первый вопрос\n12) Второй")
    assert [b.kind for b in blocks] == [doc.RIGHT, doc.CENTER, doc.NUMBERED, doc.NUMBERED]
    assert blocks[0].text == "23.10.2026"
    assert (blocks[2].marker, blocks[2].text) == ("1.", "Первый вопрос")
    assert blocks[3].marker == "12)"
