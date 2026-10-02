"""Response correlation — DATA_MODEL.md §11.4, WORKFLOW_ENGINE.md §62.

Reuses src/response_watcher.py's `match_company`/`normalize_company`
directly (imported, not duplicated) — this is the actual signal already
proven against real Gmail traffic in production, not a new, untested
correlation strategy. Phase 1's migration found only 3/359 legacy
`responses` rows had a `job_url` match; `match_company` is why that number
is misleading as "how well correlation works" — the legacy `process_message`
already uses company-name matching (sender domain / subject / body), not
job_url, as its real signal, and only copies the matched job's URL into the
row afterward. The real effectiveness ceiling is company-name specificity
in the sender/subject/body text, not URL presence — see this module's
docstring in the Phase 6 report for the honest assessment.

§11.4's anti-false-positive rule is enforced by `match_company` itself: it
requires every token of a (usually multi-word) company name to appear
together, either in the sender domain or as a contiguous phrase in the
text — never a bare generic phrase like "no-reply" or "recommended jobs"
alone.

Only opportunities with a real application_attempts row are candidates —
§11.5: "the response watcher must not retroactively fabricate an attempt
that does not exist."
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from response_watcher import match_company  # noqa: E402 — reused, not duplicated


@dataclass(frozen=True)
class CorrelationResult:
    opportunity_id: int
    attempt_id: int | None
    company: str
    reason: str


def _candidates(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT o.opportunity_id, o.company_display, o.company_normalized,
               a.attempt_id
        FROM opportunities o
        JOIN application_attempts a ON a.opportunity_id = o.opportunity_id
        WHERE a.attempt_id = (
            SELECT MAX(a2.attempt_id) FROM application_attempts a2
            WHERE a2.opportunity_id = o.opportunity_id
        )
        """
    ).fetchall()
    return [
        {"opportunity_id": r["opportunity_id"], "attempt_id": r["attempt_id"],
         "company": r["company_display"] or r["company_normalized"]}
        for r in rows
    ]


def correlate(conn: sqlite3.Connection, from_addr: str, subject: str, body: str) -> CorrelationResult | None:
    candidates = _candidates(conn)
    if not candidates:
        return None
    matched = match_company(from_addr, subject, body, candidates)
    if matched is None:
        return None
    return CorrelationResult(
        opportunity_id=matched["opportunity_id"], attempt_id=matched["attempt_id"],
        company=matched["company"], reason="company_name_match",
    )
