"""Tests for scripts/funnel_report.py (read-only funnel)."""
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import funnel_report as fr  # noqa: E402

NOW = datetime(2026, 10, 7)


def make_db(path: Path, with_qual: bool, rows: list[tuple]) -> Path:
    conn = sqlite3.connect(path)
    extra = ", qual_version TEXT, qual_decision TEXT, qual_confidence REAL" if with_qual else ""
    conn.execute(
        "CREATE TABLE jobs (id INTEGER PRIMARY KEY, status TEXT, tier TEXT, "
        f"applied_at TEXT, response_status TEXT{extra})"
    )
    for row in rows:
        marks = ",".join("?" for _ in row)
        cols = "status,tier,applied_at,response_status" + (
            ",qual_version,qual_decision,qual_confidence" if with_qual else "")
        conn.execute(f"INSERT INTO jobs ({cols}) VALUES ({marks})", row)
    conn.commit()
    conn.close()
    return path


def test_runs_without_qual_columns(tmp_path):
    rows = [("submitted", "core", "2026-08-03T10:00:00", None)] * 3
    db = make_db(tmp_path / "a.db", False, rows)
    report = json.loads(fr.run(db, None, True, NOW))
    assert report["qual_decision"]["unknown"]["counts"]["n"] == 3
    assert report["overall"]["all"]["per_100"]["status"] == "INSUFFICIENT SAMPLE"


def test_rates_and_stages_with_enough_sample(tmp_path):
    rows = [("submitted", "core", "2026-08-03T10:00:00", None, "v1", "accept", 0.8)] * 26
    rows += [("submitted", "core", "2026-08-03T10:00:00", "positive", "v1", "accept", 0.8)]
    rows += [("submission_unconfirmed", "core", "2026-08-03T10:00:00", "rejection", "v1", "accept", 0.8)]
    rows += [("submitted", "core", "2026-08-03T10:00:00", "ack", "v1", "accept", 0.8)] * 2
    rows += [("filtered", "core", "2026-08-03T10:00:00", None, "v1", "accept", 0.8)]
    db = make_db(tmp_path / "b.db", True, rows)
    report = json.loads(fr.run(db, None, True, NOW))
    group = report["qual_version"]["v1"]
    assert group["counts"]["n"] == 30
    assert group["counts"]["interview"] == 1
    assert group["counts"]["engagement"] == 1
    assert group["counts"]["response"] == 4
    assert group["per_100"]["interview"] == 3.3
    assert "confidence_band" in report and ">=0.75" in report["confidence_band"]


def test_young_applications_counted_and_since_filter(tmp_path):
    rows = [("submitted", "core", "2026-10-01T10:00:00", None),
            ("submitted", "core", "2026-07-01T10:00:00", None)]
    db = make_db(tmp_path / "c.db", False, rows)
    all_report = json.loads(fr.run(db, None, True, NOW))
    assert all_report["overall"]["all"]["counts"]["young"] == 1
    since = json.loads(fr.run(db, "2026-09-01", True, NOW))
    assert since["overall"]["all"]["counts"]["n"] == 1


def test_database_is_read_only(tmp_path):
    db = make_db(tmp_path / "d.db", False, [("submitted", "core", "2026-08-03T10:00:00", None)])
    conn = fr.open_readonly(db)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM jobs")
    conn.close()


@pytest.mark.parametrize("value,band", [(None, "unknown"), (0.49, "<0.5"),
                                         (0.5, "0.5-0.75"), (0.75, ">=0.75")])
def test_confidence_band(value, band):
    assert fr.confidence_band(value) == band


def test_text_output_marks_insufficient_and_unobservable_views(tmp_path):
    db = make_db(tmp_path / "e.db", False, [("submitted", "core", "2026-08-03T10:00:00", None)])
    text = fr.run(db, None, False, NOW)
    assert "INSUFFICIENT SAMPLE" in text and "NOT OBSERVABLE" in text
