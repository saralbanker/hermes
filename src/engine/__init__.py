"""Phase 2 — Core Execution Engine.

A net-new, isolated module implementing WORKFLOW_ENGINE.md / DATA_MODEL.md
(post Patches 1-9, see architect-redesign-docs/IMPLEMENTATION_READINESS_VERIFICATION_2026-10-01.md)
against the v2 schema created in db/migrations/0001_opportunity_model.sql
(opportunities, source_observations, application_attempts, channel_health,
work_queue, evaluation_history, responses_v2, daily_limits_v2).

This package is deliberately NOT imported by src/apply.py, src/states.py, or
any other currently-production module. It does not touch the legacy `jobs`
table or wire into scripts/run_hermes.sh. Live wiring onto the browser layer
is Phase 3 scope.
"""
