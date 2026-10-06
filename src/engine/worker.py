"""Continuous worker — WORKFLOW_ENGINE.md §47 Continuous Worker Loop:

    START -> RECOVER -> HEALTH CHECK -> DISCOVER/REFRESH -> UPDATE PROJECTIONS
    -> CALCULATE RESERVE -> EVALUATE AS NEEDED -> CLAIM NEXT -> TAILOR
    -> RESOLVE CHANNEL -> APPLY -> VERIFY -> PERSIST OUTCOME -> UPDATE HEALTH
    -> METRICS -> MAINTENANCE -> NEXT CLAIM

Assembles Phases 1-4: db/migrations/0001_opportunity_model.sql (schema),
src/engine/{claim,transitions,recovery,reserve} (Phase 2), src/engine_apply.py
(Phase 3, Indeed), src/engine/ai/* (Phase 4). "Expensive stages do not run
unnecessarily when no work requires them" (§47) — discovery and maintenance
run on their own bounded cadence, not every iteration; claim/apply and
evaluation run every iteration since that is the worker's actual job.

SAFETY: fails closed if config.yaml's `engine.enabled` is not true (reuses
src/engine_apply.py's EngineDisabledError/is_engine_enabled — the same gate
Phase 3 established, checked here a second time before the loop even
starts, not just inside apply_indeed_via_engine).
"""

from __future__ import annotations

import logging
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import engine_apply  # noqa: E402 — the Phase 3 entrypoint this loop drives

from . import db as enginedb
from . import discovery, evaluation, reserve
from .ai import resource_arbiter as ra
from .recovery import expire_stale_opportunities, run_startup_recovery

logger = logging.getLogger(__name__)

RESUME_PATH = str(ROOT / "resumes" / "resume-fullstack.pdf")
SCREENSHOT_DIR = str(ROOT / "screenshots")


@dataclass
class WorkerPolicy:
    """Cadence/bounds — AI_SYSTEM §67/§68, WORKFLOW_ENGINE §48/§76, all
    "ordinary tuning" per SYSTEM_RULES.md's own list (polling intervals,
    batch sizes) — implementer judgment calls, not architecturally fixed."""

    discovery_interval_seconds: float = 300.0
    maintenance_interval_seconds: float = 120.0
    evaluation_limit: int = 20
    claim_lease_seconds: int = 900
    idle_sleep_seconds: float = 15.0
    idle_backoff_max_seconds: float = 300.0  # WORKFLOW_ENGINE §48: "No busy spin"
    worker_id: str = "engine-worker-1"
    discovery_limit: int | None = None


@dataclass
class CycleReport:
    discovered: dict | None = None
    evaluated: dict | None = None
    claimed_outcome: object = None
    maintenance_ran: bool = False
    idle: bool = False
    deferred_ai: bool = False
    deferred_claim: bool = False


class Worker:
    def __init__(self, conn: sqlite3.Connection, cfg: dict, policy: WorkerPolicy | None = None):
        self.conn = conn
        self.cfg = cfg
        self.policy = policy or WorkerPolicy()
        self._last_discovery = 0.0
        self._last_maintenance = 0.0
        self._idle_streak = 0

    def _require_enabled(self) -> None:
        if not engine_apply.is_engine_enabled(self.cfg):
            raise engine_apply.EngineDisabledError(
                "config.yaml engine.enabled is false — the continuous worker refuses to "
                "start. This is the deliberate default (Phase 3/5 safety gate)."
            )

    def startup(self) -> dict:
        """§47 RECOVER + HEALTH CHECK, run once before the loop begins."""
        self._require_enabled()
        summary = run_startup_recovery(self.conn)
        expired = expire_stale_opportunities(self.conn)
        logger.info("worker startup: recovered %d lease(s), expired %d stale opportunity(ies)",
                    summary["recovered_leases"], expired)
        return {**summary, "expired": expired}

    def _due(self, last: float, interval: float, now_monotonic: float) -> bool:
        return (now_monotonic - last) >= interval

    def _maybe_discover(self, now_monotonic: float, report: CycleReport) -> None:
        if not self._due(self._last_discovery, self.policy.discovery_interval_seconds, now_monotonic):
            return
        report.discovered = discovery.run_discovery_cycle(self.conn, self.cfg, self.policy.discovery_limit)
        self._last_discovery = now_monotonic

    def _maybe_evaluate(self, report: CycleReport) -> None:
        decision = ra.arbitrate_model_load(priority=ra.Priority.BACKGROUND_AI)
        if not decision.proceed:
            report.deferred_ai = True
            logger.info("evaluation deferred: %s", decision.reason)
            return
        report.evaluated = evaluation.evaluate_batch(self.conn, self.cfg, self.policy.evaluation_limit)

    def _maybe_claim_and_apply(self, report: CycleReport) -> None:
        decision = ra.arbitrate_browser_open()
        if not decision.proceed:
            report.deferred_claim = True
            logger.info("claim/apply deferred: %s", decision.reason)
            return
        report.claimed_outcome = engine_apply.apply_indeed_via_engine(
            self.conn, self.policy.worker_id, None, RESUME_PATH, SCREENSHOT_DIR, cfg=self.cfg,
        )

    def _maybe_maintain(self, now_monotonic: float, report: CycleReport) -> None:
        if not self._due(self._last_maintenance, self.policy.maintenance_interval_seconds, now_monotonic):
            return
        run_startup_recovery(self.conn)  # lease sweep + age-band recomputation sweep (§76/§78)
        expire_stale_opportunities(self.conn)  # expiration sweep (§77)
        report.maintenance_ran = True
        self._last_maintenance = now_monotonic

    def run_cycle(self, now_monotonic: float | None = None) -> CycleReport:
        """One full pass of the §47 loop. Returns a report; never raises for
        an ordinary AI/browser failure (those are handled per-stage)."""
        now_monotonic = now_monotonic if now_monotonic is not None else time.monotonic()
        report = CycleReport()
        self._maybe_discover(now_monotonic, report)
        reserve.rebuild_work_queue(self.conn)
        self._maybe_evaluate(report)
        self._maybe_claim_and_apply(report)
        self._maybe_maintain(now_monotonic, report)
        report.idle = report.claimed_outcome is None and not report.deferred_claim
        return report

    def _backoff_seconds(self) -> float:
        """§48 Idle Worker: 'No busy spin.' Linear-ish bounded backoff —
        exact curve is ordinary tuning (SYSTEM_RULES.md: 'polling intervals'
        need no architecture review)."""
        base = self.policy.idle_sleep_seconds * (1 + self._idle_streak)
        return min(base, self.policy.idle_backoff_max_seconds)

    def run(self, max_iterations: int | None = None, stop_event=None, sleep_fn=time.sleep) -> dict:
        self.startup()
        iterations = 0
        reports: list[CycleReport] = []
        while max_iterations is None or iterations < max_iterations:
            if stop_event is not None and stop_event.is_set():
                break
            report = self.run_cycle()
            reports.append(report)
            iterations += 1
            if report.idle:
                self._idle_streak += 1
                sleep_fn(self._backoff_seconds())
            else:
                self._idle_streak = 0
        return {"iterations": iterations, "reports": reports}
