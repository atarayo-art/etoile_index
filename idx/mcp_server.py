"""MCP サーバ（フェーズ2）。Claude が会話中に索引を直接引けるようにする。

tools:
- search(query, limit, semantic)          → 結果 JSON
- recall(question, limit)                  → 関連スレッドの要約と抜粋（recall_count を加算）
- index_note(thread_id, summary, decisions, keywords, tags, people) → frontmatter を更新し再索引
- ls(id)                                   → 属性
- read(id, max_chars)                      → 本文
- saved_queries() / run_saved_query(name)  → 保存クエリ
- suggest(prefix)                          → 入力補完
- stats()

起動: ``idx-mcp`` または ``python mcp/server.py``。stdio で待ち受ける。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .api import Index
from . import queries as saved


def _public(h: dict[str, Any]) -> dict[str, Any]:
    keep = ["id", "kind", "title", "created", "updated", "project", "org", "people", "tags", "summary",
            "decisions", "keywords", "url", "turns", "recall_count", "path", "snippet", "score", "similarity"]
    return {k: h.get(k) for k in keep if h.get(k) not in (None, "", [], 0) or k in ("id", "title")}


def _index() -> Index:
    root = os.environ.get("ETOILE_INDEX_DATA")
    return Index(Path(root) if root else None)


def build_server():
    # mcp 2.x では FastMCP が MCPServer に改名された。両方に対応する。
    try:
        from mcp.server.mcpserver import MCPServer as FastMCP
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP
        except ImportError as e:  # pragma: no cover
            raise SystemExit("MCP サーバには extras が必要です: pip install 'etoile-index[mcp]'") from e

    mcp = FastMCP("etoile-index", instructions=(
        "Claude の過去スレッドとプロジェクト資料の索引。プロジェクトの壁を越えて全文検索できる。"
        "経緯や過去の決定を思い出すときは recall を、細かい絞り込みは search を使う。"
        "クエリ言語: 自由語（AND）, project:名前, tag:名前, org:名前, people:名前, kind:claude.thread, "
        "after:YYYY-MM-DD, before:YYYY-MM-DD, -tag:除外, \"句\"。"
    ))

    @mcp.tool()
    def search(query: str, limit: int = 10, semantic: bool = False) -> str:
        """索引を検索する。query はクエリ言語（自由語と field:value の混在）。"""
        idx = _index()
        try:
            if semantic:
                from .semantic.hybrid import hybrid_find
                hits = hybrid_find(idx, query, limit=limit)
            else:
                hits = idx.find(query, limit=limit)
            return json.dumps([_public(h) for h in hits], ensure_ascii=False)
        finally:
            idx.close()

    @mcp.tool()
    def recall(question: str, limit: int = 5, max_chars: int = 1500) -> str:
        """質問に関連するスレッドを引き、要約・決定事項・抜粋を返す。参照したスレッドの recall_count を加算する。"""
        idx = _index()
        try:
            hits = idx.find(question, limit=limit)
            out = []
            for h in hits:
                body = idx.store.get_body(h["id"])
                excerpt = _excerpt(body, question, max_chars)
                idx.bump_recall(h["id"])
                out.append({**_public(h), "excerpt": excerpt})
            return json.dumps(out, ensure_ascii=False)
        finally:
            idx.close()

    @mcp.tool()
    def index_note(
        thread_id: str,
        summary: str = "",
        decisions: list[str] | None = None,
        keywords: list[str] | None = None,
        tags: list[str] | None = None,
        people: list[str] | None = None,
        replace: bool = False,
    ) -> str:
        """スレッドの frontmatter（要点・決定事項・キーワード・タグ・人物）を更新して再索引する。"""
        idx = _index()
        try:
            changes = {"summary": summary or None, "decisions": decisions, "keywords": keywords, "tags": tags, "people": people}
            attrs = idx.update_attrs(thread_id, changes, list_mode="replace" if replace else "merge")
            if attrs is None:
                return json.dumps({"error": f"not found: {thread_id}"}, ensure_ascii=False)
            return json.dumps(_public(attrs), ensure_ascii=False)
        finally:
            idx.close()

    @mcp.tool()
    def ls(id: str) -> str:
        """1件の属性（ci:*）を返す。id はスレッドUUID、ファイルパス、id の前方一致のいずれか。"""
        idx = _index()
        try:
            attrs = idx.ls(id)
            return json.dumps(attrs or {"error": f"not found: {id}"}, ensure_ascii=False)
        finally:
            idx.close()

    @mcp.tool()
    def read(id: str, max_chars: int = 8000) -> str:
        """1件の本文（Markdown）を返す。長い場合は先頭 max_chars 文字。"""
        idx = _index()
        try:
            res = idx.read(id)
            if res is None:
                return json.dumps({"error": f"not found: {id}"}, ensure_ascii=False)
            attrs, body = res
            return json.dumps({"attrs": _public(attrs), "body": body[:max_chars], "truncated": len(body) > max_chars}, ensure_ascii=False)
        finally:
            idx.close()

    @mcp.tool()
    def saved_queries() -> str:
        """保存クエリ（スマートフォルダ）の一覧。"""
        idx = _index()
        try:
            return json.dumps(saved.list_queries(idx.layout), ensure_ascii=False)
        finally:
            idx.close()

    @mcp.tool()
    def run_saved_query(name: str, limit: int = 10) -> str:
        """保存クエリを実行する。"""
        idx = _index()
        try:
            q = saved.load_query(idx.layout, name)
            if q is None:
                return json.dumps({"error": f"not found: {name}"}, ensure_ascii=False)
            return json.dumps([_public(h) for h in idx.find(q["query"], limit=limit)], ensure_ascii=False)
        finally:
            idx.close()

    @mcp.tool()
    def suggest(prefix: str, limit: int = 10) -> str:
        """タイトル・タグ・人物名・プロジェクト名から前方一致の補完候補を返す。"""
        idx = _index()
        try:
            return json.dumps(idx.suggest(prefix, limit), ensure_ascii=False)
        finally:
            idx.close()

    @mcp.tool()
    def stats() -> str:
        """索引の件数・容量。"""
        idx = _index()
        try:
            return json.dumps(idx.store.stats(), ensure_ascii=False)
        finally:
            idx.close()

    return mcp


def _excerpt(body: str, question: str, max_chars: int) -> str:
    """質問語のうち最初に見つかった位置の前後を抜き出す。見つからなければ先頭。"""
    from .query import parse

    terms = parse(question).terms
    low = body.lower()
    pos = -1
    for t in terms:
        pos = low.find(t.lower())
        if pos >= 0:
            break
    if pos < 0:
        return body[:max_chars]
    start = max(0, pos - max_chars // 3)
    return ("…" if start else "") + body[start:start + max_chars] + ("…" if start + max_chars < len(body) else "")


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
