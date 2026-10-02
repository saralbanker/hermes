"""Phase 5: src/engine/evaluation.py — embed/rerank/classify wiring into
per-opportunity evaluation. All AI calls mocked at the gateway boundary."""
from __future__ import annotations

from engine import db as enginedb, evaluation
from engine.ai import classify, embed, gateway, rerank

CFG = {"search": {"min_score": 6.5}, "scoring": {"min_similarity": 0.5}}


def _make_evaluable_opportunity(make_opportunity, engine_conn, canonical_key, **overrides):
    overrides.setdefault("application_state", "EVALUATING")
    overrides.setdefault("fit_state", "NOT_EVALUATED")
    opp_id = make_opportunity(canonical_key, **overrides)
    now = enginedb.now_iso()
    engine_conn.execute(
        "INSERT INTO source_observations (opportunity_id, source_name, observed_at, "
        "observation_status, created_at) VALUES (?, 'indeed', ?, 'ACTIVE', ?)",
        (opp_id, now, now),
    )
    return opp_id


def test_evaluate_batch_promotes_above_threshold(make_opportunity, engine_conn, monkeypatch):
    opp_id = _make_evaluable_opportunity(make_opportunity, engine_conn, "canon::eval1")

    monkeypatch.setattr(embed, "embed_batch", lambda texts, prefix="": ([[1.0, 0.0]] * len(texts), 0.1))
    monkeypatch.setattr(classify, "score_job", lambda *a, **kw: classify.ScoreResult(
        score=8.0, confidence=0.9, reason="good match", model="phi4-mini"))

    counts = evaluation.evaluate_batch(engine_conn, CFG)
    assert counts["candidates"] == 1
    assert counts["scored"] == 1
    assert counts["promoted"] == 1

    opp = enginedb.fetch_opportunity(engine_conn, opp_id)
    assert opp["application_state"] == "READY"
    assert opp["fit_score"] == 8.0

    history = engine_conn.execute(
        "SELECT evaluation_type, result FROM evaluation_history WHERE opportunity_id = ? ORDER BY evaluation_id",
        (opp_id,),
    ).fetchall()
    assert [h["evaluation_type"] for h in history] == ["SEMANTIC_SIMILARITY", "FIT_SCORE"]


def test_evaluate_batch_holds_below_score_threshold(make_opportunity, engine_conn, monkeypatch):
    opp_id = _make_evaluable_opportunity(make_opportunity, engine_conn, "canon::eval2")
    monkeypatch.setattr(embed, "embed_batch", lambda texts, prefix="": ([[1.0, 0.0]] * len(texts), 0.1))
    monkeypatch.setattr(classify, "score_job", lambda *a, **kw: classify.ScoreResult(
        score=3.0, confidence=0.5, reason="weak match", model="phi4-mini"))

    counts = evaluation.evaluate_batch(engine_conn, CFG)
    assert counts["promoted"] == 0
    opp = enginedb.fetch_opportunity(engine_conn, opp_id)
    assert opp["application_state"] == "EVALUATING"  # held, not permanently dead (§26)


def test_evaluate_batch_excludes_below_similarity_floor(make_opportunity, engine_conn, monkeypatch):
    opp_id = _make_evaluable_opportunity(make_opportunity, engine_conn, "canon::eval3")
    # Candidate vec vs job vec orthogonal -> cosine 0, below the 0.5 floor.
    calls = {"n": 0}

    def fake_embed(texts, prefix=""):
        calls["n"] += 1
        return ([[1.0, 0.0]] if calls["n"] == 1 else [[0.0, 1.0]]), 0.1

    monkeypatch.setattr(embed, "embed_batch", fake_embed)
    score_called = {"called": False}
    monkeypatch.setattr(classify, "score_job", lambda *a, **kw: score_called.update(called=True))

    counts = evaluation.evaluate_batch(engine_conn, CFG)
    assert counts["below_floor"] == 1
    assert counts["scored"] == 0
    assert score_called["called"] is False  # never reaches the expensive scoring stage

    history = engine_conn.execute(
        "SELECT result FROM evaluation_history WHERE opportunity_id = ?", (opp_id,)
    ).fetchone()
    assert history["result"] == "BELOW_FLOOR"


def test_evaluate_batch_handles_ai_unavailable_gracefully(make_opportunity, engine_conn, monkeypatch):
    _make_evaluable_opportunity(make_opportunity, engine_conn, "canon::eval4")

    def boom(*a, **kw):
        raise gateway.AIUnavailable("ollama down")
    monkeypatch.setattr(embed, "embed_batch", boom)

    counts = evaluation.evaluate_batch(engine_conn, CFG)
    assert counts["ai_failures"] == 1
    assert counts["failure_reason"] == "runtime_unavailable"


def test_evaluate_batch_reranks_shortlist_above_k(make_opportunity, engine_conn, monkeypatch):
    """§21 Reranking Scope: more candidates than K must go through rerank()
    (or its fallback), not straight to scoring."""
    monkeypatch.setattr(evaluation, "RERANK_SHORTLIST_K", 2)
    for i in range(5):
        _make_evaluable_opportunity(make_opportunity, engine_conn, f"canon::rerank{i}")

    monkeypatch.setattr(embed, "embed_batch", lambda texts, prefix="": ([[1.0, 0.0]] * len(texts), 0.1))
    rerank_calls = {"n": 0}

    def fake_rerank(query, docs):
        rerank_calls["n"] += 1
        return [rerank.RankedDocument(index=i, score=1.0, method="bge_reranker") for i in range(len(docs))]

    monkeypatch.setattr(rerank, "rerank", fake_rerank)
    scored = {"n": 0}

    def fake_score(*a, **kw):
        scored["n"] += 1
        return classify.ScoreResult(score=7.0, confidence=0.8, reason="ok", model="phi4-mini")
    monkeypatch.setattr(classify, "score_job", fake_score)

    counts = evaluation.evaluate_batch(engine_conn, CFG, limit=20)
    assert counts["candidates"] == 5
    assert rerank_calls["n"] == 1
    assert scored["n"] == 2  # bounded to K=2, not all 5
