# indeed-submit-disabled

## Goal
Know why Indeed's "Submit your application" stays disabled on the review page, backed by captured review-page evidence, and ship the smallest fix.

## Decisions
- 2026-10-08: no fix yet. Existing evidence can't separate the hypotheses. Screenshots are viewport-only, so Submit and everything near it is below the fold. No DOM is dumped.
- The condition is not new: 28 rows since 2026-09-24, against about 65 submits. It predates 92565b2 (CATALYS 2026-10-06 06:18 UTC).
- Intermittent within a run: DIS sits between SUBs on 09-24 and 10-06. Clusters: 09-24 08:54 to 09-25 02:52 (10 DIS / 1 SUB), and 10-07 16:42 onward (5/5 DIS).
- The rate rose after the per-attempt fresh-profile change: 5/6 vs 22/86 before (Fisher p≈0.008). n is small.
- The button set is identical in all 28 rows.

## Done so far (2026-10-08)
- Instrumentation shipped: src/indeed_evidence.py + hook in `_form_changed_no_control` (src/indeed_apply.py). Read-only, gated by env HERMES_INDEED_EVIDENCE_DIR. Tests: tests/test_indeed_evidence.py. Full suite 1316 passed.
- Verified live in headless Chrome on a local fixture: full-page PNG, html, text, probe, 13 polls over 60 s, enable-at-20 s detected. Not yet verified on real Indeed.
- Diagnostic job: 10857 Green Letter Technologies requeued to `tailored` (only eligible job; 2147 has attempts=3). DB backup: db/applications.backup-evidence-run-20261008T152816.db. To undo: set 10857 back to form_changed.

## Run 1 result (2026-10-08 15:34 IST)
Job 10857 SUBMITTED (success page + Applied history + Gmail confirmation). No evidence captured: Submit was enabled. Same job had a disabled Submit ~7 h earlier -> the condition is transient, not job-specific. Instrumentation is transparent on the success path.

## Run 2 result (dry-run, 2026-10-08 15:40-15:46 IST)
0 evidence captured. 3 of 4 (10809, 10526, 10806) reached an ENABLED Submit (dry_run_ok, back to tailored). 10504 hit a different page: "It looks like you don't meet these employer requirements" with Return to job search / Apply anyway (screening years); not the disabled-Submit condition, not touched.
Totals since instrumentation: 4 attempts reached a final Submit, 4 enabled, 0 disabled. All 4 had a disabled Submit in earlier runs (3 of them at 08:01-08:14 IST today, with the same f629ba6 fixes already in the worktree). So the fixes do not explain it, and the load/ordering differences between runs are not supported by metrics.jsonl (apply cpu_s 35.7 vs 34.8).
Unexplained difference: the 08:01 run was a full pipeline run; these were apply-only. Not tested.

## Next step
No fix: nothing to diagnose. Keep capture armed (set HERMES_INDEED_EVIDENCE_DIR in output/hermes.env or the unit) and wait for a natural recurrence at low volume, then analyze output/indeed_evidence/*/. 3 jobs are in `tailored` (10809,10526,10806) plus 2147 (attempts=3).

## Open questions
- Does the review page contain an `input[type=file]`? If yes, `_fill_form_step` -> `_fill_resume` re-uploads the resume on the review page just before the button scan.
- Does Submit enable after more than 12 s?
- hermes.timer is disabled (checked 2026-10-08 15:09 IST). Is that intended? (Incident brief says yes.)
- The 08:01 IST run (3/3 disabled) was a full pipeline run; today's 4/4 enabled were apply-only. Does a full run (discover/score/tailor first, Ollama resident) change Submit? Untested.
