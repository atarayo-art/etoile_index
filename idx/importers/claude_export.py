"""claude.ai データエクスポートの会話（conversations.json）を取り込むインポータ。

1会話 → ``threads/YYYY/YYYY-MM-DD_<project-slug>_<title-slug>.md``。
本文は ``## User`` / ``## Claude`` の見出しで往復を並べる（時刻付き）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from ..config import Config
from ..paths import slugify
from .. import schema
from ._claude_common import (
    extract_people,
    get,
    has_file,
    load_json,
    parse_time,
    project_index,
    resolve_project,
    short_date,
    year_of,
)
from .base import Importer, Item

CLAUDE_CHAT_URL = "https://claude.ai/chat/{id}"

_SENDER_LABEL = {
    "human": "User",
    "user": "User",
    "assistant": "Claude",
    "claude": "Claude",
    "system": "System",
}


def _message_text(msg: dict[str, Any]) -> str:
    text = get(msg, "text", default="")
    if isinstance(text, str) and text.strip():
        return text
    parts: list[str] = []
    for block in get(msg, "content", default=[]) or []:
        if isinstance(block, dict):
            if block.get("type") in (None, "text") and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif block.get("type") == "tool_result" and isinstance(block.get("content"), list):
                for sub in block["content"]:
                    if isinstance(sub, dict) and isinstance(sub.get("text"), str):
                        parts.append(sub["text"])
        elif isinstance(block, str):
            parts.append(block)
    return "\n".join(parts)


def _attachments_text(msg: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for att in get(msg, "attachments", default=[]) or []:
        if not isinstance(att, dict):
            continue
        fname = get(att, "file_name", "filename", "name", default="attachment")
        content = get(att, "extracted_content", "content", "text", default="")
        if content:
            out.append(f"### 添付: {fname}\n\n{content}")
        else:
            out.append(f"### 添付: {fname}")
    for f in get(msg, "files", default=[]) or []:
        if isinstance(f, dict):
            fname = get(f, "file_name", "filename", "name", default="")
            if fname:
                out.append(f"### ファイル: {fname}")
        elif isinstance(f, str):
            out.append(f"### ファイル: {f}")
    return out


def render_thread_body(conv: dict[str, Any], tz) -> tuple[str, int]:
    """会話 → Markdown 本文。往復数も返す。"""
    messages = get(conv, "chat_messages", "messages", default=[]) or []
    chunks: list[str] = []
    turns = 0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        sender = str(get(msg, "sender", "role", default="")).lower()
        label = _SENDER_LABEL.get(sender, sender.capitalize() or "Unknown")
        when = parse_time(get(msg, "created_at", "timestamp"), tz)
        stamp = when.replace("T", " ")[:16] if when else ""
        heading = f"## {label}" + (f" ({stamp})" if stamp else "")
        text = _message_text(msg).strip()
        parts = [heading, "", text] if text else [heading]
        parts.extend("\n" + a for a in _attachments_text(msg))
        chunks.append("\n".join(parts).rstrip() + "\n")
        if label == "User":
            turns += 1
    return "\n".join(chunks), turns


class ClaudeExportImporter(Importer):
    kind = schema.KIND_THREAD
    name = "claude_export"

    def __init__(self, config: Config | None = None):
        self.config = config or Config()

    def can_handle(self, source: Path) -> bool:
        return has_file(Path(source), "conversations.json")

    def iter_items(self, source: Path) -> Iterator[Item]:
        source = Path(source)
        conversations = load_json(source, "conversations.json") or []
        projects = project_index(load_json(source, "projects.json"))
        tz = self.config.tz
        source_label = source.name
        for conv in conversations:
            if not isinstance(conv, dict):
                continue
            item = self._convert(conv, projects, tz, source_label)
            if item is not None:
                yield item

    def _convert(self, conv: dict[str, Any], projects, tz, source_label: str) -> Item | None:
        cid = str(get(conv, "uuid", "id", default="") or "")
        if not cid:
            return None
        title = str(get(conv, "name", "title", default="") or "").strip() or "無題"
        created = parse_time(get(conv, "created_at", "created"), tz)
        updated = parse_time(get(conv, "updated_at", "updated"), tz) or created
        pid, pname = resolve_project(conv, projects)
        if not pname and cid in self.config.project_overrides:
            pname = self.config.project_overrides[cid]
        body, turns = render_thread_body(conv, tz)
        org = self.config.resolve_org(pname, title)
        attrs = schema.empty_attrs(
            id=cid,
            kind=self.kind,
            title=title,
            created=created,
            updated=updated,
            project=pname,
            project_id=pid,
            org=org,
            people=extract_people(body),
            source=source_label,
            url=CLAUDE_CHAT_URL.format(id=cid),
            turns=turns,
        )
        relpath = "threads/{year}/{date}_{proj}_{title}.md".format(
            year=year_of(created),
            date=short_date(created),
            proj=slugify(pname, 30, default="no-project"),
            title=slugify(title, 40),
        )
        return Item(attrs=attrs, body=body, relpath=relpath, meta={"conversation": conv})
