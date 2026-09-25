"""``ci:`` 名前空間の属性スキーマ（Apple の kMDItem* に相当）。

Markdown の先頭に YAML frontmatter として平文で保持し、索引DBにも同名の列を持つ。
未知の属性は ``ci:x_<name>`` として受け入れる（拡張属性）。
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from typing import Any

import yaml

PREFIX = "ci:"


@dataclass(frozen=True)
class Attr:
    name: str
    type: str  # "str" | "datetime" | "list" | "int"
    doc: str = ""


# 順序は frontmatter の出力順にもなる。
ATTRS: list[Attr] = [
    Attr("id", "str", "一意キー（会話UUID等）"),
    Attr("kind", "str", "UTI相当。claude.thread / claude.project_doc など"),
    Attr("title", "str", "タイトル"),
    Attr("created", "datetime", "作成日時（ISO 8601）"),
    Attr("updated", "datetime", "更新日時（ISO 8601）"),
    Attr("project", "str", "プロジェクト名（属性であって壁ではない）"),
    Attr("project_id", "str", "プロジェクトUUID"),
    Attr("org", "str", "法人・区分"),
    Attr("people", "list", "登場人物（自動抽出＋手動）"),
    Attr("tags", "list", "タグ（Finderタグへ書き戻す対象）"),
    Attr("summary", "str", "3行以内の要点"),
    Attr("decisions", "list", "決定事項"),
    Attr("keywords", "list", "キーワード"),
    Attr("source", "str", "取り込み元"),
    Attr("url", "str", "元のURL"),
    Attr("turns", "int", "往復数"),
    Attr("recall_count", "int", "Claudeが参照した回数（ランキング用）"),
]

ATTR_BY_NAME: dict[str, Attr] = {a.name: a for a in ATTRS}
ATTR_NAMES: list[str] = [a.name for a in ATTRS]
LIST_ATTRS = {a.name for a in ATTRS if a.type == "list"}

# 再取り込み時に上書きせず保持する「人が育てる」属性。
CURATED_ATTRS = {"tags", "summary", "decisions", "keywords", "org", "people", "recall_count"}

KIND_THREAD = "claude.thread"
KIND_PROJECT_DOC = "claude.project_doc"

_FM_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)


def _to_iso(v: Any) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, _dt.datetime):
        return v.isoformat()
    if isinstance(v, _dt.date):
        return v.isoformat()
    return str(v)


def _to_list(v: Any) -> list:
    if v is None or v == "":
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if x is not None and str(x) != ""]
    return [str(v)]


def _to_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def coerce(name: str, value: Any) -> Any:
    """属性を型に合わせて整える。"""
    attr = ATTR_BY_NAME.get(name)
    if attr is None:
        # 拡張属性はそのまま
        return value
    if attr.type == "datetime":
        return _to_iso(value)
    if attr.type == "list":
        return _to_list(value)
    if attr.type == "int":
        return _to_int(value)
    return "" if value is None else str(value)


def normalize(attrs: dict[str, Any]) -> dict[str, Any]:
    """スキーマに沿った dict を返す。未知キーは ``x_`` 接頭辞を付けて残す。"""
    out: dict[str, Any] = {}
    for a in ATTRS:
        out[a.name] = coerce(a.name, attrs.get(a.name))
    for k, v in attrs.items():
        if k in ATTR_BY_NAME:
            continue
        key = k if k.startswith("x_") else f"x_{k}"
        out[key] = v
    return out


def empty_attrs(**overrides: Any) -> dict[str, Any]:
    return normalize(overrides)


# ---- frontmatter の読み書き -------------------------------------------------


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Markdown 文字列から (attrs, body) を取り出す。frontmatter が無ければ attrs は空。"""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    raw = yaml.safe_load(m.group(1)) or {}
    attrs: dict[str, Any] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            k = str(k)
            if k.startswith(PREFIX):
                k = k[len(PREFIX):]
            attrs[k] = v
    body = text[m.end():]
    return normalize(attrs), body


def _dump_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    s = "" if v is None else str(v)
    # 日時や特殊文字を含む文字列は必ず引用符で囲み、YAML の暗黙型変換を避ける
    return yaml.safe_dump(s, allow_unicode=True, default_style='"', width=10**6).strip()


def _dump_list(v: list) -> str:
    if not v:
        return "[]"
    return yaml.safe_dump(
        [str(x) for x in v], allow_unicode=True, default_flow_style=True, width=10**6
    ).strip()


def render_frontmatter(attrs: dict[str, Any]) -> str:
    """attrs から ``ci:`` 付きの frontmatter 文字列を生成する。"""
    attrs = normalize(attrs)
    lines = ["---"]
    keys = ATTR_NAMES + [k for k in attrs if k not in ATTR_BY_NAME]
    for k in keys:
        v = attrs.get(k)
        key = f"{PREFIX}{k}"
        if isinstance(v, (list, tuple)):
            lines.append(f"{key}: {_dump_list(list(v))}")
        elif isinstance(v, str) and "\n" in v:
            lines.append(f"{key}: |-")
            for ln in v.rstrip("\n").split("\n"):
                lines.append(f"  {ln}")
        elif isinstance(v, dict):
            dumped = yaml.safe_dump(v, allow_unicode=True, default_flow_style=True, width=10**6).strip()
            lines.append(f"{key}: {dumped}")
        else:
            lines.append(f"{key}: {_dump_scalar(v)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def render_document(attrs: dict[str, Any], body: str) -> str:
    body = body.lstrip("\n")
    return render_frontmatter(attrs) + "\n" + body
