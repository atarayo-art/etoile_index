"""claude.ai プロジェクトの指示文と添付資料（projects.json）を取り込むインポータ。

``projects/<slug>/instructions.md`` と ``projects/<slug>/docs/<file>.md`` を生成する。
``ci:kind: claude.project_doc``。会話と同じ索引に入る（横断検索の対象）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterator

from ..config import Config
from ..paths import slugify
from .. import schema
from ._claude_common import get, has_file, load_json, parse_time
from .base import Importer, Item

CLAUDE_PROJECT_URL = "https://claude.ai/project/{id}"


class ClaudeProjectDocsImporter(Importer):
    kind = schema.KIND_PROJECT_DOC
    name = "claude_project_docs"

    def __init__(self, config: Config | None = None):
        self.config = config or Config()

    def can_handle(self, source: Path) -> bool:
        return has_file(Path(source), "projects.json")

    def iter_items(self, source: Path) -> Iterator[Item]:
        source = Path(source)
        projects = load_json(source, "projects.json") or []
        tz = self.config.tz
        for proj in projects:
            if not isinstance(proj, dict):
                continue
            yield from self._convert_project(proj, tz, source.name)

    def _base_attrs(self, proj: dict[str, Any], tz, source_label: str) -> dict[str, Any]:
        pid = str(get(proj, "uuid", "id", default="") or "")
        pname = str(get(proj, "name", "title", default="") or "").strip() or "無題プロジェクト"
        return dict(
            kind=self.kind,
            project=pname,
            project_id=pid,
            org=self.config.resolve_org(pname),
            created=parse_time(get(proj, "created_at", "created"), tz),
            updated=parse_time(get(proj, "updated_at", "updated"), tz),
            source=source_label,
            url=CLAUDE_PROJECT_URL.format(id=pid) if pid else "",
        )

    def _convert_project(self, proj: dict[str, Any], tz, source_label: str) -> Iterator[Item]:
        base = self._base_attrs(proj, tz, source_label)
        pid = base["project_id"]
        pname = base["project"]
        pslug = slugify(pname, 40, default="no-project")
        key = pid or hashlib.sha1(pname.encode("utf-8")).hexdigest()[:12]

        # 指示文（prompt_template）
        instructions = get(proj, "prompt_template", "instructions", "system_prompt", default="")
        description = get(proj, "description", default="")
        if instructions or description:
            body_parts = []
            if description:
                body_parts.append(f"## 説明\n\n{description}\n")
            if instructions:
                body_parts.append(f"## 指示文\n\n{instructions}\n")
            attrs = schema.empty_attrs(
                id=f"{key}:instructions",
                title=f"{pname} 指示文",
                **base,
            )
            yield Item(attrs=attrs, body="\n".join(body_parts), relpath=f"projects/{pslug}/instructions.md")

        # 添付資料（docs）
        for i, doc in enumerate(get(proj, "docs", "documents", "files", default=[]) or []):
            if not isinstance(doc, dict):
                continue
            fname = str(get(doc, "filename", "file_name", "name", default="") or f"doc_{i}")
            content = get(doc, "content", "text", "extracted_content", default="")
            if not isinstance(content, str):
                content = str(content)
            did = str(get(doc, "uuid", "id", default="") or "")
            doc_id = f"{key}:{did}" if did else f"{key}:{hashlib.sha1(fname.encode('utf-8')).hexdigest()[:12]}"
            attrs = schema.empty_attrs(
                id=doc_id,
                title=fname,
                **{
                    **base,
                    "created": parse_time(get(doc, "created_at", "created"), tz) or base["created"],
                    "updated": parse_time(get(doc, "updated_at", "updated", "created_at"), tz) or base["updated"],
                },
            )
            body = f"## {fname}\n\n{content}\n"
            yield Item(attrs=attrs, body=body, relpath=f"projects/{pslug}/docs/{slugify(fname, 60)}.md")
