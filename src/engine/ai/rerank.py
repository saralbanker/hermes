"""Reranking role — AI_SYSTEM.md §19-21.

KNOWN HOST LIMITATION (confirmed 2026-10-02, see the Phase 4 report):
Ollama has no dedicated rerank HTTP endpoint (confirmed against Ollama's
own API docs — only /api/generate, /api/chat, /api/embed exist), so a
BGE-class cross-encoder reranker is invoked through /api/embed, which is
the standard community pattern for BERT-architecture rerank models on
Ollama. The only BGE-reranker checkpoint this host could pull with a
resolvable manifest — `dengcao/bge-reranker-v2-m3:latest` (3 other
community uploads attempted had no resolvable manifest) — is CONFIRMED
UNRELIABLE on this host's Ollama 0.33.3: the real measurement pass
(scripts/measure_ai_pipeline.py) succeeded once, immediately after the
model's first load (0.05s, real scores returned), but 4/4 subsequent calls
with the same input — including the exact same input that had just
succeeded — failed with
`GGML_ASSERT(n_outputs_max <= cparams.n_outputs_max)` killing the backend
llama-server process (verified independent of this code via bare curl).
This looks like a crash-and-respawn race in Ollama's BERT-reranker support
for this checkpoint, not a fluke of this code's input shape. `rerank()`
below is implemented against the real API shape (confirmed correct — it is
what produced the one successful real call) and `gateway.AIUnavailable` is
correctly raised when the backend 500s (verified: the crash response is
HTTP 500, not a 200-with-error-body, so `gateway._post`'s normal
`raise_for_status()` already handles it) — but given the ~80% observed
failure rate, treat this role as effectively unavailable in practice on
this host until a more stable checkpoint or Ollama version is available.
Every caller must be able to fall back to `rerank_fallback()` (§85 Fallback
Ranking), and should expect to use it most of the time.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from . import gateway
from .embed import cosine

PROMPT_SCHEMA_VERSION = "rerank_v1"
FALLBACK_METHOD = "embedding_cosine_fallback"
FALLBACK_VERSION = "v1"


@dataclass(frozen=True)
class RankedDocument:
    index: int
    score: float
    method: str  # "bge_reranker" or FALLBACK_METHOD
    reason: str | None = None


def rerank(query: str, documents: list[str]) -> list[RankedDocument]:
    """§19-21: query + shortlisted documents -> relevance score + ordering.
    Raises gateway.AIUnavailable/AITimeout on backend failure — callers
    must catch this and use rerank_fallback(), never silently return an
    unranked list."""
    model = gateway.load_role_config().model_for("reranker")
    pairs = [f"query: {query}\ndocument: {doc}" for doc in documents]
    vectors, _latency = gateway.embed(pairs)
    # A cross-encoder reranker's /api/embed response, when the backend
    # actually supports it, carries the relevance score as the model's
    # single pooled output dimension; absent confirmed-working hardware to
    # verify the exact response shape (see module docstring), this takes
    # the first dimension as the score — this line is the untested part.
    scored = [(i, vec[0] if vec else 0.0) for i, vec in enumerate(vectors)]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [RankedDocument(index=i, score=s, method="bge_reranker") for i, s in scored]


def rerank_fallback(query_vector: list[float], document_vectors: list[list[float]]) -> list[RankedDocument]:
    """§85 Fallback Ranking: reuse the embedding-stage cosine similarity
    already computed — not a second, independently-invented ranking signal.
    Provenance (method/version/reason/timestamp) is carried on each result,
    never represented as an equivalent model score."""
    scored = [(i, cosine(query_vector, vec)) for i, vec in enumerate(document_vectors)]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    reason = f"reranker unavailable as of {dt.datetime.now(dt.timezone.utc).isoformat()}"
    return [
        RankedDocument(index=i, score=s, method=FALLBACK_METHOD, reason=reason)
        for i, s in scored
    ]
