from konspekt import document as doc


def test_parse_kinds():
    blocks = doc.parse("# Заголовок\r\nАбзац  один\n\n\n- пункт\n* второй\n• третий\n\n")
    assert [b.kind for b in blocks] == [doc.HEADING, doc.PARAGRAPH, doc.GAP, doc.ITEM, doc.ITEM, doc.ITEM]
    assert blocks[0].text == "Заголовок"
    assert blocks[1].words == ["Абзац", "один"]


def test_empty_text():
    assert doc.parse("  \n\n") == []
