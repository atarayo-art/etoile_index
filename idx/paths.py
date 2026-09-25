"""データ置き場のパス解決とファイル名規則。

利用者データは既定で ``~/etoile-index-data/`` に置く。
環境変数 ``ETOILE_INDEX_DATA`` で変更できる。

    threads/   YYYY/YYYY-MM-DD_<project-slug>_<title-slug>.md
    projects/  <project-slug>/docs/*.md, instructions.md
    queries/   *.yaml（保存クエリ＝スマートフォルダ相当）
    .index/    index.sqlite, embeddings.sqlite, state.json
    _trash/    削除の代わりにここへ移す
"""

from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

ENV_VAR = "ETOILE_INDEX_DATA"
DEFAULT_DIR_NAME = "etoile-index-data"


def data_dir() -> Path:
    """データ置き場のルートを返す（存在は保証しない）。"""
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env).expanduser()
    return Path.home() / DEFAULT_DIR_NAME


class DataLayout:
    """データ置き場の各サブディレクトリへのアクセサ。"""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else data_dir()

    @property
    def threads(self) -> Path:
        return self.root / "threads"

    @property
    def projects(self) -> Path:
        return self.root / "projects"

    @property
    def queries(self) -> Path:
        return self.root / "queries"

    @property
    def index(self) -> Path:
        return self.root / ".index"

    @property
    def db_path(self) -> Path:
        return self.index / "index.sqlite"

    @property
    def embeddings_path(self) -> Path:
        return self.index / "embeddings.sqlite"

    @property
    def state_path(self) -> Path:
        return self.index / "state.json"

    @property
    def config_path(self) -> Path:
        return self.root / "config.yaml"

    @property
    def trash(self) -> Path:
        return self.root / "_trash"

    def ensure(self) -> None:
        for p in (self.threads, self.projects, self.queries, self.index):
            p.mkdir(parents=True, exist_ok=True)

    def document_dirs(self) -> list[Path]:
        """索引対象の Markdown が置かれるディレクトリ一覧。"""
        return [self.threads, self.projects]

    def iter_documents(self):
        """索引対象の Markdown ファイルを列挙する。"""
        for base in self.document_dirs():
            if not base.exists():
                continue
            for p in sorted(base.rglob("*.md")):
                if p.is_file():
                    yield p

    def relpath(self, path: Path) -> str:
        """ルートからの相対パス（区切りは / に統一）。"""
        try:
            return Path(path).resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return Path(path).as_posix()

    def move_to_trash(self, path: Path) -> Path:
        """削除の代わりに _trash/ へ移す（同名があれば時刻を付ける）。"""
        path = Path(path)
        self.trash.mkdir(parents=True, exist_ok=True)
        dest = self.trash / path.name
        if dest.exists():
            dest = self.trash / f"{path.stem}_{int(time.time())}{path.suffix}"
        shutil.move(str(path), str(dest))
        return dest


# ファイル名に使えない文字。区切りは `_` に統一し、`|` `｜` は使わない（利用者の命名規則）。
_UNSAFE = re.compile(r'[\\/:*?"<>|｜\s　]+')
_MULTI_US = re.compile(r"_+")


def slugify(text: str, maxlen: int = 40, default: str = "untitled") -> str:
    """ファイル名向けのスラグを作る。日本語はそのまま残す。"""
    text = (text or "").strip()
    text = _UNSAFE.sub("_", text)
    text = text.replace(".", "_")
    text = _MULTI_US.sub("_", text).strip("_")
    if not text:
        return default
    return text[:maxlen].rstrip("_") or default
