import shutil
import zipfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def export_dir() -> Path:
    return FIXTURES / "dummy_export"


@pytest.fixture
def export_zip(tmp_path: Path, export_dir: Path) -> Path:
    """実物と同じく zip の形で渡す（中にサブディレクトリを持たせて寛容パースも確認）。"""
    z = tmp_path / "data-2026-09-25.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for p in export_dir.iterdir():
            zf.write(p, f"export/{p.name}")
    return z


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "etoile-index-data"
    root.mkdir()
    shutil.copy(FIXTURES / "config.yaml", root / "config.yaml")
    monkeypatch.setenv("ETOILE_INDEX_DATA", str(root))
    return root


@pytest.fixture
def index(data_root: Path, export_zip: Path):
    from idx.api import Index
    from idx.ingest import import_source
    from idx.watch import reindex

    idx = Index(data_root)
    import_source(export_zip, idx.layout, idx.config)
    reindex(idx.store, idx.layout)
    yield idx
    idx.close()
