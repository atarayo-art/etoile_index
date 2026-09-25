"""索引ストア（``.index/index.sqlite``。Apple の .Spotlight-V100 に相当）。

- 属性は ``items`` テーブルの列、本文は FTS5 仮想テーブル ``items_fts``（trigram トークナイザ）。
- trigram は3文字未満の語に当たらないので、短い語は LIKE にフォールバックする。
- ストアは使い捨て。``idx reindex --full`` でいつでも Markdown から再構築できる。
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from . import schema
from .query import Filter, Query

SCHEMA_VERSION = 1

FTS_COLUMNS = ["title", "body", "summary", "keywords", "tags", "people", "id"]
# bm25 の列重み（FTS_COLUMNS と同順）
FTS_WEIGHTS = [5.0, 1.0, 3.0, 3.0, 3.0, 2.0, 0.0]
SNIPPET_TOKENS = 14
MIN_TRIGRAM_LEN = 3

_DDL = f"""
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL DEFAULT '',
    updated TEXT NOT NULL DEFAULT '',
    project TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    org TEXT NOT NULL DEFAULT '',
    people TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    summary TEXT NOT NULL DEFAULT '',
    decisions TEXT NOT NULL DEFAULT '[]',
    keywords TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    turns INTEGER NOT NULL DEFAULT 0,
    recall_count INTEGER NOT NULL DEFAULT 0,
    extra TEXT NOT NULL DEFAULT '{{}}',
    path TEXT NOT NULL UNIQUE,
    mtime REAL NOT NULL DEFAULT 0,
    hash TEXT NOT NULL DEFAULT '',
    body_len INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS items_kind ON items(kind);
