"""インポータ規約（Apple の mdimporter に相当）。

新しいソース（ChatGPT export 等）は ``importers/`` にファイルを1つ足し、
``Importer`` を継承して ``kind`` / ``can_handle`` / ``iter_items`` を実装するだけでよい。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


@dataclass
class Item:
    """1文書分の取り込み結果。"""

    attrs: dict[str, Any]          # ci: 属性（接頭辞なし）
    body: str                      # Markdown 本文
    relpath: str                   # データ置き場ルートからの推奨相対パス
    meta: dict[str, Any] = field(default_factory=dict)  # インポータ固有の補足


class Importer:
    """型別インポータの抽象クラス。"""

    kind: str = ""        # 例 "claude.thread"
    name: str = ""        # 例 "claude_export"

    def can_handle(self, source: Path) -> bool:  # pragma: no cover - 抽象
        raise NotImplementedError

    def iter_items(self, source: Path) -> Iterator[Item]:  # pragma: no cover - 抽象
        raise NotImplementedError
