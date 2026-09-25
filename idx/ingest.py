"""取り込み（mdimport 相当）: インポータの出力を Markdown としてデータ置き場に書き出す。

- 既存ファイルがあり ``ci:updated`` が同じなら上書きしない（差分取り込み）。
- 上書きするときも、人が育てる属性（tags / summary / decisions / keywords / org / people /
  recall_count / x_*）は既存の値を保持する。
- Markdown 側が唯一の真実。索引DBの更新は ``idx reindex`` が担当する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import schema
from .config import Config
from .document import read_attrs, write_document
from .importers import Importer, Item, importers_for
from .paths import DataLayout


@dataclass
class ImportReport:
    new: int = 0
    updated: int = 0
    skipped: int = 0
    paths: list[str] = field(default_factory=list)
    importers: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.new + self.updated + self.skipped


def existing_ids(layout: DataLayout) -> dict[str, Path]:
    """データ置き場にある文書の ci:id → パス。"""
    out: dict[str, Path] = {}
    for p in layout.iter_documents():
        try:
            attrs = read_attrs(p)
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        cid = attrs.get("id")
        if cid:
            out[str(cid)] = p
    return out


def merge_curated(new_attrs: dict[str, Any], old_attrs: dict[str, Any]) -> dict[str, Any]:
    """再取り込み時に、人が育てた属性を新しい属性へ引き継ぐ。"""
    merged = dict(new_attrs)
    for k in schema.CURATED_ATTRS:
        old = old_attrs.get(k)
        if k in ("tags", "keywords", "decisions", "people"):
            seen = list(merged.get(k) or [])
            for v in old or []:
                if v not in seen:
                    seen.append(v)
            merged[k] = seen
        elif old not in (None, "", 0, []):
            merged[k] = old
    if not merged.get("project") and old_attrs.get("project"):
        merged["project"] = old_attrs["project"]
        merged["project_id"] = merged.get("project_id") or old_attrs.get("project_id", "")
    for k, v in old_attrs.items():
        if k.startswith("x_") and k not in merged:
            merged[k] = v
    return schema.normalize(merged)


def _unique_path(layout: DataLayout, relpath: str, item_id: str) -> Path:
    """推奨パスが別 id の文書に使われていれば id の先頭8文字を付けて回避する。"""
    dest = layout.root / relpath
    if dest.exists():
        try:
            other = read_attrs(dest).get("id")
        except (OSError, UnicodeDecodeError, ValueError):
            other = None
        if other and other != item_id:
            suffix = item_id.replace(":", "_")[:8]
            dest = dest.with_name(f"{dest.stem}_{suffix}{dest.suffix}")
    return dest


def ingest_item(layout: DataLayout, item: Item, known: dict[str, Path], force: bool = False) -> str:
    """1件を書き出す。戻り値は "new" / "updated" / "skipped"。"""
    item_id = str(item.attrs.get("id"))
    existing = known.get(item_id)
    if existing and existing.exists():
        old_attrs = read_attrs(existing)
        if not force and old_attrs.get("updated") == item.attrs.get("updated") and old_attrs.get("kind") == item.attrs.get("kind"):
            return "skipped"
        merged = merge_curated(item.attrs, old_attrs)
        write_document(existing, merged, item.body)
        return "updated"
    dest = _unique_path(layout, item.relpath, item_id)
    write_document(dest, item.attrs, item.body)
    known[item_id] = dest
    return "new"


def import_source(
    source: Path,
    layout: DataLayout,
    config: Config | None = None,
    importers: list[Importer] | None = None,
    force: bool = False,
    progress=None,
) -> ImportReport:
    """ソース（zip / ディレクトリ）を取り込む。"""
    layout.ensure()
    source = Path(source)
    importers = importers if importers is not None else importers_for(source, config)
    report = ImportReport()
    if not importers:
        return report
    known = existing_ids(layout)
    for imp in importers:
        report.importers.append(imp.name)
        for item in imp.iter_items(source):
            result = ingest_item(layout, item, known, force=force)
            setattr(report, result, getattr(report, result) + 1)
            if result != "skipped":
                report.paths.append(layout.relpath(known[str(item.attrs["id"])]))
            if progress:
                progress(result, item)
    return report
