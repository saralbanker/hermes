"""
pipeline.py — Master orchestrator for the Hermes job automation pipeline.

Stages (in order):
  discover → score → tailor → apply

Usage:
  python src/pipeline.py                         # full pipeline
  python src/pipeline.py --dry-run               # full pipeline, no submissions
  python src/pipeline.py --discover-only         # only scrape new jobs
  python src/pipeline.py --score-only            # only score discovered jobs
  python src/pipeline.py --tailor-only           # only tailor scored jobs
  python src/pipeline.py --apply-only            # only submit tailored jobs
  python src/pipeline.py --limit 10              # cap each stage at 10 items
  python src/pipeline.py --discover-only --limit 5
"""

import sys
import argparse
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from db import init_db
from cap_enforcer import remaining_today


def print_header():
    print("\n" + "═" * 50)
    print("  HERMES — Job Application Pipeline")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═" * 50)


def print_stage(name: str):
    print(f"\n{'─' * 50}")
    print(f"  STAGE: {name}")
    print("─" * 50)


def print_summary():
    rem = remaining_today()
    print(f"\n{'═' * 50}")
    print("  PIPELINE COMPLETE")
    print(f"  LinkedIn remaining today: {rem['linkedin_remaining']}/{rem['limits']['linkedin_per_day']}")
    print(f"  Other remaining today:    {rem['other_remaining']}/{rem['limits']['other_per_day']}")
    print(f"  Total remaining today:    {rem['total_remaining']}/{rem['limits']['total_per_day']}")
    print("═" * 50)
    print("\nNext steps:")
    print("  python src/tracker.py stats          — view full stats")
    print("  python src/tracker.py list --today   — see today's applications")


def run_discover(limit: int | None, dry_run: bool):
    print_stage("DISCOVER — scraping job boards")
    from discover import main as discover_main
    discover_main(dry_run=dry_run, limit=limit)


def run_score(limit: int | None):
    print_stage("SCORE — rating jobs against your resume")
    from score import main as score_main
    score_main(limit=limit)


def run_tailor(limit: int | None, dry_run: bool):
    print_stage("TAILOR — writing cover letters")
    from tailor import main as tailor_main
    tailor_main(limit=limit, dry_run=dry_run)


def run_apply(limit: int | None, dry_run: bool):
    print_stage("APPLY — submitting applications via browser-use + local Ollama")
    if dry_run:
        print("  [pipeline] --dry-run active: applications will NOT be submitted")
    from apply import main as apply_main
    apply_main(limit=limit, dry_run=dry_run)


def main():
    parser = argparse.ArgumentParser(
        description="Hermes Job Automation Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/pipeline.py                    Full pipeline (discover→score→tailor→apply)
  python src/pipeline.py --dry-run          Full pipeline but don't submit
  python src/pipeline.py --discover-only    Only scrape new jobs
  python src/pipeline.py --apply-only --limit 5   Submit up to 5 tailored jobs
  python src/pipeline.py --score-only --limit 20  Score up to 20 discovered jobs
        """,
    )

    # Stage selectors (mutually exclusive with each other and full pipeline)
    stage = parser.add_mutually_exclusive_group()
    stage.add_argument("--discover-only", action="store_true",
                       help="Only run the discover stage")
    stage.add_argument("--score-only", action="store_true",
                       help="Only run the score stage")
    stage.add_argument("--tailor-only", action="store_true",
                       help="Only run the tailor stage")
    stage.add_argument("--apply-only", action="store_true",
                       help="Only run the apply stage")

    parser.add_argument("--dry-run", action="store_true",
                        help="Run pipeline without writing jobs to DB (discover) "
                             "or submitting applications (apply)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap items processed per stage (useful for testing)")
    parser.add_argument("--skip-discover", action="store_true",
                        help="Skip discover stage in full pipeline run")
    parser.add_argument("--skip-score", action="store_true",
                        help="Skip score stage in full pipeline run")

    args = parser.parse_args()

    print_header()
    init_db()

    # Show daily cap status upfront
    rem = remaining_today()
    print(f"\n  Daily slots — LinkedIn: {rem['linkedin_remaining']} left  "
          f"| Other: {rem['other_remaining']} left  "
          f"| Total: {rem['total_remaining']} left")

    if rem["total_remaining"] == 0 and not (
        args.discover_only or args.score_only or args.tailor_only
    ):
        print("\n  [pipeline] Daily application cap already reached.")
        print("  [pipeline] You can still run --discover-only or --score-only.")
        print("  [pipeline] Applications will resume tomorrow.")
        return

    t_start = time.time()

    try:
        if args.discover_only:
            run_discover(args.limit, args.dry_run)

        elif args.score_only:
            run_score(args.limit)

        elif args.tailor_only:
            run_tailor(args.limit, args.dry_run)

        elif args.apply_only:
            run_apply(args.limit, args.dry_run)

        else:
            # Full pipeline
            if not args.skip_discover:
                run_discover(args.limit, args.dry_run)
            if not args.skip_score:
                run_score(args.limit)
            run_tailor(args.limit, args.dry_run)
            run_apply(args.limit, args.dry_run)

    except KeyboardInterrupt:
        print("\n\n[pipeline] Interrupted by user. Progress saved to DB.")

    elapsed = time.time() - t_start
    print(f"\n[pipeline] Total runtime: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print_summary()


if __name__ == "__main__":
    main()
