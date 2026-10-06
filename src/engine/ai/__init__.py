"""Phase 4 — AI Pipeline.

A new, isolated AI subsystem implementing AI_SYSTEM.md's frozen role
architecture (embedding, semantic reranking, scoring/classification,
generation) against real local Ollama inference. Does not modify or import
from src/llm.py, src/score.py, src/tailor.py, src/answers.py — those keep
running unmodified as the still-disabled-by-default legacy path's AI layer.

Failure handling funnels into src/engine/transitions.py's existing
`record_tailoring_failure` ("release without consuming an attempt") rather
than inventing a parallel failure-recording mechanism — see resource_arbiter.py
and the AIUnavailable/AITimeout exceptions in gateway.py.
"""
