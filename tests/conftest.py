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


@pytest.fixture
def engine_conn():
    """A fresh in-memory v2 schema (db/migrations/0001_opportunity_model.sql)
    for Phase 2 engine tests. Fully isolated from `temp_db`/the legacy
    `jobs` schema and from the real db/applications.db."""
    from engine import db as enginedb

    conn = enginedb.connect(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def make_opportunity(engine_conn):
    """Factory fixture: insert a minimal, valid, READY opportunity into
    `engine_conn` and return its opportunity_id. Accepts field overrides."""
    from engine import db as enginedb

    def _make(canonical_key: str, candidate_channel: str = "indeed", **overrides):
        now = enginedb.now_iso()
        fields = dict(
            canonical_key=canonical_key,
            identity_version=1,
            company_normalized="acme",
            job_title_normalized="engineer",
            first_seen_at=now,
            last_observed_at=now,
            current_open_state="OPEN",
            age_basis="FIRST_SEEN_AT_FALLBACK",
            age_reference_at=now,
            age_band="0_3D",
            hard_eligibility_state="ELIGIBLE",
            fit_state="EVALUATED",
            fit_score=0.9,
            application_state="READY",
            created_at=now,
            updated_at=now,
        )
        fields.update(overrides)
        columns = ", ".join(fields.keys())
        placeholders = ", ".join("?" for _ in fields)
        cur = engine_conn.execute(
            f"INSERT INTO opportunities ({columns}) VALUES ({placeholders})",
            tuple(fields.values()),
        )
        opportunity_id = cur.lastrowid
        engine_conn.execute(
            """
            INSERT INTO work_queue (opportunity_id, ready_state, age_band, priority_score,
                                     candidate_channel, updated_at)
            VALUES (?, 'READY', ?, ?, ?, ?)
            """,
            (opportunity_id, fields["age_band"], fields["fit_score"],
             candidate_channel, now),
        )
        return opportunity_id

    return _make


@pytest.fixture
def seed_channel(engine_conn):
    def _seed(channel_key: str, status: str = "HEALTHY"):
        from engine import db as enginedb

        now = enginedb.now_iso()
        engine_conn.execute(
            """
            INSERT INTO channel_health (channel_key, scope, provider, status, updated_at)
            VALUES (?, 'global', ?, ?, ?)
            ON CONFLICT(channel_key) DO UPDATE SET status = excluded.status
            """,
            (channel_key, channel_key, status, now),
        )

    return _seed
