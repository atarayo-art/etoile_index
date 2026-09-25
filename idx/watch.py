"""差分検出と再索引（Apple の mds に相当。常駐はしない）。

- ``reindex()``: mtime とハッシュで変更ファイルを検出し、変更分だけ索引を更新する。
- ``reindex(full=True)``: 索引を捨てて ``threads/`` ``projects/`` から全再構築する。
- ``watch()``: 任意起動のポーリングループ。``Ctrl+C`` で止める。
"""

from __future__ import annotations

import datetime as _dt
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .document import file_hash, read_document
from .paths import DataLayout
from .store import Store


@dataclass
class ReindexReport:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def changed(self) -> int:
        return self.added + self.updated + self.removed


def index_file(store: Store, layout: DataLayout, path: Path) -> None:
    rel = layout.relpath(path)
    attrs, body = read_document(path)
    if not attrs.get("id"):
        attrs["id"] = rel
    store.upsert(attrs, body, rel, path.stat().st_mtime, file_hash(path))


def reindex(store: Store, layout: DataLayout, full: bool = False, progress=None) -> ReindexReport:
    report = ReindexReport()
    if full:
        store.reset()
    known = store.all_paths()
    seen: set[str] = set()
    for path in layout.iter_documents():
        rel = layout.relpath(path)
        seen.add(rel)
        try:
            st = path.stat()
            prev = known.get(rel)
            if prev is not None and abs(prev[0] - st.st_mtime) < 1e-6:
                report.unchanged += 1
                continue
            h = file_hash(path)
            if prev is not None and prev[1] == h:
                # 内容は同じで mtime だけ違う（touch など）: mtime を更新して終わり
                attrs, body = read_document(path)
                store.upsert(attrs if attrs.get("id") else {**attrs, "id": rel}, body, rel, st.st_mtime, h)
                report.unchanged += 1
                continue
            index_file(store, layout, path)
            if prev is None:
                report.added += 1
            else:
                report.updated += 1
            if progress:
                progress("added" if prev is None else "updated", rel)
        except Exception as e:  # 1ファイルの失敗で全体を止めない
            report.errors.append(f"{rel}: {e}")
    for rel in set(known) - seen:
        store.delete_path(rel)
        report.removed += 1
        if progress:
            progress("removed", rel)
    _write_state(layout, report, store.count())
    return report


def _write_state(layout: DataLayout, report: ReindexReport, count: int) -> None:
    layout.index.mkdir(parents=True, exist_ok=True)
    state = {
        "last_reindex": _dt.datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "items": count,
        "added": report.added,
        "updated": report.updated,
        "removed": report.removed,
        "errors": report.errors[:20],
    }
    layout.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def watch(store: Store, layout: DataLayout, interval: float = 30.0, on_change=None, max_loops: int | None = None) -> None:
    """ポーリングで差分再索引を繰り返す。max_loops はテスト用。"""
    loops = 0
    while True:
        report = reindex(store, layout)
        if report.changed and on_change:
            on_change(report)
        loops += 1
        if max_loops is not None and loops >= max_loops:
            return
        time.sleep(interval)
