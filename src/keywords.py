"""
keywords.py — Fast TF-IDF keyword extraction and overlap scoring.
Used by score.py (pre-filter) and tailor.py (targeted cover letter injection).
No external API calls — fully local / free.
"""
from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def extract_keywords(text: str, top_n: int = 20) -> list[str]:
    """
    Extract top N keywords/phrases from job description text.

    Strategy:
    1. Fit TfidfVectorizer on the single document.
    2. Extract feature names, sort by their TF-IDF score.
    3. Return as list of strings, highest score first.
    """
    if not text or not text.strip():
        return []

    vectorizer = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),   # unigrams + bigrams catch "machine learning", "node js" etc.
        max_features=500,
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9+#._-]{1,}\b",  # allow "c++", "node.js"
    )

    try:
        tfidf_matrix = vectorizer.fit_transform([text])
    except ValueError:
        # All tokens stripped by stop-words → return empty
        return []

    feature_names = vectorizer.get_feature_names_out()
    scores = tfidf_matrix.toarray()[0]

    # Sort indices by score descending, pick top_n
    ranked_indices = scores.argsort()[::-1][:top_n]
    keywords = [feature_names[i] for i in ranked_indices if scores[i] > 0]
    return keywords


def keyword_overlap_score(resume_text: str, jd_text: str) -> float:
    """
    Compute cosine similarity between resume and JD using TF-IDF.

    Returns 0.0–1.0.
    If < 0.20: obvious mismatch — caller should skip Qwen to save tokens.
    Fits vectorizer on both texts together so IDF is shared.
    """
    if not resume_text or not jd_text:
        return 0.0

    vectorizer = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        max_features=2000,
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9+#._-]{1,}\b",
    )

    try:
        matrix = vectorizer.fit_transform([resume_text, jd_text])
    except ValueError:
        return 0.0

    sim = cosine_similarity(matrix[0], matrix[1])
    return float(sim[0][0])


def missing_keywords(resume_text: str, jd_keywords: list[str]) -> list[str]:
    """
    Return keywords from jd_keywords not found in resume_text.
    Uses case-insensitive substring match so "typescript" matches
    both "TypeScript" and "typescript" in the resume.
    """
    if not resume_text or not jd_keywords:
        return []

    resume_lower = resume_text.lower()
    return [kw for kw in jd_keywords if kw.lower() not in resume_lower]
