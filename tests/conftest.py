import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """A fresh copy of the real schema in a temp file; the real DB is never touched."""
    import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db
