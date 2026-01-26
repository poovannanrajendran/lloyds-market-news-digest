from __future__ import annotations

from lloyds_digest.scoring.heuristics import HeuristicThresholds, evaluate_text


def test_heuristics_too_short() -> None:
    decision, score = evaluate_text("short", HeuristicThresholds(min_chars=10, min_words=3))
    assert decision == "TOO_SHORT"
    assert score < 1.0


def test_heuristics_accept() -> None:
    text = "word " * 100
    decision, score = evaluate_text(text, HeuristicThresholds(min_chars=50, min_words=10))
    assert decision == "ACCEPT"
    assert score >= 1.0
