from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HeuristicThresholds:
    min_chars: int = 400
    min_words: int = 60


def evaluate_text(text: str, thresholds: HeuristicThresholds | None = None) -> tuple[str, float]:
    thresholds = thresholds or HeuristicThresholds()
    text = text.strip()
    if not text:
        return "TOO_SHORT", 0.0

    char_count = len(text)
    word_count = len(text.split())

    if char_count < thresholds.min_chars or word_count < thresholds.min_words:
        score = min(char_count / thresholds.min_chars, word_count / thresholds.min_words)
        return "TOO_SHORT", max(score, 0.0)

    score = min(char_count / thresholds.min_chars, word_count / thresholds.min_words)
    return "ACCEPT", score
