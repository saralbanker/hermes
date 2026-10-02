"""Phase 4: src/engine/ai/rerank.py — fallback ranking (AI_SYSTEM.md §85),
and that a backend failure is correctly surfaced (never silently returns an
unranked list)."""
from __future__ import annotations

import pytest

from engine.ai import gateway, rerank


def test_rerank_fallback_orders_by_cosine_similarity_descending():
    query_vec = [1.0, 0.0]
    doc_vecs = [[0.0, 1.0], [1.0, 0.0], [0.7, 0.7]]  # orthogonal, identical, 45deg
    ranked = rerank.rerank_fallback(query_vec, doc_vecs)
    assert [r.index for r in ranked] == [1, 2, 0]
    assert all(r.method == rerank.FALLBACK_METHOD for r in ranked)
    assert all(r.reason for r in ranked)  # provenance per §85


def test_rerank_fallback_is_tagged_as_fallback_not_equivalent_model_score():
    ranked = rerank.rerank_fallback([1.0], [[1.0]])
    assert ranked[0].method != "bge_reranker"


def test_rerank_raises_aiunavailable_on_backend_failure(monkeypatch):
    def boom(*a, **kw):
        raise gateway.AIUnavailable("backend crashed")
    monkeypatch.setattr(gateway, "embed", boom)
    with pytest.raises(gateway.AIUnavailable):
        rerank.rerank("query", ["doc1", "doc2"])


def test_rerank_success_path_orders_by_score(monkeypatch):
    """Exercises the real-response-shape code path with a synthetic
    response (the true end-to-end shape is UNTESTED on this host — see
    rerank.py's module docstring)."""
    monkeypatch.setattr(gateway, "embed", lambda pairs: ([[0.2], [0.9], [0.5]], 0.1))
    ranked = rerank.rerank("query", ["a", "b", "c"])
    assert [r.index for r in ranked] == [1, 2, 0]
    assert all(r.method == "bge_reranker" for r in ranked)
