from idx.query import parse


def test_free_terms_and_fields():
    q = parse('青空商店 補助金 project:青空 tag:写真 -tag:草案 -下書き after:2026-05 before:2026-06-30 "写真 撮影"')
    assert q.terms == ["青空商店", "補助金", "写真 撮影"]
    assert q.not_terms == ["下書き"]
    assert [(f.field, f.value, f.negate) for f in q.filters] == [("project", "青空", False), ("tags", "写真", False), ("tags", "草案", True)]
    assert q.after == "2026-05" and q.before == "2026-06-30"


def test_aliases_and_unknown_field():
    q = parse("kw:広報費 person:田中さん http://example.com/x")
    assert {f.field for f in q.filters} == {"keywords", "people"}
    assert q.terms == ["http://example.com/x"]


def test_date_normalization():
    assert parse("after:2026-1-5").after == "2026-01-05"
    assert parse("after:2026").after == "2026"
