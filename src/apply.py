"""
apply.py — Submit tailored Indeed applications via DrissionPage (CDP-based, no WebDriver).
Zero API cost. Fully local.

Pipeline per job:
  1. Check daily cap
  2. Load cover letter + resolve resume
  3. Run indeed_apply.run_indeed_apply() → DrissionPage fills form deterministically
  4. Update DB status
"""
from __future__ import annotations

import argparse
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from cap_enforcer import CapExceeded, check_can_apply
from db import get_jobs_by_status, increment_daily, init_db, update_job
from indeed_apply import run_indeed_apply
from usage_guard import check_due, log_status, reset_session, schedule_resume

ROOT        = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config.yaml"
SCREENSHOTS = ROOT / "screenshots"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config() -> dict:
    return yaml.safe_load(open(CONFIG_PATH))


def make_slug(company: str, title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", f"{company}-{title}".lower())[:60].strip("-")


def read_cover_letter(rel_path: str) -> str:
    full = ROOT / rel_path
    return full.read_text().strip() if full.exists() else ""


def resolve_resume(variant: str, cfg: dict) -> str:
    resumes = cfg.get("resumes", {})
    rel = resumes.get(variant) or resumes.get("default", "resumes/resume-fullstack.pdf")
    return str(ROOT / rel)


def human_delay(cfg: dict):
    limits = cfg.get("limits", {})
    delay  = random.uniform(limits.get("min_delay_seconds", 15), limits.get("max_delay_seconds", 30))
    print(f"  [apply] Waiting {delay:.0f}s...")
    time.sleep(delay)


# ---------------------------------------------------------------------------
# Per-job application
# ---------------------------------------------------------------------------

def apply_to_job(job: dict, cfg: dict, dry_run: bool = False) -> bool:
    url     = job["url"]
    company = job["company"]
    title   = job["title"]
    board   = (job["job_board"] or "other").lower()
    slug    = make_slug(company, title)

    print(f"\n  [apply] {company} — {title}")

    try:
        check_can_apply("linkedin" if board == "linkedin" else "other")
    except CapExceeded as e:
        print(f"  [apply] CAP: {e}")
        return False

    cover_letter = read_cover_letter(job["cover_letter_path"]) if job["cover_letter_path"] else ""
    variant      = job["resume_variant"] or "fullstack"
    resume_path  = resolve_resume(variant, cfg)

    if not Path(resume_path).exists():
        resume_path = str(ROOT / cfg["resumes"]["default"])

    if dry_run:
        print(f"  [apply] DRY RUN — {url}")
        return True

    update_job(url, {"status": "applying"})
    SCREENSHOTS.mkdir(exist_ok=True)

    screenshot_path = str(SCREENSHOTS / f"{slug}.png")

    result = run_indeed_apply(url, cover_letter, resume_path, screenshot_path)

    if result.get("success"):
        update_job(url, {
            "status":          "submitted",
            "applied_at":      datetime.utcnow().isoformat(),
            "screenshot_path": result.get("screenshot"),
        })
        increment_daily("linkedin" if board == "linkedin" else "other")
        print(f"  [apply] ✓ Submitted")
        return True
    else:
        error = result.get("error", "unknown")
        update_job(url, {"status": "error", "status_reason": f"apply_error: {error}"})
        print(f"  [apply] ✗ Failed — {error[:120]}")
        return False


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _reset_stuck_applying() -> int:
    """Jobs stuck in 'applying' from a previous crashed run — reset to 'tailored'."""
    from db import get_conn
    conn = get_conn()
    cur = conn.execute(
        "UPDATE jobs SET status='tailored', status_reason='reset_from_stuck_applying' "
        "WHERE status='applying'"
    )
    conn.commit()
    count = cur.rowcount
    conn.close()
    if count:
        print(f"[apply] Reset {count} job(s) stuck in 'applying' from previous crash")
    return count


def main(limit: int | None = None, dry_run: bool = False) -> None:
    init_db()
    cfg = load_config()

    _reset_stuck_applying()

    all_tailored = get_jobs_by_status("tailored")
    jobs = [j for j in all_tailored if (j["job_board"] or "").lower() == "indeed"]
    if limit:
        jobs = jobs[:limit]

    if not jobs:
        print("[apply] No Indeed tailored jobs. Run tailor.py first.")
        return

    print(f"[apply] {len(jobs)} Indeed jobs to submit{' (DRY RUN)' if dry_run else ''}.")
    reset_session()

    success_count = 0
    fail_count    = 0

    for i, job in enumerate(jobs):
        if check_due():
            log_status()

        from cap_enforcer import remaining_today
        if remaining_today()["total_remaining"] == 0:
            print("\n[apply] Daily cap reached.")
            break

        ok = apply_to_job(dict(job), cfg, dry_run=dry_run)
        if ok:
            success_count += 1
        else:
            fail_count += 1

        if not dry_run and i < len(jobs) - 1:
            human_delay(cfg)

    print(f"\n[apply] Done — submitted: {success_count}, failed: {fail_count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit",   type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(limit=args.limit, dry_run=args.dry_run)