CREATE INDEX IF NOT EXISTS items_project ON items(project);
CREATE INDEX IF NOT EXISTS items_updated ON items(updated);
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    {", ".join(c if c != "id" else "id UNINDEXED" for c in FTS_COLUMNS)},
    tokenize = 'trigram'
);
"""

_STR_FIELDS = {"kind", "title", "project", "project_id", "org", "summary", "source", "url", "path", "id"}
_LIST_FIELDS = {"people", "tags", "decisions", "keywords"}


def _fts_phrase(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def _like(term: str) -> str:
    return "%" + term.replace("%", "\\%").replace("_", "\\_") + "%"


def _split_terms(terms: Iterable[str]) -> tuple[list[str], list[str]]:
    """trigram で引ける語（3文字以上）と、LIKE に回す短い語に分ける。"""
    long_, short = [], []
    for t in terms:
        (long_ if len(t) >= MIN_TRIGRAM_LEN else short).append(t)
    return long_, short


class Store:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_DDL)
        self.conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- 書き込み ---------------------------------------------------------

    def reset(self) -> None:
        """索引を空にする（全再構築の前処理）。"""
        self.conn.execute("DELETE FROM items")
        self.conn.execute("DELETE FROM items_fts")
        self.conn.commit()

    def upsert(self, attrs: dict[str, Any], body: str, path: str, mtime: float, hash_: str) -> None:
        a = schema.normalize(attrs)
        extra = {k: v for k, v in a.items() if k.startswith("x_")}
        item_id = a["id"] or path
        with self.conn:
            # 同じパスに別 id が入っていた場合（id が振り直された等）は先に消す
            self.conn.execute("DELETE FROM items_fts WHERE id IN (SELECT id FROM items WHERE path = ? AND id != ?)", (path, item_id))
            self.conn.execute("DELETE FROM items WHERE path = ? AND id != ?", (path, item_id))
            self.conn.execute(
                """INSERT INTO items(id, kind, title, created, updated, project, project_id, org, people, tags,
                       summary, decisions, keywords, source, url, turns, recall_count, extra, path, mtime, hash, body_len)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                       kind=excluded.kind, title=excluded.title, created=excluded.created, updated=excluded.updated,
                       project=excluded.project, project_id=excluded.project_id, org=excluded.org,
                       people=excluded.people, tags=excluded.tags, summary=excluded.summary,
                       decisions=excluded.decisions, keywords=excluded.keywords, source=excluded.source,
                       url=excluded.url, turns=excluded.turns, recall_count=excluded.recall_count,
                       extra=excluded.extra, path=excluded.path, mtime=excluded.mtime, hash=excluded.hash,
                       body_len=excluded.body_len""",
                (
                    item_id, a["kind"], a["title"], a["created"], a["updated"], a["project"], a["project_id"],
                    a["org"], json.dumps(a["people"], ensure_ascii=False), json.dumps(a["tags"], ensure_ascii=False),
                    a["summary"], json.dumps(a["decisions"], ensure_ascii=False),
                    json.dumps(a["keywords"], ensure_ascii=False), a["source"], a["url"], a["turns"],
                    a["recall_count"], json.dumps(extra, ensure_ascii=False), path, mtime, hash_, len(body),
                ),
            )
            self.conn.execute("DELETE FROM items_fts WHERE id = ?", (item_id,))
            self.conn.execute(
                "INSERT INTO items_fts(title, body, summary, keywords, tags, people, id) VALUES (?,?,?,?,?,?,?)",
                (
                    a["title"], body, a["summary"], " ".join(a["keywords"]), " ".join(a["tags"]),
                    " ".join(a["people"]), item_id,
                ),
            )

    def delete_path(self, path: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM items_fts WHERE id IN (SELECT id FROM items WHERE path = ?)", (path,))
            self.conn.execute("DELETE FROM items WHERE path = ?", (path,))

    def delete_id(self, item_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM items_fts WHERE id = ?", (item_id,))
            self.conn.execute("DELETE FROM items WHERE id = ?", (item_id,))

    def increment_recall(self, item_id: str, by: int = 1) -> int:
        with self.conn:
            self.conn.execute("UPDATE items SET recall_count = recall_count + ? WHERE id = ?", (by, item_id))
        row = self.conn.execute("SELECT recall_count FROM items WHERE id = ?", (item_id,)).fetchone()
        return int(row[0]) if row else 0

    # ---- 読み取り ---------------------------------------------------------

    @staticmethod
    def _row_to_attrs(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        for k in _LIST_FIELDS:
            if isinstance(d.get(k), str):
                try:
                    d[k] = json.loads(d[k])
                except ValueError:
                    d[k] = []
        extra = d.pop("extra", "{}")
        try:
            d.update(json.loads(extra) if isinstance(extra, str) else {})
        except ValueError:
            pass
        return d

    def get(self, item_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return self._row_to_attrs(row) if row else None

    def get_by_path(self, path: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM items WHERE path = ?", (path,)).fetchone()
        return self._row_to_attrs(row) if row else None

    def resolve(self, ref: str) -> dict[str, Any] | None:
        """id・パス・id の前方一致のいずれかで1件を探す。"""
        hit = self.get(ref) or self.get_by_path(ref)
        if hit:
            return hit
        rows = self.conn.execute("SELECT * FROM items WHERE id LIKE ? OR path LIKE ? LIMIT 2", (ref + "%", "%" + ref + "%")).fetchall()
        return self._row_to_attrs(rows[0]) if len(rows) == 1 else None

    def get_body(self, item_id: str) -> str:
        row = self.conn.execute("SELECT body FROM items_fts WHERE id = ?", (item_id,)).fetchone()
        return row[0] if row else ""

    def all_paths(self) -> dict[str, tuple[float, str, str]]:
        """path → (mtime, hash, id)。差分検出に使う。"""
        return {
            r["path"]: (r["mtime"], r["hash"], r["id"])
            for r in self.conn.execute("SELECT path, mtime, hash, id FROM items")
        }

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0])

    def stats(self) -> dict[str, Any]:
        c = self.conn
        by_kind = {r[0]: r[1] for r in c.execute("SELECT kind, COUNT(*) FROM items GROUP BY kind ORDER BY 2 DESC")}
        by_project = {r[0] or "(なし)": r[1] for r in c.execute("SELECT project, COUNT(*) FROM items GROUP BY project ORDER BY 2 DESC LIMIT 50")}
        by_org = {r[0] or "(なし)": r[1] for r in c.execute("SELECT org, COUNT(*) FROM items GROUP BY org ORDER BY 2 DESC")}
        tags: dict[str, int] = {}
        for r in c.execute("SELECT tags FROM items"):
            for t in json.loads(r[0] or "[]"):
                tags[t] = tags.get(t, 0) + 1
        body_total = int(c.execute("SELECT COALESCE(SUM(body_len),0) FROM items").fetchone()[0])
        size = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "items": self.count(),
            "by_kind": by_kind,
            "by_project": by_project,
            "by_org": by_org,
            "tags": dict(sorted(tags.items(), key=lambda kv: -kv[1])[:50]),
            "body_chars": body_total,
            "db_bytes": size,
        }

    def suggest(self, prefix: str, limit: int = 10) -> list[str]:
        """入力補完: タイトル・タグ・人物名・プロジェクト名から前方一致で候補を返す。"""
        prefix = prefix.strip().lower()
        if not prefix:
            return []
        cands: dict[str, int] = {}
        for r in self.conn.execute("SELECT title, project, tags, people, keywords FROM items"):
            pool = [r[0], r[1]] + json.loads(r[2] or "[]") + json.loads(r[3] or "[]") + json.loads(r[4] or "[]")
            for s in pool:
                if s and str(s).lower().startswith(prefix):
                    cands[str(s)] = cands.get(str(s), 0) + 1
        return [s for s, _ in sorted(cands.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]

    # ---- 検索 -------------------------------------------------------------

    @staticmethod
    def _filter_sql(f: Filter) -> tuple[str, list[Any]]:
        col = f.field
        if col in _LIST_FIELDS:
            sql = f"EXISTS (SELECT 1 FROM json_each(i.{col}) WHERE lower(value) = lower(?))"
            params: list[Any] = [f.value]
        elif col in ("id", "kind"):
            sql = f"lower(i.{col}) = lower(?)"
            params = [f.value]
        elif col in _STR_FIELDS:
            sql = f"instr(lower(i.{col}), lower(?)) > 0"
            params = [f.value]
        else:  # 拡張属性 x_*
            sql = "instr(lower(json_extract(i.extra, ?)), lower(?)) > 0"
            params = ["$." + (col if col.startswith("x_") else "x_" + col), f.value]
        if f.negate:
            sql = f"NOT ({sql})"
        return sql, params

    def search(self, query: Query, limit: int = 20, candidates: int | None = None) -> list[dict[str, Any]]:
        """クエリを実行し、attrs に ``fts_rank`` / ``snippet`` を付けた候補を返す（未ランク）。"""
        where: list[str] = []
        params: list[Any] = []
        for f in query.filters:
            sql, p = self._filter_sql(f)
            where.append(sql)
            params.extend(p)
        if query.after:
            where.append("i.created >= ?")
            params.append(query.after)
        if query.before:
            where.append("substr(i.created, 1, ?) <= ?")
            params.extend([len(query.before), query.before])
        if query.updated_after:
            where.append("i.updated >= ?")
            params.append(query.updated_after)
        if query.updated_before:
            where.append("substr(i.updated, 1, ?) <= ?")
            params.extend([len(query.updated_before), query.updated_before])

        long_terms, short_terms = _split_terms(query.terms)
        long_not, short_not = _split_terms(query.not_terms)
        for t in short_terms:
            where.append("(f.title LIKE ? ESCAPE '\\' OR f.body LIKE ? ESCAPE '\\' OR f.summary LIKE ? ESCAPE '\\' OR f.tags LIKE ? ESCAPE '\\' OR f.people LIKE ? ESCAPE '\\' OR f.keywords LIKE ? ESCAPE '\\')")
            params.extend([_like(t)] * 6)
        for t in short_not:
            where.append("NOT (f.title LIKE ? ESCAPE '\\' OR f.body LIKE ? ESCAPE '\\')")
            params.extend([_like(t)] * 2)

        match = ""
        if long_terms or long_not:
            parts = [_fts_phrase(t) for t in long_terms]
            expr = " AND ".join(parts) if parts else ""
            for t in long_not:
                expr = (expr + " NOT " + _fts_phrase(t)) if expr else f"NOT {_fts_phrase(t)}"
            if not parts:
                # FTS5 は単独の NOT を許さないので、全件から除外する形にする
                expr = " AND ".join(f"NOT {_fts_phrase(t)}" for t in long_not)
                # 全件を対象にするために LIKE 側で除外する
                for t in long_not:
                    where.append("NOT (f.title LIKE ? ESCAPE '\\' OR f.body LIKE ? ESCAPE '\\')")
                    params.extend([_like(t)] * 2)
                expr = ""
            match = expr

        cand_limit = candidates or max(limit * 5, 100)
        weights = ", ".join(str(w) for w in FTS_WEIGHTS)
        if match:
            sql = (
                f"SELECT i.*, bm25(items_fts, {weights}) AS fts_rank, "
                f"snippet(items_fts, 1, '[', ']', '…', {SNIPPET_TOKENS}) AS snippet "
                "FROM items_fts f JOIN items i ON i.id = f.id WHERE items_fts MATCH ?"
            )
            params = [match] + params
            if where:
                sql += " AND " + " AND ".join(where)
            sql += " ORDER BY fts_rank LIMIT ?"
        else:
            sql = "SELECT i.*, NULL AS fts_rank, substr(f.body, 1, 120) AS snippet FROM items i JOIN items_fts f ON f.id = i.id"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY i.updated DESC LIMIT ?"
        params.append(cand_limit)
        rows = self.conn.execute(sql, params).fetchall()
        hits = []
        for r in rows:
            d = self._row_to_attrs(r)
            if not match and short_terms:
                d["snippet"] = self._manual_snippet(d["id"], short_terms[0])
            d["snippet"] = _clean_snippet(d.get("snippet") or "")
            hits.append(d)
        return hits

    def _manual_snippet(self, item_id: str, term: str, width: int = 60) -> str:
        body = self.get_body(item_id)
        pos = body.lower().find(term.lower())
        if pos < 0:
            return body[:width]
        start = max(0, pos - width // 2)
        end = min(len(body), pos + len(term) + width // 2)
        return ("…" if start > 0 else "") + body[start:pos] + "[" + body[pos:pos + len(term)] + "]" + body[pos + len(term):end] + ("…" if end < len(body) else "")


_WS = re.compile(r"\s+")


def _clean_snippet(s: str) -> str:
    return _WS.sub(" ", s).strip()
