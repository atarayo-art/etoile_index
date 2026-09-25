from idx import schema


def test_roundtrip_frontmatter():
    attrs = schema.empty_attrs(
        id="abc", kind="claude.thread", title="テスト: 例", created="2026-09-14T10:32:00+09:00",
        tags=["a", "b"], summary="行1\n行2", foo="bar", turns="3",
    )
    text = schema.render_document(attrs, "## User\nこんにちは\n")
    back, body = schema.parse_frontmatter(text)
    assert back == attrs
    assert body.strip() == "## User\nこんにちは"
    assert "ci:x_foo" in text


def test_unknown_keys_become_extension_attrs():
    a = schema.normalize({"id": "1", "custom": "v", "x_already": 2})
    assert a["x_custom"] == "v" and a["x_already"] == 2


def test_datetime_string_not_converted_by_yaml():
    text = schema.render_document(schema.empty_attrs(id="1", created="2026-01-02T03:04:05+09:00"), "")
    back, _ = schema.parse_frontmatter(text)
    assert back["created"] == "2026-01-02T03:04:05+09:00"


def test_no_frontmatter():
    attrs, body = schema.parse_frontmatter("plain text")
    assert attrs == {} and body == "plain text"
