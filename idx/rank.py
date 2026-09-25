"""ランキング。FTS スコアに、鮮度・利用頻度・タグ一致（Core Spotlight を踏襲）を加点する。

score = fts_norm (0..1)
      + W_FRESH  * exp(-days_since_updated / HALF_LIFE)
      + W_RECALL * min(1, log1p(recall_count) / 3)
      + W_TAG    * (クエリ語がタグ／キーワードに完全一致した数)
"""

from __future__ import annotations

import datetime as _dt
import math
from typing import Any, Iterable

W_FRESH = 0.15
W_RECALL = 0.10
W_TAG = 0.20
HALF_LIFE_DAYS = 180.0


def _days_since(iso: str, now: _dt.datetime) -> float:
    if not iso:
        return 3650.0
    try:
        dt = _dt.datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return max(0.0, (now - dt).total_seconds() / 86400.0)
    except ValueError:
        return 3650.0


def freshness(iso: str, now: _dt.datetime | None = None) -> float:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    return math.exp(-_days_since(iso, now) / HALF_LIFE_DAYS)


def recall_boost(count: int) -> float:
    return min(1.0, math.log1p(max(0, int(count or 0))) / 3.0)


def tag_hits(terms: Iterable[str], attrs: dict[str, Any]) -> int:
    pool = {str(t).lower() for t in (attrs.get("tags") or [])}
    pool |= {str(t).lower() for t in (attrs.get("keywords") or [])}
    return sum(1 for t in terms if t.lower() in pool)


def score_hits(hits: list[dict[str, Any]], terms: list[str], now: _dt.datetime | None = None) -> list[dict[str, Any]]:
    """``hits`` の各要素は attrs に加えて ``fts_rank``（bm25。小さいほど良い、None 可）を持つ。
    ``score`` を付けて降順に並べ替えて返す。"""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    ranks = [h.get("fts_rank") for h in hits if h.get("fts_rank") is not None]
    max_abs = max((abs(r) for r in ranks), default=0.0) or 1.0
    for h in hits:
        r = h.get("fts_rank")
        fts_norm = (abs(r) / max_abs) if r is not None else 0.0
        h["score"] = (
            fts_norm
            + W_FRESH * freshness(h.get("updated") or h.get("created") or "", now)
            + W_RECALL * recall_boost(h.get("recall_count") or 0)
            + W_TAG * tag_hits(terms, h)
        )
    hits.sort(key=lambda h: (-h["score"], h.get("updated") or ""), reverse=False)
    return hits
