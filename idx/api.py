"""CLI と MCP サーバの両方から使う高水準の操作。"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

from . import schema
from .config import Config, load_config
from .document import read_document, write_document
from .paths import DataLayout
from .query import parse
from .rank import score_hits
from .store import Store
from .watch import index_file


class Index:
    """データ置き場＋索引ストアをまとめたファサード。"""

    def __init__(self, root: Path | None = None):
        self.layout = DataLayout(root)
        self.layout.ensure()
        self.config: Config = load_config(self.layout.config_path)
        self.store = Store(self.layout.db_path)

    def close(self) -> None:
        self.store.close()

    # ---- 検索 -------------------------------------------------------------

    def find(self, query_text: str, limit: int = 20) -> list[dict[str, Any]]:
        q = parse(query_text)
        hits = self.store.search(q, limit=limit)
        ranked = score_hits(hits, q.terms)
        return ranked[:limit]

    def suggest(self, prefix: str, limit: int = 10) -> list[str]:
        return self.store.suggest(prefix, limit)

    # ---- 1件の操作 ----------------------------------------------------------

    def resolve_path(self, ref: str) -> Path | None:
        """id・相対パス・絶対パスのいずれかから Markdown の実パスを得る。"""
        p = Path(ref)
        if p.exists() and p.is_file():
            return p
        p2 = self.layout.root / ref
        if p2.exists() and p2.is_file():
            return p2
        rec = self.store.resolve(ref)
        if rec:
            p3 = self.layout.root / rec["path"]
            if p3.exists():
                return p3
        return None

    def ls(self, ref: str) -> dict[str, Any] | None:
        p = self.resolve_path(ref)
        if p is None:
            return None
        attrs, body = read_document(p)
        attrs["path"] = self.layout.relpath(p)
        attrs["body_chars"] = len(body)
        return attrs

    def read(self, ref: str) -> tuple[dict[str, Any], str] | None:
        p = self.resolve_path(ref)
        if p is None:
            return None
        attrs, body = read_document(p)
        attrs["path"] = self.layout.relpath(p)
        return attrs, body

    def update_attrs(self, ref: str, changes: dict[str, Any], list_mode: str = "replace") -> dict[str, Any] | None:
        """frontmatter を更新して再索引する。list_mode は "replace" か "merge"。"""
        p = self.resolve_path(ref)
        if p is None:
            return None
        attrs, body = read_document(p)
        for k, v in changes.items():
            if v is None:
                continue
            if k in schema.LIST_ATTRS and list_mode == "merge":
                cur = list(attrs.get(k) or [])
                for x in schema.coerce(k, v):
                    if x not in cur:
                        cur.append(x)
                attrs[k] = cur
            else:
                attrs[k] = schema.coerce(k, v) if k in schema.ATTR_BY_NAME else v
        write_document(p, attrs, body)
        index_file(self.store, self.layout, p)
        attrs = schema.normalize(attrs)
        attrs["path"] = self.layout.relpath(p)
        return attrs

    def tag(self, ref: str, add: list[str], remove: list[str]) -> dict[str, Any] | None:
        p = self.resolve_path(ref)
        if p is None:
            return None
        attrs, body = read_document(p)
        tags = list(attrs.get("tags") or [])
        for t in add:
            if t and t not in tags:
                tags.append(t)
        tags = [t for t in tags if t not in set(remove)]
        attrs["tags"] = tags
        write_document(p, attrs, body)
        index_file(self.store, self.layout, p)
        attrs["path"] = self.layout.relpath(p)
        return attrs

    def bump_recall(self, ref: str) -> int:
        """recall_count を1増やす（frontmatter と索引の両方）。"""
        p = self.resolve_path(ref)
        if p is None:
            return 0
        attrs, body = read_document(p)
        attrs["recall_count"] = int(attrs.get("recall_count") or 0) + 1
        write_document(p, attrs, body)
        index_file(self.store, self.layout, p)
        return attrs["recall_count"]

    def now_iso(self) -> str:
        return _dt.datetime.now(self.config.tz).replace(microsecond=0).isoformat()
