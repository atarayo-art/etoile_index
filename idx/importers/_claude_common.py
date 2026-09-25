"""claude.ai データエクスポート（zip / 展開済みディレクトリ）の共通読み取り。

エクスポート形式は変わりうるので寛容にパースする。
実物のキー名は ``idx inspect <zip>`` で確認できる。
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import zipfile
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def _find_member(zf: zipfile.ZipFile, name: str) -> str | None:
    cands = [m for m in zf.namelist() if m.rsplit("/", 1)[-1] == name and not m.startswith("__MACOSX")]
    if not cands:
        return None
    cands.sort(key=len)
    return cands[0]


def load_json(source: Path, name: str) -> Any:
    """zip または展開済みディレクトリから ``name``（例 conversations.json）を読む。無ければ None。"""
    source = Path(source)
    if source.is_dir():
        hits = sorted(source.rglob(name), key=lambda p: len(p.parts))
        if not hits:
            return None
        return json.loads(hits[0].read_text(encoding="utf-8"))
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as zf:
            member = _find_member(zf, name)
            if member is None:
                return None
            with zf.open(member) as f:
                return json.load(f)
    if source.name == name:
        return json.loads(source.read_text(encoding="utf-8"))
    return None


def has_file(source: Path, name: str) -> bool:
    source = Path(source)
    if source.is_dir():
        return any(source.rglob(name))
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as zf:
            return _find_member(zf, name) is not None
    return source.name == name


def get(d: Any, *keys: str, default: Any = None) -> Any:
    """複数候補のキーから最初に見つかった値を返す。"""
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def parse_time(v: Any, tz: ZoneInfo) -> str:
    """ISO 文字列や epoch 秒を、利用者タイムゾーンの ISO 8601 文字列にする。"""
    if v is None or v == "":
        return ""
    try:
        if isinstance(v, (int, float)):
            dt = _dt.datetime.fromtimestamp(float(v), tz=_dt.timezone.utc)
        else:
            s = str(v).strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = _dt.datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_dt.timezone.utc)
        return dt.astimezone(tz).replace(microsecond=0).isoformat()
    except (ValueError, OverflowError, OSError):
        return str(v)


def short_date(iso: str) -> str:
    return iso[:10] if iso else "0000-00-00"


def year_of(iso: str) -> str:
    return iso[:4] if iso and iso[:4].isdigit() else "0000"


# 「○○さん」「○○様」「○○氏」を人物候補として拾う（自動抽出。手動で直す前提）
_PERSON_RE = re.compile(r"([一-鿿぀-ゟ゠-ヿー々A-Za-z]{1,8}?)(さん|様|氏)(?![一-鿿])")
_PERSON_STOP = {"皆", "みな", "お客", "客", "担当者", "皆様", "各位", "お疲れ"}


def extract_people(text: str, min_count: int = 2, limit: int = 10) -> list[str]:
    counts: dict[str, int] = {}
    for m in _PERSON_RE.finditer(text):
        name = m.group(1)
        if name in _PERSON_STOP or len(name) < 2:
            continue
        counts[name + m.group(2)] = counts.get(name + m.group(2), 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [n for n, c in ranked if c >= min_count][:limit]


def project_index(projects: Any) -> dict[str, dict[str, Any]]:
    """projects.json を uuid → project dict の辞書にする。"""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(projects, list):
        return out
    for p in projects:
        if not isinstance(p, dict):
            continue
        pid = get(p, "uuid", "id", default="")
        if pid:
            out[str(pid)] = p
    return out


def resolve_project(conv: dict[str, Any], projects: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """会話からプロジェクト (id, name) を解決する。紐付けキーの候補を順に試す。"""
    pid = get(conv, "project_uuid", "project_id", default="")
    pname = ""
    proj = get(conv, "project")
    if isinstance(proj, dict):
        pid = pid or get(proj, "uuid", "id", default="")
        pname = get(proj, "name", default="")
    elif isinstance(proj, str) and proj:
        if proj in projects:
            pid = proj
        else:
            pname = proj
    pid = str(pid) if pid else ""
    if pid and pid in projects:
        pname = get(projects[pid], "name", default=pname) or pname
    return pid, str(pname or "")
