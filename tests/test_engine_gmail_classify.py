"""Phase 6: src/engine/gmail/classify.py — the five DATA_MODEL.md §11.3
(Patch 10) categories."""
from __future__ import annotations

from engine.gmail import classify


def test_rejection_detected():
    assert classify.classify("Update on your application", "Unfortunately, we have decided to "
                              "move forward with other candidates.") == classify.REJECTION


def test_rejection_checked_before_human_required_even_if_interview_mentioned():
    text = "Unfortunately, we will not be moving forward after your interview."
    assert classify.classify("Application update", text) == classify.REJECTION


def test_human_required_interview_invitation():
    assert classify.classify("Interview invitation", "We'd like to schedule a call with you — "
                              "please select a time via Calendly.") == classify.HUMAN_REQUIRED_SIGNAL


def test_human_required_offer_letter():
    assert classify.classify("Your offer", "We are pleased to offer you the position. "
                              "Please find the offer letter attached.") == classify.HUMAN_REQUIRED_SIGNAL


def test_human_required_salary_discussion():
    assert classify.classify("Compensation", "Let's discuss salary expectations before "
                              "proceeding.") == classify.HUMAN_REQUIRED_SIGNAL


def test_human_required_assessment():
    assert classify.classify("Next steps", "Please complete this coding challenge on "
                              "HackerRank within 48 hours.") == classify.HUMAN_REQUIRED_SIGNAL


def test_screening_follow_up_portfolio_request():
    assert classify.classify("Quick question", "Could you share your portfolio or a link to "
                              "your GitHub?") == classify.SCREENING_FOLLOW_UP


def test_acknowledgement_detected():
    assert classify.classify("Application received", "Thank you for applying. We have received "
                              "your application and will review it shortly.") == classify.ACKNOWLEDGEMENT


def test_ambiguous_fallback_when_nothing_matches():
    assert classify.classify("Hi", "Just wanted to touch base.") == classify.AMBIGUOUS


def test_all_categories_are_the_five_patch_10_values():
    assert classify.ALL_CATEGORIES == {
        "screening_follow_up", "human_required_signal", "rejection", "acknowledgement", "ambiguous",
    }
