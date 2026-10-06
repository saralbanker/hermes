#!/usr/bin/env python3
"""hermes_engine_worker.py — Entry point for the Phase 5 continuous worker
(src/engine/worker.py).

Lock mechanism: the same OS primitive scripts/run_hermes.sh's `flock` uses
for the legacy path — a non-blocking exclusive lock via flock(2) on a lock
file — reused here via Python's fcntl.flock rather than inventing a
different mechanism (e.g. a pidfile-only check, which race-and-leak on an
unclean kill the way flock does not). A SEPARATE lock file
(output/hermes-engine.lock, not output/hermes.lock) is used because this is
a genuinely separate process from the legacy pipeline — the orchestrator
decides, at cutover, whether the two should ever run concurrently.

SAFETY: refuses to run unless config.yaml's `engine.enabled` is true (fails
closed — src/engine/worker.py's Worker.startup() enforces this a second
time, inside the loop itself).

Usage:
    python3 scripts/hermes_engine_worker.py [--max-iterations N]
"""
from __future__ import annotations

import argparse
import fcntl
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from engine import db as enginedb  # noqa: E402
from engine.worker import Worker, WorkerPolicy  # noqa: E402
import engine_apply  # noqa: E402

LOCK_PATH = ROOT / "output" / "hermes-engine.lock"
DB_PATH = ROOT / "db" / "applications.db"

logging.basicConfig(level=logging.INFO, format="[hermes-engine %(asctime)s] %(message)s")
logger = logging.getLogger("hermes_engine_worker")


def acquire_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fh = open(LOCK_PATH, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    fh.write(str(__import__("os").getpid()))
    fh.flush()
    return fh


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 5 continuous engine worker")
    parser.add_argument("--max-iterations", type=int, default=None,
                         help="Stop after N loop iterations (omit to run forever)")
    args = parser.parse_args()

    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    if not engine_apply.is_engine_enabled(cfg):
        logger.error("config.yaml engine.enabled is false — refusing to start. "
                      "This is the deliberate default; see config.yaml's comment.")
        return 1

    lock_fh = acquire_lock()
    if lock_fh is None:
        logger.info("another hermes-engine worker holds %s — exiting (no overlap)", LOCK_PATH)
        return 0

    try:
        conn = enginedb.connect(str(DB_PATH), ensure_schema=True)
        worker = Worker(conn, cfg, WorkerPolicy())
        logger.info("hermes-engine worker starting (max_iterations=%s)", args.max_iterations)
        summary = worker.run(max_iterations=args.max_iterations)
        logger.info("worker stopped after %d iteration(s)", summary["iterations"])
        return 0
    finally:
        lock_fh.close()


if __name__ == "__main__":
    sys.exit(main())
