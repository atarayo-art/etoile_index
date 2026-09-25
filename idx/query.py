"""クエリ言語（mdfind 相当）。Finder の検索欄と同じ感覚で書ける。

    青空商店 補助金                   # 全文（自由語は AND）
    project:xxx tag:yyy 自由語        # 属性で絞る
    org:AAA after:2026-09-01 決定     # 期間（created を対象）
    -tag:草案  -下書き                 # 除外（属性／自由語）
    "完全一致したい 句"                # 引用符で句

フィールド名は ``ci:`` 属性名（接頭辞なし）。別名: tag→tags, keyword→keywords,
person→people, kw→keywords。
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

ALIASES = {
    "tag": "tags",
    "keyword": "keywords",
    "kw": "keywords",
    "person": "people",
    "decision": "decisions",
    "proj": "project",
}

# 自由語として扱わず、属性フィルタとして解釈するフィールド
FILTER_FIELDS = {
    "id", "kind", "title", "project", "project_id", "org", "people", "tags",
    "summary", "decisions", "keywords", "source", "url", "path",
}
DATE_FIELDS = {"after", "before", "updated_after", "updated_before"}

_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$")


@dataclass
class Filter:
    field: str
    value: str
    negate: bool = False


@dataclass
class Query:
    terms: list[str] = field(default_factory=list)        # 自由語（AND）
    not_terms: list[str] = field(default_factory=list)    # 除外語
    filters: list[Filter] = field(default_factory=list)   # 属性フィルタ
    after: str = ""            # created >= YYYY-MM-DD
    before: str = ""           # created <  YYYY-MM-DD（当日を含めるため翌日扱いにはしない。文字列比較）
    updated_after: str = ""
    updated_before: str = ""
    raw: str = ""

    @property
    def is_empty(self) -> bool:
        return not (self.terms or self.not_terms or self.filters or self.after or self.before
                    or self.updated_after or self.updated_before)

    def has_text(self) -> bool:
        return bool(self.terms or self.not_terms)


def normalize_date(value: str) -> str:
    """YYYY / YYYY-MM / YYYY-MM-DD を ISO の日付接頭辞に揃える。それ以外はそのまま。"""
    m = _DATE_RE.match(value.strip())
    if not m:
        return value.strip()
    y, mo, d = m.groups()
    parts = [y]
    if mo:
        parts.append(mo.zfill(2))
        if d:
            parts.append(d.zfill(2))
    return "-".join(parts)


def _split(q: str) -> list[str]:
    try:
        return shlex.split(q, posix=True)
    except ValueError:
        return q.split()


def parse(q: str) -> Query:
    query = Query(raw=q)
    for tok in _split(q or ""):
        if not tok:
            continue
        negate = False
        if tok.startswith("-") and len(tok) > 1:
            negate = True
            tok = tok[1:]
        if ":" in tok:
            fld, _, val = tok.partition(":")
            fld = ALIASES.get(fld.lower(), fld.lower())
            if fld in DATE_FIELDS and val:
                setattr(query, fld, normalize_date(val))
                continue
            if fld in FILTER_FIELDS and val:
                query.filters.append(Filter(fld, val, negate))
                continue
            # 未知のフィールドや "http://..." のような語は自由語として扱う
        if negate:
            query.not_terms.append(tok)
        else:
            query.terms.append(tok)
    return query
