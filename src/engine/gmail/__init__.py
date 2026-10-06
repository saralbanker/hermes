"""Phase 6 — Gmail + Telegram.

A new, isolated response-classification/correlation/notification pipeline
implementing DATA_MODEL.md §11 (post Patch 10) and
EXECUTION_PROTOCOL.md §74.12 (Patch 11). Does NOT modify or import
src/response_watcher.py's module-level state, and is NOT wired into
hermes-watch.timer/hermes-watch.service — those keep polling real Gmail on
their existing 10-minute schedule, completely unaffected.

This package only CLASSIFIES, CORRELATES, and NOTIFIES. It never sends an
employer-facing reply and never takes any action on an interview/offer/
salary/contract/legal-document signal beyond a High Priority Telegram
Notification routing it to MANUAL_REVIEW — the hard automation boundary
(AI_SYSTEM.md §28, WORKFLOW_ENGINE.md §60/§62) is enforced by never
building a reply-sending code path at all in this phase, not by a runtime
check that could be bypassed.
"""
