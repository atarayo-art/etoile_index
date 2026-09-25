"""MCP サーバの起動用ランチャ。実体は idx/mcp_server.py。

    python mcp/server.py          # または: idx-mcp

このディレクトリには __init__.py を置かない（PyPI の mcp パッケージと名前が衝突するため）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from idx.mcp_server import main  # noqa: E402

if __name__ == "__main__":
    main()
