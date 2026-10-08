import fcntl
import json
import sqlite3

import pytest

from dashboard import queries

TODAY = "2026-10-07"


class _Seeded:
    """Read-only connection plus an `add` helper that inserts via a separate writer."""

    def __init__(self, ro, add):
        self._ro, self.add = ro, add

    def __getattr__(self, name):
        return getattr(self._ro, name)


@pytest.fixture
def conn(temp_db):
    rw = sqlite3.connect(temp_db.DB_PATH)
    rw.row_factory = sqlite3.Row
    counter = iter(range(10_000))

    def add(**f):
        f.setdefault("company", "Acme")
        f.setdefault("title", "Engineer")
        f["url"] = f"https://x/{next(counter)}"
        cols = ", ".join(f)
        rw.execute(f"INSERT INTO jobs ({cols}) VALUES ({', '.join('?' for _ in f)})",
                   tuple(f.values()))
        rw.commit()

    ro = queries.open_readonly(temp_db.DB_PATH)
    yield _Seeded(ro, add)
    ro.close()
    rw.close()


def test_readonly_rejects_write(conn):
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO jobs (url, company, title) VALUES ('u','c','t')")


def test_applications_local_date_and_zero_fill(conn):
    conn.add(status="submitted", applied_at="2026-10-07T23:59:59.999999")
    conn.add(status="submitted", applied_at="2026-10-07T00:00:00.000001")
    conn.add(status="submitted", applied_at="2026-10-05T10:00:00.123456")
    conn.add(status="submitted", applied_at="2026-09-01T10:00:00")  # outside window
    conn.add(status="failed", applied_at="2026-10-07T10:00:00")  # not submitted
    apps = queries.get_applications(conn, TODAY, 25)
    series = apps["last_14_days"]
    assert len(series) == 14
    assert series[0]["date"] == "2026-09-24" and series[-1]["date"] == TODAY
    assert series[-1]["count"] == 2 and series[-3]["count"] == 1
    assert sum(d["count"] for d in series) == 3
    assert apps["submitted_total"] == 4
    assert apps["cap"] == {"used": 2, "limit": 25, "remaining": 23}


def test_breakdowns_fallbacks(conn):
    conn.add(status="submitted", apply_channel=None, job_board="indeed")
    conn.add(status="submitted", apply_channel="greenhouse", job_board="indeed", tier="stretch",
             resume_variant="fullstack")
    b = queries.get_breakdowns(conn)
    assert {c["name"] for c in b["by_channel"]} == {"indeed", "greenhouse"}
    assert {c["name"] for c in b["by_tier"]} == {"core", "stretch"}
    assert {c["name"] for c in b["by_variant"]} == {"unknown", "fullstack"}


def test_errors_grouping_prefix_truncation(conn):
    huge = "Form changed: " + "x\n  y " * 1000
    assert len(huge) > 5000
    conn.add(status="form_changed", status_reason=huge, last_attempt_at=f"{TODAY}T09:00:00")
    conn.add(status="form_changed", status_reason="Form changed: other",
             last_attempt_at="2026-10-05T09:00:00")
    conn.add(status="failed", status_reason=None, last_attempt_at=f"{TODAY}T10:00:00")
    conn.add(status="filtered", last_attempt_at=f"{TODAY}T10:00:00")  # not a failure
    conn.add(status="failed", status_reason="old: x", last_attempt_at="2026-09-01T10:00:00")
    conn.add(status="failed", status_reason="never attempted")  # no last_attempt_at
    err = queries.get_errors(conn, TODAY)
    assert err["today_total"] == 2
    assert {s["status"] for s in err["today_by_status"]} == {"form_changed", "failed"}
    groups = {(g["status"], g["reason_prefix"]): g["count"] for g in err["top_groups_7d"]}
    assert groups[("form_changed", "Form changed")] == 2
    assert ("failed", "") in groups and ("failed", "old") not in groups
    assert len(err["recent"]) == 4  # all attempted failures, any date
    for r in err["recent"]:
        assert len(r["reason"]) <= 120 and "\n" not in r["reason"]
    assert err["recent"][0]["status"] == "failed"  # newest first


def test_responses(conn):
    for s in ("positive", "ack", "ack", "rejection", "weird", None, None, None):
        conn.add(status="submitted", response_status=s)
    conn.add(status="failed", response_status="rejection")  # ignored
    r = queries.get_responses(conn)
    assert r["counts"] == {"positive": 1, "ack": 2, "rejection": 1, "other": 1}
    assert r["awaiting"] == 3
    assert r["response_rate"] == pytest.approx(5 / 8)


def test_responses_empty(conn):
    assert queries.get_responses(conn)["response_rate"] == 0.0


def test_lock_probe(tmp_path):
    lock = tmp_path / "hermes.lock"
    assert queries.is_lock_held(lock) is False  # missing file
    lock.touch()
    assert queries.is_lock_held(lock) is False
    with open(lock, "rb") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert queries.is_lock_held(lock) is True
    assert queries.is_lock_held(lock) is False


def test_run_state_missing_files(tmp_path):
    state = queries.read_run_state(tmp_path)
    assert state == {"is_running": False, "last_run": None, "log_tail": []}


def test_run_state_reads_tails(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    rows = [{"at": f"t{i}", "total_s": i, "status_counts": {"submitted": i}} for i in range(3)]
    (out / "metrics.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (out / "hermes_cron.log").write_text("\n".join(f"line {i}" for i in range(100)) + "\n")
    state = queries.read_run_state(tmp_path)
    assert state["last_run"] == {"at": "t2", "total_s": 2, "status_counts": {"submitted": 2}}
    assert state["log_tail"][-1] == "line 99" and len(state["log_tail"]) == 15


def test_settings_excludes_profile(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "profile:\n  email: secret@example.com\n  phone: '123'\n"
        "screening_answers:\n  q: a\n"
        "limits:\n  total_per_day: 25\n"
        "salary:\n  usd_to_inr: 88\n"
        "search:\n  min_score: 6.5\n  queries: [x]\n")
    s = queries.read_limits(tmp_path)
    assert s == {"limits": {"total_per_day": 25}, "min_score": 6.5, "salary": {"usd_to_inr": 88}}
    assert "secret@example.com" not in json.dumps(s)


def test_build_overview_shape(conn, tmp_path):
    (tmp_path / "config.yaml").write_text("limits:\n  total_per_day: 25\nsearch:\n  min_score: 7\n")
    conn.add(status="submitted", applied_at=f"{TODAY}T08:00:00")
    ov = queries.build_overview(conn, TODAY, tmp_path)
    assert set(ov) == {"today", "run", "applications", "responses", "errors", "pipeline", "settings"}
    assert set(ov["applications"]) == {"submitted_today", "cap", "submitted_total", "last_14_days",
                                       "by_channel", "by_tier", "by_variant"}
    assert ov["applications"]["cap"]["remaining"] == 24
    assert ov["pipeline"]["status_counts"] == {"submitted": 1}
