"""インポータのレジストリ。新しいソースはここに1行足す。"""

from __future__ import annotations

from pathlib import Path

from ..config import Config
from .base import Importer, Item
from .claude_export import ClaudeExportImporter
from .claude_project_docs import ClaudeProjectDocsImporter

IMPORTER_CLASSES: list[type[Importer]] = [
    ClaudeExportImporter,
    ClaudeProjectDocsImporter,
]


def all_importers(config: Config | None = None) -> list[Importer]:
    return [cls(config) for cls in IMPORTER_CLASSES]


def importers_for(source: Path, config: Config | None = None) -> list[Importer]:
    """ソースを扱えるインポータ一覧を返す。"""
    return [imp for imp in all_importers(config) if imp.can_handle(Path(source))]


__all__ = ["Importer", "Item", "IMPORTER_CLASSES", "all_importers", "importers_for"]
