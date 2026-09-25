"""ローカル埋め込み（``.index/embeddings.sqlite``）。

- モデルは sentence-transformers で動く多言語モデル。既定は ``intfloat/multilingual-e5-small``。
- チャンク単位（1往復＝ ``## `` 見出しごと、長ければ約500字で分割）で保存する。
- 依存が無い環境では ``pip install etoile-index[semantic]`` を案内する。
"""

from __future__ import annotations

import re
import sqlite3
import struct
from pathlib import Path
from typing import Callable, Iterable

DEFAULT_MODEL = "intfloat/multilingual-e5-small"
CHUNK_CHARS = 500

_DDL = """
CREATE TABLE IF NOT EXISTS chunks (
    item_id TEXT NOT NULL,
    chunk_no INTEGER NOT NULL,
    hash TEXT NOT NULL,
    text TEXT NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (item_id, chunk_no)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

_HEADING = re.compile(r"^## ", re.M)


def split_chunks(body: str, max_chars: int = CHUNK_CHARS) -> list[str]:
    """本文を往復単位で分け、長い往復はさらに max_chars ごとに切る。"""
    parts = [p.strip() for p in _HEADING.split(body) if p.strip()]
    out: list[str] = []
    for p in parts or [body.strip()]:
        if not p:
            continue
        while len(p) > max_chars:
            cut = p.rfind("\n", 0, max_chars)
            if cut < max_chars // 2:
                cut = max_chars
            out.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            out.append(p)
    return out


def pack(vec: Iterable[float]) -> bytes:
    v = list(vec)
    return struct.pack(f"<{len(v)}f", *v)


def unpack(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


class Embedder:
    """埋め込みモデルの薄いラッパ。テストでは encode を差し替えられる。"""

    def __init__(self, model_name: str = DEFAULT_MODEL, encode: Callable[[list[str]], list[list[float]]] | None = None):
        self.model_name = model_name
        self._encode = encode
        self._model = None

    def encode(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        if self._encode is not None:
            return self._encode(texts)
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:  # pragma: no cover
                raise RuntimeError("意味検索には extras が必要です: pip install 'etoile-index[semantic]'") from e
            self._model = SentenceTransformer(self.model_name)
        # e5 系は "query: " / "passage: " の接頭辞を推奨
        prefix = "query: " if is_query else "passage: "
        if "e5" in self.model_name:
            texts = [prefix + t for t in texts]
        return [list(map(float, v)) for v in self._model.encode(texts, normalize_embeddings=True)]


class EmbeddingStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.executescript(_DDL)

    def close(self) -> None:
        self.conn.close()

    def hashes(self) -> dict[str, str]:
        return {r[0]: r[1] for r in self.conn.execute("SELECT item_id, hash FROM chunks GROUP BY item_id")}

    def replace(self, item_id: str, hash_: str, chunks: list[str], vectors: list[list[float]]) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM chunks WHERE item_id = ?", (item_id,))
            self.conn.executemany(
                "INSERT INTO chunks(item_id, chunk_no, hash, text, vector) VALUES (?,?,?,?,?)",
                [(item_id, i, hash_, c, pack(v)) for i, (c, v) in enumerate(zip(chunks, vectors))],
            )

    def delete(self, item_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM chunks WHERE item_id = ?", (item_id,))

    def clear(self) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM chunks")

    def nearest(self, qvec: list[float], limit: int = 20) -> list[tuple[str, float, str]]:
        """(item_id, 類似度, チャンク本文) を類似度順に返す。文書ごとに最良チャンクのみ。"""
        best: dict[str, tuple[float, str]] = {}
        for item_id, text, blob in self.conn.execute("SELECT item_id, text, vector FROM chunks"):
            sim = cosine(qvec, unpack(blob))
            if item_id not in best or sim > best[item_id][0]:
                best[item_id] = (sim, text)
        ranked = sorted(best.items(), key=lambda kv: -kv[1][0])[:limit]
        return [(i, s, t) for i, (s, t) in ranked]


def build_embeddings(idx, model_name: str | None = None, force: bool = False, progress=None, embedder: Embedder | None = None) -> int:
    """索引にある全文書の埋め込みを作る。ハッシュが同じ文書は飛ばす。"""
    embedder = embedder or Embedder(model_name or DEFAULT_MODEL)
    es = EmbeddingStore(idx.layout.embeddings_path)
    try:
        if force:
            es.clear()
        done = es.hashes()
        known = idx.store.all_paths()
        n = 0
        ids_on_disk = set()
        for path, (mtime, h, item_id) in known.items():
            ids_on_disk.add(item_id)
            if not force and done.get(item_id) == h:
                continue
            body = idx.store.get_body(item_id)
            rec = idx.store.get(item_id) or {}
            chunks = split_chunks(body)
            if rec.get("title"):
                chunks = [rec["title"] + "\n" + (rec.get("summary") or "")] + chunks
            vectors = embedder.encode(chunks)
            es.replace(item_id, h, chunks, vectors)
            n += len(chunks)
            if progress:
                progress(f"embedded {path} ({len(chunks)} chunks)")
        for item_id in set(done) - ids_on_disk:
            es.delete(item_id)
        return n
    finally:
        es.close()
