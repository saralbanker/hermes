#!/usr/bin/env python3
"""hermes_gmail_watcher.py — Entry point for the Phase 6 Gmail
classify/correlate/notify pipeline (src/engine/gmail/).

NOT wired into hermes-watch.timer/hermes-watch.service — those keep running
src/response_watcher.py exactly as before, on their existing schedule. This
is a separate, explicitly-invoked entrypoint, gated by config.yaml's
`engine.gmail_enabled` (default false) — fails closed, same pattern as
scripts/hermes_engine_worker.py's `engine.enabled` gate.

Usage:
    python3 scripts/hermes_gmail_watcher.py [--max-iterations N] [--days N]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from engine import db as enginedb  # noqa: E402
from engine.gmail.watcher import poll_loop  # noqa: E402

DB_PATH = ROOT / "db" / "applications.db"

logging.basicConfig(level=logging.INFO, format="[hermes-gmail %(asctime)s] %(message)s")
logger = logging.getLogger("hermes_gmail_watcher")


def is_gmail_enabled(cfg: dict) -> bool:
    return bool((cfg.get("engine") or {}).get("gmail_enabled"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 6 Gmail classify/correlate/notify watcher")
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--interval-minutes", type=int, default=10)
    args = parser.parse_args()

    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    if not is_gmail_enabled(cfg):
        logger.error("config.yaml engine.gmail_enabled is false — refusing to start. "
                      "This is the deliberate default; see config.yaml's comment.")
        return 1

    def conn_factory():
        return enginedb.connect(str(DB_PATH), ensure_schema=True)

    logger.info("hermes-gmail watcher starting (max_iterations=%s, days=%s)",
                args.max_iterations, args.days)
    reports = poll_loop(conn_factory, interval_minutes=args.interval_minutes,
                        max_iterations=args.max_iterations)
    logger.info("watcher stopped after %d poll(s): %s", len(reports), reports[-1] if reports else {})
    return 0


if __name__ == "__main__":
    sys.exit(main())
