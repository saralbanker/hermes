"""
pipeline.py — Hermes orchestrator.

    discover → score → tailor → apply        (then response_watcher runs on its own timer)

Every stage is idempotent and DB-driven, so a crash at any point resumes on the
next run. Each stage's wall time, CPU time and peak RSS are measured and written
to output/metrics.jsonl for the status script.

Usage:
  python src/pipeline.py                     full run
  python src/pipeline.py --dry-run           everything, but appliers never click submit
  python src/pipeline.py --apply-only        only submit already-tailored jobs
  python src/pipeline.py --discover-only | --score-only | --tailor-only
  python src/pipeline.py --limit 10          cap each stage
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).parent))
from cap_enforcer import remaining_today
from db import init_db, status_counts, tier_counts_today

ROOT = Path(__file__).parent.parent
METRICS = ROOT / "output" / "metrics.jsonl"


class StageMeter:
    """Wall/CPU/peak-RSS of a stage, including child processes (Chrome, Xvfb)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.proc = psutil.Process()

    def _cpu(self) -> float:
        t = self.proc.cpu_times()
        return t.user + t.system + t.children_user + t.children_system

    def _rss_mb(self) -> float:
        procs = [self.proc] + self.proc.children(recursive=True)
        total = 0
        for p in procs:
            try:
                total += p.memory_info().rss
            except psutil.Error:
                continue  # child exited between listing and sampling
        return total / 1e6

    def __enter__(self) -> "StageMeter":
        print(f"\n{'─' * 50}\n  STAGE: {self.name}\n{'─' * 50}", flush=True)
        self.t0, self.c0, self.peak = time.time(), self._cpu(), self._rss_mb()
        self._stop = threading.Event()
        threading.Thread(target=self._sampler, daemon=True).start()
        return self

    def _sampler(self) -> None:
        while not self._stop.wait(2):
            self.sample()

    def sample(self) -> None:
        self.peak = max(self.peak, self._rss_mb())

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self.sample()
        self.result = {"stage": self.name, "wall_s": round(time.time() - self.t0, 1),
                       "cpu_s": round(self._cpu() - self.c0, 1), "peak_rss_mb": round(self.peak)}
        print(f"  [{self.name}] {self.result}", flush=True)


def run_stages(args: argparse.Namespace) -> list[dict]:
    only = [s for s in ("discover", "score", "tailor", "apply") if getattr(args, f"{s}_only")]
    stages = only or ["discover", "score", "tailor", "apply"]
    results = []
    for name in stages:
        with StageMeter(name) as meter:
            out = run_stage(name, args)
        results.append({**meter.result, **({"outcome": out} if isinstance(out, dict) else {})})
    return results


def run_stage(name: str, args: argparse.Namespace):
    if name != "discover":
        from db import collapse_duplicates
        collapsed = collapse_duplicates()  # never spend LLM or browser time twice on one role
        if collapsed:
            print(f"  [pipeline] collapsed {collapsed} duplicate listing(s)")
    if name == "discover":
        from discover import main as discover_main
        return discover_main(dry_run=args.dry_run, limit=args.limit)
    if name == "score":
        from score import main as score_main
        return score_main(limit=args.limit)
    if name == "tailor":
        from tailor import main as tailor_main
        return tailor_main(limit=args.limit, dry_run=False)
    from display import ensure_virtual_display
    print(f"  [pipeline] browsers render on virtual display {ensure_virtual_display()}")
    from apply import main as apply_main
    return apply_main(limit=args.limit, dry_run=args.dry_run, max_minutes=args.max_minutes)


def write_metrics(results: list[dict], started: float, args: argparse.Namespace) -> None:
    record = {"at": datetime.now().isoformat(timespec="seconds"), "dry_run": args.dry_run,
              "total_s": round(time.time() - started, 1), "stages": results,
              "status_counts": status_counts(), "submitted_today_by_tier": tier_counts_today()}
    METRICS.parent.mkdir(exist_ok=True)
    with METRICS.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    print(f"\n[pipeline] total {record['total_s']}s · status {record['status_counts']}")
    print(f"[pipeline] submitted today by tier: {record['submitted_today_by_tier']} · "
          f"slots left: {remaining_today()['total_remaining']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hermes job pipeline")
    stage = parser.add_mutually_exclusive_group()
    for name in ("discover", "score", "tailor", "apply"):
        stage.add_argument(f"--{name}-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="discover writes nothing; appliers fill forms but never submit")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-minutes", type=int, default=None, help="apply-stage time budget")
    return parser.parse_args()


def acquire_run_lock():
    """Same lock file as run_hermes.sh, so a manual run never overlaps a scheduled one.
    run_hermes.sh already holds it for its child and sets HERMES_LOCK_HELD=1."""
    if os.environ.get("HERMES_LOCK_HELD") == "1":
        return None
    fh = open(ROOT / "output" / "hermes.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("[pipeline] Another Hermes run is in progress (output/hermes.lock). Exiting.")
        sys.exit(0)
    os.environ["HERMES_LOCK_HELD"] = "1"  # tells apply.py no other applier can be running
    return fh  # kept open for the life of the process; the kernel releases it on exit/crash


def main() -> int:
    args = parse_args()
    _lock = acquire_run_lock()
    print(f"\n{'═' * 50}\n  HERMES — {datetime.now():%Y-%m-%d %H:%M:%S}"
          f"{'  (DRY RUN)' if args.dry_run else ''}\n{'═' * 50}")
    init_db()
    started = time.time()
    try:
        results = run_stages(args)
    except KeyboardInterrupt:
        print("\n[pipeline] Interrupted. Progress is in the DB; the next run resumes.")
        return 130
    write_metrics(results, started, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
