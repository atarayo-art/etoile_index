"""ハイブリッド検索: FTS の順位と埋め込み類似度の順位を RRF（Reciprocal Rank Fusion）で統合する。"""

from __future__ import annotations

from typing import Any, Iterable

from ..query import parse
from ..rank import score_hits
from .embed import Embedder, EmbeddingStore

RRF_K = 60


def rrf(rankings: Iterable[list[str]], k: int = RRF_K) -> dict[str, float]:
    """複数の順位付きリストを RRF で統合し、id → スコアを返す。"""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return scores


def hybrid_find(idx, query_text: str, limit: int = 20, embedder: Embedder | None = None) -> list[dict[str, Any]]:
    q = parse(query_text)
    # 1) 全文側（属性フィルタは全文側で効かせる）
    fts_hits = score_hits(idx.store.search(q, limit=limit, candidates=limit * 5), q.terms)
    fts_ids = [h["id"] for h in fts_hits]
    by_id = {h["id"]: h for h in fts_hits}

    # 2) 意味側
    embedder = embedder or Embedder()
    es = EmbeddingStore(idx.layout.embeddings_path)
    try:
        text = " ".join(q.terms) or query_text
        qvec = embedder.encode([text], is_query=True)[0]
        near = es.nearest(qvec, limit=limit * 5)
    finally:
        es.close()
    sem_ids = []
    for item_id, sim, chunk in near:
        if q.filters or q.after or q.before:
            # 属性フィルタがあるクエリでは、全文側で通った文書だけを意味側でも採用する
            if item_id not in by_id:
                continue
        sem_ids.append(item_id)
        if item_id not in by_id:
            rec = idx.store.get(item_id)
            if rec is None:
                continue
            rec["snippet"] = chunk[:120].replace("\n", " ")
            rec["fts_rank"] = None
            by_id[item_id] = rec
        by_id[item_id]["similarity"] = sim

    fused = rrf([fts_ids, sem_ids])
    out = []
    for item_id, s in sorted(fused.items(), key=lambda kv: -kv[1]):
        h = by_id.get(item_id)
        if h is None:
            continue
        h["score"] = s
        out.append(h)
    return out[:limit]
