"""保存クエリ（スマートフォルダ相当）。``queries/<name>.yaml`` に保持する。"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

import yaml

from .paths import DataLayout, slugify


def _path(layout: DataLayout, name: str) -> Path:
    return layout.queries / f"{slugify(name, 60)}.yaml"


def save_query(layout: DataLayout, name: str, query: str, description: str = "") -> Path:
    layout.queries.mkdir(parents=True, exist_ok=True)
    p = _path(layout, name)
    data = {
        "name": name,
        "query": query,
        "description": description,
        "created": _dt.datetime.now().astimezone().replace(microsecond=0).isoformat(),
    }
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def load_query(layout: DataLayout, name: str) -> dict[str, Any] | None:
    p = _path(layout, name)
    if not p.exists():
        return None
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    data.setdefault("name", name)
    data["path"] = str(p)
    return data


def list_queries(layout: DataLayout) -> list[dict[str, Any]]:
    out = []
    if not layout.queries.exists():
        return out
    for p in sorted(layout.queries.glob("*.yaml")):
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        data.setdefault("name", p.stem)
        data["path"] = str(p)
        out.append(data)
    return out


def remove_query(layout: DataLayout, name: str) -> Path | None:
    p = _path(layout, name)
    if not p.exists():
        return None
    return layout.move_to_trash(p)
