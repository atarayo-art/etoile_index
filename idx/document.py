"""Markdown 文書（frontmatter＋本文）の読み書き。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from . import schema


def read_document(path: Path) -> tuple[dict[str, Any], str]:
    text = Path(path).read_text(encoding="utf-8")
    return schema.parse_frontmatter(text)


def read_attrs(path: Path) -> dict[str, Any]:
    """frontmatter だけを読む（本文が長くても先頭だけ読めばよい）。"""
    head = []
    with open(path, encoding="utf-8") as f:
        first = f.readline()
        if not first.startswith("---"):
            return {}
        head.append(first)
        for line in f:
            head.append(line)
            if line.rstrip("\r\n") == "---":
                break
    attrs, _ = schema.parse_frontmatter("".join(head))
    return attrs


def write_document(path: Path, attrs: dict[str, Any], body: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(schema.render_document(attrs, body), encoding="utf-8")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
