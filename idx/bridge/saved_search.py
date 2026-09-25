"""保存クエリ（queries/*.yaml）から Finder のスマートフォルダ（.savedSearch plist）を生成する。

Spotlight のクエリ言語へは次のように写す（完全な対応ではない。全文と属性の一部のみ）。

    自由語        → kMDItemTextContent == "*語*"cd || kMDItemDisplayName == "*語*"cd
    tag:x         → kMDItemUserTags == "x"cd
    -tag:x        → !(kMDItemUserTags == "x"cd)
    after:/before: → kMDItemContentCreationDate >= / <= $time.iso(...)
    project:/org: 等 → 本文の全文一致で近似（Spotlight は ci: 属性を知らないため）

検索範囲（SearchScopes）はデータ置き場ルートに限定する。
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

from ..paths import DataLayout, slugify
from ..query import Query, parse


def _q(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def to_spotlight_query(query: Query | str) -> str:
    q = parse(query) if isinstance(query, str) else query
    clauses: list[str] = []
    for t in q.terms:
        clauses.append(f'(kMDItemTextContent == "*{_q(t)}*"cd || kMDItemDisplayName == "*{_q(t)}*"cd)')
    for t in q.not_terms:
        clauses.append(f'!(kMDItemTextContent == "*{_q(t)}*"cd)')
    for f in q.filters:
        if f.field == "tags":
            c = f'kMDItemUserTags == "{_q(f.value)}"cd'
        else:
            c = f'kMDItemTextContent == "*{_q(f.value)}*"cd'
        clauses.append(f"!({c})" if f.negate else c)
    if q.after:
        clauses.append(f'kMDItemContentCreationDate >= $time.iso({q.after}T00:00:00Z)')
    if q.before:
        clauses.append(f'kMDItemContentCreationDate <= $time.iso({q.before}T23:59:59Z)')
    if not clauses:
        clauses.append('kMDItemContentType == "net.daringfireball.markdown" || kMDItemDisplayName == "*.md"cd')
    return " && ".join(clauses)


def build_saved_search(name: str, query: str, scope: Path) -> dict:
    raw = to_spotlight_query(query)
    scope_str = str(Path(scope).expanduser())
    return {
        "CompatibleVersion": 1,
        "RawQuery": raw,
        "RawQueryDict": {
            "RawQuery": raw,
            "SearchScopes": [scope_str],
            "UserQuery": query,
        },
        "SearchCriteria": {
            "FXScopeArrayOfPaths": [scope_str],
            "CurrentFolderPath": [scope_str],
        },
        "ViewOptions": {"ViewStyle": "Nlsv"},
        "etoile-index": {"name": name, "query": query},
    }


def saved_search_bytes(name: str, query: str, scope: Path) -> bytes:
    return plistlib.dumps(build_saved_search(name, query, scope), fmt=plistlib.FMT_XML)


def install_saved_search(layout: DataLayout, name: str, query: str, dest_dir: Path | None = None) -> Path | None:
    """~/Library/Saved Searches/<name>.savedSearch を書く。Mac 以外は None。dest_dir はテスト用。"""
    if dest_dir is None:
        if sys.platform != "darwin":
            return None
        dest_dir = Path.home() / "Library" / "Saved Searches"
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{slugify(name, 60)}.savedSearch"
    out.write_bytes(saved_search_bytes(name, query, layout.root))
    return out


def install_all_saved_searches(layout: DataLayout, dest_dir: Path | None = None) -> list[Path]:
    from ..queries import list_queries

    outs = []
    for q in list_queries(layout):
        p = install_saved_search(layout, q["name"], q.get("query", ""), dest_dir)
        if p:
            outs.append(p)
    return outs
