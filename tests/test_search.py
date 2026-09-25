from idx.query import parse
from idx.rank import score_hits
from idx.watch import reindex


def titles(hits):
    return [h["title"] for h in hits]


def test_cross_project_fulltext(index):
    hits = index.find("補助金")
    assert {h["project"] for h in hits} == {"青空商店 Webリニューアル", "山川市 観光パンフレット"}
    assert all("[補助金]" in h["snippet"] for h in hits)


def test_attribute_filters(index):
    assert titles(index.find("補助金 project:青空")) == ["青空商店 補助金で写真撮影をまかなえるか"]
    assert titles(index.find("org:EXAMPLE-B kind:claude.thread")) == ["小規模事業者向け補助金の申請メモ"]
    assert titles(index.find("people:田中さん")) == ["青空商店 サイト刷新の方針整理"]
    assert titles(index.find("補助金 -project:青空")) == ["小規模事業者向け補助金の申請メモ"]


def test_date_range(index):
    assert titles(index.find("補助金 after:2026-06")) == ["青空商店 補助金で写真撮影をまかなえるか"]
    assert titles(index.find("補助金 before:2026-05-31")) == ["小規模事業者向け補助金の申請メモ"]


def test_short_term_falls_back_to_like(index):
    # trigram は2文字に当たらないので LIKE で拾う
    hits = index.find("旅行")
    assert titles(hits) == ["無題"] and "[旅行]" in hits[0]["snippet"]


def test_phrase_and_exclusion(index):
    assert titles(index.find('"写真撮影費を補助金"')) == ["青空商店 補助金で写真撮影をまかなえるか"]
    assert "青空商店 補助金で写真撮影をまかなえるか" not in titles(index.find("補助金 -写真撮影"))


def test_project_docs_are_searchable(index):
    hits = index.find("丸ゴシック")
    assert titles(hits) == ["ブランドガイド.md"] and hits[0]["kind"] == "claude.project_doc"


def test_tag_and_note_reindex(index):
    index.tag("3333", ["補助金", "写真"], [])
    assert titles(index.find("tag:写真")) == ["青空商店 補助金で写真撮影をまかなえるか"]
    index.update_attrs("3333", {"summary": "要点", "decisions": ["広報費で申請"], "keywords": ["広報費"]})
    hits = index.find("広報費")
    assert titles(hits) == ["青空商店 補助金で写真撮影をまかなえるか"]
    attrs = index.ls("33333333-3333-4333-8333-333333333333")
    assert attrs["decisions"] == ["広報費で申請"] and attrs["tags"] == ["補助金", "写真"]
    # frontmatter に書かれている（Markdown が唯一の真実）
    text = (index.layout.root / attrs["path"]).read_text(encoding="utf-8")
    assert 'ci:keywords: [広報費]' in text


def test_ranking_prefers_tag_match_and_recall(index):
    index.tag("2222", ["補助金"], [])
    hits = index.find("補助金")
    assert hits[0]["title"] == "小規模事業者向け補助金の申請メモ"
    index.tag("2222", [], ["補助金"])
    index.bump_recall("3333"); index.bump_recall("3333"); index.bump_recall("3333")
    hits = index.find("補助金")
    assert hits[0]["title"] == "青空商店 補助金で写真撮影をまかなえるか"


def test_incremental_reindex_detects_changes(index):
    r = reindex(index.store, index.layout)
    assert r.changed == 0 and r.unchanged == 7
    p = index.layout.root / index.ls("1111")["path"]
    p.write_text(p.read_text(encoding="utf-8") + "\n追記した内容 ユニークな語句XYZ\n", encoding="utf-8")
    r = reindex(index.store, index.layout)
    assert (r.added, r.updated, r.removed) == (0, 1, 0)
    assert titles(index.find("ユニークな語句")) == ["青空商店 サイト刷新の方針整理"]
    index.layout.move_to_trash(p)
    r = reindex(index.store, index.layout)
    assert r.removed == 1 and index.store.count() == 6
    assert (index.layout.trash / p.name).exists()


def test_full_rebuild(index):
    r = reindex(index.store, index.layout, full=True)
    assert r.added == 7 and index.store.count() == 7


def test_suggest_and_stats(index):
    assert index.suggest("山") == ["山川市 観光パンフレット", "山川市 観光パンフレット 指示文"]
    st = index.store.stats()
    assert st["items"] == 7 and st["by_kind"] == {"claude.thread": 4, "claude.project_doc": 3}


def test_score_hits_is_stable_without_fts():
    hits = [{"id": "a", "fts_rank": None, "updated": "2026-01-01T00:00:00+09:00", "recall_count": 0},
            {"id": "b", "fts_rank": None, "updated": "2026-06-01T00:00:00+09:00", "recall_count": 0}]
    assert [h["id"] for h in score_hits(hits, [])] == ["b", "a"]
