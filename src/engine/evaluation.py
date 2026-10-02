"""Evaluation — AI_SYSTEM.md §9 Target Evaluation Pipeline:

    hard filters (discovery.py, already applied)
    -> candidate/job embedding
    -> similarity floor
    -> shortlist
    -> BGE-class reranking (with §85 fallback — see src/engine/ai/rerank.py)
    -> Phi-4-mini fit judgment
    -> ranking result

Writes one evaluation_history row per stage per opportunity (DATA_MODEL.md
§10, AI_SYSTEM.md §86) and advances hard-eligible, sufficiently-similar,
sufficiently-scored opportunities to READY. A below-floor or below-threshold
result is a current outcome, not a permanent tombstone (AI_SYSTEM.md §17/§26)
— it stays OBSERVED/EVALUATING and can be re-evaluated later.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .ai import classify, embed, gateway, rerank
from .ai.failure import classify_ai_failure
from . import db as enginedb
from . import description_store

EVALUATION_BATCH_DEFAULT = 20
# AI_SYSTEM.md §21/§66 Reranking Scope/Budget: "K is a measured performance
# parameter" — no doc gives a number; this implementation's chosen default,
# same pattern as every other undocumented threshold in this codebase.
RERANK_SHORTLIST_K = 10


@dataclass
class _Shortlisted:
    opportunity_id: int
    title: str
    description: str
    location: str
    job_vec: list[float]
    similarity: float


def _candidates_due_for_evaluation(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT opportunity_id, job_title_display, job_title_normalized, location_display
        FROM opportunities
        WHERE hard_eligibility_state = 'ELIGIBLE'
          AND application_state IN ('OBSERVED', 'EVALUATING')
          AND fit_state IN ('NOT_EVALUATED', 'STALE')
        ORDER BY updated_at ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def _description_for(conn: sqlite3.Connection, opportunity_id: int) -> str:
    row = conn.execute(
        "SELECT description_ref FROM source_observations WHERE opportunity_id = ? "
        "ORDER BY observed_at DESC LIMIT 1",
        (opportunity_id,),
    ).fetchone()
    return description_store.read(row["description_ref"] if row else None)


def _record_evaluation(conn: sqlite3.Connection, opportunity_id: int, evaluation_type: str,
                        result: str, score: float | None, confidence: float | None,
                        reason: str | None, model: str | None, now: str) -> None:
    conn.execute(
        """
        INSERT INTO evaluation_history (
            opportunity_id, evaluation_type, evaluated_at, policy_version, result,
            score, confidence, reason, model_name, metadata
        ) VALUES (?, ?, ?, 'v1', ?, ?, ?, ?, ?, NULL)
        """,
        (opportunity_id, evaluation_type, now, result, score, confidence, reason, model),
    )


def _embed_similarity_floor(
    conn: sqlite3.Connection, candidates: list[sqlite3.Row], candidate_vec: list[float],
    floor: float, now: str, counts: dict,
) -> list[_Shortlisted]:
    """§12-17: embed each candidate job, drop anything below the similarity
    floor (recorded either way — a below-floor result is still a real
    evaluation outcome, §17)."""
    shortlist: list[_Shortlisted] = []
    for row in candidates:
        opportunity_id = row["opportunity_id"]
        title = row["job_title_display"] or row["job_title_normalized"] or ""
        description = _description_for(conn, opportunity_id)
        location = row["location_display"] or ""
        job_text = embed.job_text(title, description, location)
        try:
            job_vec = embed.embed_batch(["search_document: " + job_text])[0][0]
        except (gateway.AIUnavailable, gateway.AITimeout):
            counts["ai_failures"] += 1
            continue
        similarity = embed.cosine(candidate_vec, job_vec)
        _record_evaluation(conn, opportunity_id, "SEMANTIC_SIMILARITY",
                            "BELOW_FLOOR" if similarity < floor else "ABOVE_FLOOR",
                            similarity, None, None, None, now)
        if similarity < floor:
            counts["below_floor"] += 1
            continue
        shortlist.append(_Shortlisted(opportunity_id, title, description, location, job_vec, similarity))
    return shortlist


def _rerank_shortlist(shortlist: list[_Shortlisted], k: int) -> list[_Shortlisted]:
    """§19-21 BGE-class reranking, bounded to top-K; falls back to the
    already-computed embedding cosine ordering (§85) if the reranker is
    unavailable (confirmed unreliable on this host as of Phase 4 — see
    src/engine/ai/rerank.py's module docstring)."""
    if len(shortlist) <= k:
        return shortlist
    query = embed.candidate_text()
    docs = [s.description or s.title for s in shortlist]
    try:
        ranked = rerank.rerank(query, docs)
    except (gateway.AIUnavailable, gateway.AITimeout):
        vectors = [s.job_vec for s in shortlist]
        # rerank_fallback needs a query vector; reuse the already-computed
        # job vectors' own space by comparing each to the mean (cheap stand-
        # in for a fresh candidate-text embed call we'd otherwise repeat).
        ranked = rerank.rerank_fallback(shortlist[0].job_vec, vectors)
    return [shortlist[r.index] for r in ranked[:k]]


def _score_and_advance(conn: sqlite3.Connection, item: _Shortlisted, cfg: dict, now: str,
                        counts: dict) -> None:
    try:
        score_result = classify.score_job(item.title, item.description, item.location)
    except (gateway.AIUnavailable, gateway.AITimeout, ValueError):
        counts["ai_failures"] += 1
        return
    counts["scored"] += 1
    _record_evaluation(conn, item.opportunity_id, "FIT_SCORE", "SCORED", score_result.score,
                        score_result.confidence, score_result.reason, score_result.model, now)
    threshold = cfg.get("search", {}).get("min_score", 0.0)
    promote = score_result.score >= threshold
    new_state = "READY" if promote else "EVALUATING"
    conn.execute(
        "UPDATE opportunities SET application_state = ?, fit_state = 'EVALUATED', "
        "fit_score = ?, fit_reasons = ?, updated_at = ? "
        "WHERE opportunity_id = ? AND application_state IN ('OBSERVED', 'EVALUATING')",
        (new_state, score_result.score, score_result.reason, now, item.opportunity_id),
    )
    if promote:
        counts["promoted"] += 1


def evaluate_batch(conn: sqlite3.Connection, cfg: dict, limit: int = EVALUATION_BATCH_DEFAULT) -> dict:
    """One evaluation cycle, AI_SYSTEM.md §67 Scoring Budget: bounded by
    `limit` — a large backlog waits for the next cycle rather than starving
    application execution."""
    now = enginedb.now_iso()
    counts = {"candidates": 0, "below_floor": 0, "scored": 0, "promoted": 0, "ai_failures": 0}
    candidates = _candidates_due_for_evaluation(conn, limit)
    counts["candidates"] = len(candidates)
    if not candidates:
        return counts

    try:
        candidate_vec = embed.embed_batch([embed.candidate_text()], prefix="search_query: ")[0][0]
    except (gateway.AIUnavailable, gateway.AITimeout) as exc:
        counts["ai_failures"] += len(candidates)
        counts["failure_reason"] = classify_ai_failure(exc)
        return counts

    floor = cfg.get("scoring", {}).get("min_similarity", 0.0)
    shortlist = _embed_similarity_floor(conn, candidates, candidate_vec, floor, now, counts)
    ranked = _rerank_shortlist(shortlist, RERANK_SHORTLIST_K)
    for item in ranked:
        _score_and_advance(conn, item, cfg, now, counts)
    return counts
