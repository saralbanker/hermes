"""
apply.py — Submit tailored Indeed applications via browser-use + local Ollama.
Zero API cost. Fully local.

Pipeline per job:
  1. Check daily cap
  2. Load cover letter + resolve resume
  3. Build task prompt
  4. Run local_apply.run_local_apply() → browser-use + qwen3:4b drives Playwright
  5. Update DB status
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
from db import get_conn, get_jobs_by_status, increment_daily, init_db, update_job
from local_apply import run_local_apply
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
# Prompt builder
# ---------------------------------------------------------------------------

def build_prompt(job: dict, cover_letter: str, resume_path: str, cfg: dict) -> str:
    p = cfg["profile"]
    a = cfg["screening_answers"]

    # Keep prompt short — browser-use handles multi-step browsing itself
    cover_short = cover_letter[:400] if cover_letter else a.get("why_interested_template", "")[:300]

    phone_digits = re.sub(r"[^\d]", "", p["phone"])
    phone_local  = phone_digits[-10:]  # 10 digits only, no country code

    return f"""Go to {job['url']} and submit a job application for {p['name']}.

APPLICANT: {p['name']} | {p['email']} | {p['location']} | {p['years_experience']} yrs exp
PHONE: {phone_local}  ← use EXACTLY this (10 digits, no +91, no spaces)
GitHub: https://{p['github']} | Portfolio: https://{p['portfolio']}
Education: {p['education']} | Work auth: {p['work_authorization']}

COVER LETTER (paste into any motivation/cover/tell-us field):
{cover_short}

SALARY: "Open to competitive offers"
EXPERIENCE: {a.get('years_experience_total', '2')} years total, {a.get('years_experience_typescript', '2')} TypeScript, {a.get('years_experience_react', '2')} React
NOTICE: {a.get('notice_period', 'Immediately available')}
RELOCATE: {a.get('willing_to_relocate', 'Open to fully remote positions')}

RULES:
- After clicking Continue/Next, the form advances to a new page — do NOT re-fill fields you already filled
- If a field already has a value, skip it and move to the next empty field
- For file inputs, call upload_resume
- If the phone field shows a validation error, leave it blank and continue

STEPS: Click Apply → fill all empty fields → Continue through each page → Submit.
When done say SUBMITTED. If login wall or fatal error say FAILED: reason."""


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

    prompt          = build_prompt(dict(job), cover_letter, resume_path, cfg)
    screenshot_path = str(SCREENSHOTS / f"{slug}.png")

    result = run_local_apply(prompt, resume_path, screenshot_path)

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

def main(limit: int | None = None, dry_run: bool = False) -> None:
    init_db()
    cfg = load_config()

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
