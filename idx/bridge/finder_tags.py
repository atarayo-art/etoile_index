"""``ci:tags`` を実ファイルの Finder タグ（xattr ``com.apple.metadata:_kMDItemUserTags``）と同期する。

- 書き込み: ``tag`` コマンド（brew install tag）があればそれを使い、無ければ bplist を生成して ``xattr -w``。
- 読み込み: ``xattr -p`` で bplist を取り出して復号する。
- Mac 以外ではすべて no-op（False / 空を返す）。
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

XATTR_KEY = "com.apple.metadata:_kMDItemUserTags"


def is_mac() -> bool:
    return sys.platform == "darwin"


def encode_tags(tags: list[str]) -> bytes:
    """Finder タグの bplist（文字列配列。色は付けない＝ "名前\\n0" 形式にしない）。"""
    return plistlib.dumps([str(t) for t in tags], fmt=plistlib.FMT_BINARY)


def decode_tags(blob: bytes) -> list[str]:
    try:
        data = plistlib.loads(blob)
    except Exception:
        return []
    out = []
    for t in data if isinstance(data, list) else []:
        s = str(t)
        # Finder は "名前\n<色番号>" の形で持つことがある
        out.append(s.split("\n", 1)[0])
    return out


def write_finder_tags(path: Path, tags: list[str]) -> bool:
    if not is_mac():
        return False
    path = Path(path)
    tag_cmd = shutil.which("tag")
    try:
        if tag_cmd:
            subprocess.run([tag_cmd, "--set", ",".join(tags), str(path)], check=True, capture_output=True)
        else:
            hexblob = encode_tags(tags).hex()
            subprocess.run(["xattr", "-wx", XATTR_KEY, hexblob, str(path)], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, OSError):
        return False


def read_finder_tags(path: Path) -> list[str]:
    if not is_mac():
        return []
    try:
        res = subprocess.run(["xattr", "-px", XATTR_KEY, str(path)], check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, OSError):
        return []
    hexstr = "".join(res.stdout.split())
    try:
        return decode_tags(bytes.fromhex(hexstr))
    except ValueError:
        return []


def sync_all_tags(idx, direction: str = "to-finder") -> int:
    """全文書のタグを同期する。to-finder: frontmatter→Finder、from-finder: Finder→frontmatter。"""
    if not is_mac():
        return 0
    from ..document import read_document, write_document
    from ..watch import index_file

    n = 0
    for p in idx.layout.iter_documents():
        attrs, body = read_document(p)
        if direction == "to-finder":
            if write_finder_tags(p, list(attrs.get("tags") or [])):
                n += 1
        else:
            finder = read_finder_tags(p)
            merged = list(attrs.get("tags") or [])
            changed = False
            for t in finder:
                if t not in merged:
                    merged.append(t)
                    changed = True
            if changed:
                attrs["tags"] = merged
                write_document(p, attrs, body)
                index_file(idx.store, idx.layout, p)
                n += 1
    return n
