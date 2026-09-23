"""
response_watcher.py — Polls Gmail (IMAP) for employer replies to submitted
applications, classifies each message deterministically, records it (with
persistent dedupe), updates the matching job's response_status, and sends an
urgent desktop notification the first time a message classifies as positive.

Reuses otp_resolver's Gmail credential loading (_get_app_password / _connect) —
never copies or logs the App Password itself.

CLI:
  python src/response_watcher.py                 # one poll, last 3 days
  python src/response_watcher.py --days 7         # one poll, last N days
  python src/response_watcher.py --loop           # poll every notify.check_every_minutes
  python src/response_watcher.py --summary        # print + notify a daily summary
"""
from __future__ import annotations

import argparse
import email
import hashlib
import logging
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import db  # noqa: E402
import notify as notify_mod  # noqa: E402
from otp_resolver import _connect, _get_app_password  # noqa: E402  (reuse, don't copy secrets)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
DAYS_DEFAULT = 3

# ---------------------------------------------------------------------------
# responses table (self-managed, persistent dedupe)
# ---------------------------------------------------------------------------

_RESPONSES_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses(
    message_id     TEXT PRIMARY KEY,
    from_addr      TEXT,
    subject        TEXT,
    received_at    TEXT,
    classification TEXT,
    job_url        TEXT,
    notified_at    TEXT
)
"""


def ensure_responses_table(conn: sqlite3.Connection) -> None:
    conn.execute(_RESPONSES_SCHEMA)
    conn.commit()


# ---------------------------------------------------------------------------
# Classification (deterministic — keyword/regex based, no LLM required)
# ---------------------------------------------------------------------------

# Automated job-alert / newsletter senders — always "other", never matched to a job.
_JOB_ALERT_SENDER_PATTERNS = [
    r"jobalerts?-noreply@",
    r"jobalerts@",
    r"@indeedalerts\.",
    r"jobs-noreply@",
    r"jobs-listings@",
    r"talent-alerts@",
]
_JOB_ALERT_TEXT_PATTERNS = [
    r"\bjob alert\b",
    r"\bjobs for you\b",
    r"\bnew jobs matching\b",
    r"\brecommended jobs\b",
]

# Rejection — checked before positive so a rejection that happens to mention
# "interview" in passing (e.g. "we won't be moving forward after the interview")
# is never misread as positive.
_REJECTION_PATTERNS = [
    r"\bunfortunately\b",
    r"not\s+(?:be\s+)?moving forward",
    r"other candidates",
    r"will not be (?:moving|proceeding)",
    r"decided not to (?:proceed|move forward)",
    r"not\s+(?:been\s+)?selected",
    r"position (?:has been|was) filled",
    r"pursue other candidates",
    r"regret to inform",
    r"we (?:have )?chosen to move forward with other",
]

# Positive — requires an actual invitation / action / explicit progression, not
# boilerplate conditional language ("if selected for interview we'll contact you").
_POSITIVE_PATTERNS = [
    r"schedule\s+(?:a|an|your)\s+(?:call|interview|chat)",
    r"invite you (?:to|for) (?:an?\s+)?interview",
    r"interview invitation",
    r"next round",
    r"move (?:you )?forward (?:with|to) (?:the )?next",
    r"calendly\.com",
    r"book a (?:time|slot|call)",
    r"select a time",
    r"(?:share|provide) your availability",
    r"your availability (?:for|to)",
    r"available for a (?:call|chat|interview)",
    r"shortlisted",
    r"take[- ]?home (?:assignment|test|challenge|project)",
    r"coding (?:test|challenge|assessment)",
    r"technical assessment",
    r"online assessment",
    r"\bhackerrank\b",
    r"\bcodility\b",
    r"complete (?:the|this) assessment",
    r"assessment (?:link|invite|invitation)",
    r"phone screen",
    r"next steps? in (?:the|your) (?:hiring|interview) process",
]

# Generic automated acknowledgement — NOT positive, even if it mentions
# "interview" only as a conditional ("if selected for an interview...").
_ACK_PATTERNS = [
    r"thank you for applying",
    r"thanks for applying",
    r"we(?:'ve| have)? received your application",
    r"application (?:has been |was )?received",
    r"we will review your application",
    r"if (?:your|you're) (?:profile|qualifications|background|experience) (?:matches|match)",
    r"if selected",
    r"this is an automated",
    r"no-?reply",
]


def _matches_any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def classify(subject: str, body: str, from_addr: str) -> str:
    """Classify a message as positive | rejection | ack | other."""
    subject = subject or ""
    body = body or ""
    from_addr = from_addr or ""
    text = f"{subject}\n{body}".lower()
    sender = from_addr.lower()

    if _matches_any(_JOB_ALERT_SENDER_PATTERNS, sender) or _matches_any(_JOB_ALERT_TEXT_PATTERNS, text):
        return "other"
    if _matches_any(_REJECTION_PATTERNS, text):
        return "rejection"
    if _matches_any(_POSITIVE_PATTERNS, text):
        return "positive"
    if _matches_any(_ACK_PATTERNS, text):
        return "ack"
    return "other"


# ---------------------------------------------------------------------------
# Company matching
# ---------------------------------------------------------------------------

_LEGAL_SUFFIXES = re.compile(r"\b(inc|llc|ltd|pvt|private|limited|gmbh|corp|co)\b\.?", re.I)


def normalize_company(name: str | None) -> str:
    text = re.sub(r"\(.*?\)|\[.*?\]", " ", (name or "").lower())
    text = _LEGAL_SUFFIXES.sub(" ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def match_company(from_addr: str, subject: str, body: str, jobs: list[dict]) -> dict | None:
    """Best-effort match of an incoming message to a submitted job by company name
    appearing in the sender domain, display name, subject, or body."""
    from_addr = from_addr or ""
    domain = from_addr.split("@")[-1].lower() if "@" in from_addr else ""
    text = f"{from_addr}\n{subject or ''}\n{(body or '')[:3000]}".lower()

    for job in jobs:
        norm = normalize_company(job.get("company"))
        if not norm:
            continue
        tokens = norm.split()
        domain_tokens = [t for t in tokens if len(t) > 2]
        if domain_tokens and domain and all(t in domain for t in domain_tokens):
            return job
        pattern = r"\b" + r"\s+".join(re.escape(t) for t in tokens) + r"\b"
        if re.search(pattern, text):
            return job
    return None


# ---------------------------------------------------------------------------
# Message processing (dedupe + job update + notify) — pure of IMAP, testable
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _update_job_response(conn: sqlite3.Connection, job_url: str, classification: str,
                          subject: str, received_at: str) -> None:
    row = conn.execute("SELECT response_status FROM jobs WHERE url = ?", (job_url,)).fetchone()
    if row is None:
        return
    current = row["response_status"]
    if current == "positive" and classification != "positive":
        return  # never downgrade a positive response
    conn.execute(
        "UPDATE jobs SET response_status = ?, response_subject = ?, response_at = ? WHERE url = ?",
        (classification, subject, received_at, job_url),
    )
    conn.commit()


def process_message(
    conn: sqlite3.Connection,
    message_id: str,
    from_addr: str,
    subject: str,
    body: str,
    received_at: str,
    jobs: list[dict],
    notify_fn=notify_mod.notify,
) -> str | None:
    """Classify + dedupe + update job + notify. Returns the classification, or
    None if this message_id was already processed (dedupe hit — no re-notify)."""
    ensure_responses_table(conn)

    if conn.execute("SELECT 1 FROM responses WHERE message_id = ?", (message_id,)).fetchone():
        return None

    classification = classify(subject, body, from_addr)
    job = match_company(from_addr, subject, body, jobs) if classification != "other" else None
    job_url = job["url"] if job else None

    conn.execute(
        "INSERT INTO responses(message_id, from_addr, subject, received_at, classification, job_url) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (message_id, from_addr, subject, received_at, classification, job_url),
    )
    conn.commit()

    if job_url and classification in ("positive", "rejection", "ack"):
        _update_job_response(conn, job_url, classification, subject, received_at)

    if classification == "positive":
        company = job["company"] if job else "an employer"
        title_line = f"{subject}" if subject else "Check your email"
        if notify_fn(f"Hermes: positive response from {company}", title_line, urgent=True):
            conn.execute(
                "UPDATE responses SET notified_at = ? WHERE message_id = ?",
                (_now_iso(), message_id),
            )
            conn.commit()

    return classification


# ---------------------------------------------------------------------------
# IMAP fetch
# ---------------------------------------------------------------------------

def _decode_mime_header(raw: str | None) -> str:
    if not raw:
        return ""
    parts = decode_header(raw)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            try:
                out.append(text.decode(enc or "utf-8", errors="ignore"))
            except (LookupError, TypeError):
                out.append(text.decode("utf-8", errors="ignore"))
        else:
            out.append(text)
    return "".join(out)


def _extract_body(msg: email.message.Message) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if "attachment" in str(part.get("Content-Disposition") or ""):
                continue
            if part.get_content_type() == "text/plain":
                try:
                    body += part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="ignore"
                    )
                except Exception:
                    continue
        if not body:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    try:
                        html = part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8", errors="ignore"
                        )
                        body += re.sub(r"<[^>]+>", " ", html)
                    except Exception:
                        continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")
        except Exception:
            body = ""
    return body


def _parse_message(msg: email.message.Message) -> tuple[str, str, str, str, str]:
    message_id = (msg.get("Message-ID") or "").strip()
    from_addr = _decode_mime_header(msg.get("From", ""))
    subject = _decode_mime_header(msg.get("Subject", ""))
    date_hdr = msg.get("Date", "")
    try:
        received_at = parsedate_to_datetime(date_hdr).isoformat()
    except Exception:
        received_at = _now_iso()
    body = _extract_body(msg)
    if not message_id:
        digest = hashlib.sha256(f"{from_addr}|{subject}|{date_hdr}".encode("utf-8", "ignore")).hexdigest()
        message_id = f"<generated-{digest}@hermes>"
    return message_id, from_addr, subject, body, received_at


def fetch_messages(imap_conn, days: int):
    """Yields (message_id, from_addr, subject, body, received_at) for INBOX
    messages received in the last `days` days. Never raises — IMAP errors are
    logged and iteration simply stops/skips."""
    try:
        imap_conn.select("INBOX")
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        typ, data = imap_conn.search(None, f'(SINCE "{since}")')
        if typ != "OK":
            logger.warning("response_watcher: IMAP search returned %s", typ)
            return
        uids = data[0].split() if data and data[0] else []
    except Exception as e:
        logger.warning("response_watcher: IMAP search failed: %s", e)
        return

    for uid in uids:
        try:
            typ, msg_data = imap_conn.fetch(uid, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg = email.message_from_bytes(msg_data[0][1])
        except Exception as e:
            logger.warning("response_watcher: fetch failed for uid %s: %s", uid, e)
            continue
        try:
            yield _parse_message(msg)
        except Exception as e:
            logger.warning("response_watcher: failed to parse message uid %s: %s", uid, e)
            continue


# ---------------------------------------------------------------------------
# Poll / loop / summary
# ---------------------------------------------------------------------------

def poll_once(days: int = DAYS_DEFAULT) -> dict:
    stats = {"scanned": 0, "new": 0, "positive": 0, "rejection": 0, "ack": 0, "other": 0, "notified": 0}

    if not _get_app_password():
        print(
            "[response_watcher] Gmail credentials not configured "
            "(GMAIL_APP_PASSWORD env var or output/gmail_app_password.txt) — skipping poll."
        )
        return stats

    imap_conn = _connect()
    if imap_conn is None:
        print("[response_watcher] Could not connect to Gmail IMAP (see log) — skipping poll.")
        return stats

    db_conn = db.get_conn()
    ensure_responses_table(db_conn)
    try:
        jobs = [
            dict(r) for r in db_conn.execute(
                "SELECT url, company, title FROM jobs WHERE status = 'submitted' AND company IS NOT NULL"
            ).fetchall()
        ]
        for message_id, from_addr, subject, body, received_at in fetch_messages(imap_conn, days):
            stats["scanned"] += 1
            classification = process_message(db_conn, message_id, from_addr, subject, body, received_at, jobs)
            if classification is None:
                continue
            stats["new"] += 1
            stats[classification] = stats.get(classification, 0) + 1
            if classification == "positive":
                row = db_conn.execute(
                    "SELECT notified_at FROM responses WHERE message_id = ?", (message_id,)
                ).fetchone()
                if row and row["notified_at"]:
                    stats["notified"] += 1
    finally:
        try:
            imap_conn.logout()
        except Exception:
            pass
        db_conn.close()

    return stats


def poll_loop(days: int, interval_minutes: int) -> None:
    print(f"[response_watcher] loop starting — every {interval_minutes} min, last {days} days each poll")
    while True:
        try:
            stats = poll_once(days)
            print(f"[response_watcher] poll: {stats}")
        except Exception as e:
            logger.error("response_watcher: poll_once raised unexpectedly: %s", e)
        try:
            time.sleep(max(1, interval_minutes) * 60)
        except KeyboardInterrupt:
            print("[response_watcher] loop stopped")
            return


def _load_config() -> dict:
    import yaml
    try:
        with open(ROOT / "config.yaml") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("response_watcher: could not read config.yaml: %s", e)
        return {}


def print_summary() -> dict:
    conn = db.get_conn()
    ensure_responses_table(conn)
    today = date.today().isoformat()

    submitted = conn.execute(
        "SELECT COALESCE(tier, 'core') AS tier, COALESCE(apply_channel, 'unknown') AS channel, "
        "COUNT(*) AS n FROM jobs WHERE status = 'submitted' AND substr(applied_at, 1, 10) = ? "
        "GROUP BY 1, 2",
        (today,),
    ).fetchall()
    failures = conn.execute(
        "SELECT status, COUNT(*) AS n FROM jobs WHERE substr(last_attempt_at, 1, 10) = ? "
        "AND status NOT IN ('submitted', 'already_applied') GROUP BY status",
        (today,),
    ).fetchall()
    responses_today = conn.execute(
        "SELECT classification, COUNT(*) AS n FROM responses WHERE substr(received_at, 1, 10) = ? "
        "GROUP BY classification",
        (today,),
    ).fetchall()
    conn.close()

    total_submitted = sum(r["n"] for r in submitted)
    total_failures = sum(r["n"] for r in failures)
    total_responses = sum(r["n"] for r in responses_today)

    lines = [f"Hermes Daily Summary — {today}", ""]
    lines.append(f"Submitted today: {total_submitted}")
    for r in submitted:
        lines.append(f"  {r['tier']} / {r['channel']}: {r['n']}")
    if not submitted:
        lines.append("  (none)")
    lines.append(f"Failures today: {total_failures}")
    for r in failures:
        lines.append(f"  {r['status']}: {r['n']}")
    if not failures:
        lines.append("  (none)")
    lines.append(f"New responses today: {total_responses}")
    for r in responses_today:
        lines.append(f"  {r['classification']}: {r['n']}")
    if not responses_today:
        lines.append("  (none)")

    text = "\n".join(lines)
    print(text)

    notified = notify_mod.notify(
        "Hermes Daily Summary",
        f"{total_submitted} submitted, {total_failures} failures, {total_responses} new responses",
        urgent=False,
    )
    return {"text": text, "notified": notified, "submitted": total_submitted,
            "failures": total_failures, "responses": total_responses}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Hermes employer response watcher")
    parser.add_argument("--loop", action="store_true", help="poll continuously")
    parser.add_argument("--summary", action="store_true", help="print + notify a daily summary")
    parser.add_argument("--days", type=int, default=DAYS_DEFAULT, help="how many days of INBOX to scan")
    args = parser.parse_args()

    db.init_db()

    if args.summary:
        print_summary()
        return

    if args.loop:
        cfg = _load_config()
        interval = int(((cfg or {}).get("notify") or {}).get("check_every_minutes", 10))
        poll_loop(args.days, interval)
        return

    stats = poll_once(args.days)
    print(
        f"[response_watcher] scanned={stats['scanned']} new={stats['new']} "
        f"positive={stats.get('positive', 0)} rejection={stats.get('rejection', 0)} "
        f"ack={stats.get('ack', 0)} other={stats.get('other', 0)} notified={stats.get('notified', 0)}"
    )


if __name__ == "__main__":
    main()
