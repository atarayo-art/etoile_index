from pathlib import Path

from idx.document import read_document
from idx.importers import importers_for
from idx.ingest import import_source
from idx.paths import DataLayout, slugify
from idx.config import load_config


def test_slugify_no_pipe_or_spaces():
    assert slugify("a | b｜c d/e") == "a_b_c_d_e"
    assert slugify("") == "untitled"


def test_importers_detected_for_zip(export_zip):
    names = [i.name for i in importers_for(export_zip)]
    assert names == ["claude_export", "claude_project_docs"]


def test_import_writes_threads_and_project_docs(data_root, export_zip):
    layout = DataLayout(data_root)
    cfg = load_config(layout.config_path)
    r = import_source(export_zip, layout, cfg)
    assert (r.new, r.updated, r.skipped) == (7, 0, 0)
    threads = sorted(p.name for p in (layout.threads).rglob("*.md"))
    assert threads == [
        "2025-12-01_no-project_無題.md",
        "2026-04-10_青空商店_Webリニューアル_青空商店_サイト刷新の方針整理.md",
        "2026-05-02_山川市_観光パンフレット_小規模事業者向け補助金の申請メモ.md",
        "2026-06-15_青空商店_Webリニューアル_青空商店_補助金で写真撮影をまかなえるか.md",
    ]
    assert (layout.projects / "青空商店_Webリニューアル" / "instructions.md").exists()
    assert (layout.projects / "青空商店_Webリニューアル" / "docs" / "ブランドガイド_md.md").exists()

    attrs, body = read_document(layout.threads / "2026" / "2026-04-10_青空商店_Webリニューアル_青空商店_サイト刷新の方針整理.md")
    assert attrs["id"] == "11111111-1111-4111-8111-111111111111"
    assert attrs["kind"] == "claude.thread"
    assert attrs["project"] == "青空商店 Webリニューアル"
    assert attrs["org"] == "EXAMPLE-A"                 # config の org_rules
    assert attrs["created"] == "2026-04-10T10:32:00+09:00"   # UTC → JST
    assert attrs["people"] == ["田中さん"]
    assert attrs["turns"] == 1
    assert attrs["url"].endswith(attrs["id"])
    assert "## User (2026-04-10 10:32)" in body and "## Claude (2026-04-10 10:33)" in body
    assert "### 添付: 要望メモ.txt" in body and "営業時間をトップに大きく" in body


def test_reimport_skips_unchanged_and_preserves_curated(data_root, export_zip):
    layout = DataLayout(data_root)
    cfg = load_config(layout.config_path)
    import_source(export_zip, layout, cfg)
    p = layout.threads / "2026" / "2026-06-15_青空商店_Webリニューアル_青空商店_補助金で写真撮影をまかなえるか.md"
    attrs, body = read_document(p)
    attrs["tags"] = ["補助金"]
    attrs["summary"] = "手で書いた要点"
    attrs["recall_count"] = 3
    from idx.document import write_document
    write_document(p, attrs, body)

    r = import_source(export_zip, layout, cfg)
    assert (r.new, r.updated, r.skipped) == (0, 0, 7)

    r = import_source(export_zip, layout, cfg, force=True)
    assert (r.new, r.updated, r.skipped) == (0, 7, 0)
    attrs2, _ = read_document(p)
    assert attrs2["tags"] == ["補助金"] and attrs2["summary"] == "手で書いた要点" and attrs2["recall_count"] == 3


def test_content_block_messages_and_missing_project(data_root, export_dir):
    layout = DataLayout(data_root)
    import_source(export_dir, layout, load_config(layout.config_path))
    attrs, body = read_document(layout.threads / "2026" / "2026-05-02_山川市_観光パンフレット_小規模事業者向け補助金の申請メモ.md")
    assert "経費は印刷費・デザイン費・写真撮影費の3区分" in body   # content[] 形式のメッセージ
    attrs, _ = read_document(layout.threads / "2025" / "2025-12-01_no-project_無題.md")
    assert attrs["project"] == "" and attrs["org"] == "個人"
