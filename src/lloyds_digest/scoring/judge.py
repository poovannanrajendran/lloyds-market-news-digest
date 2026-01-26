from __future__ import annotations

from dataclasses import dataclass


@dataclass
class JudgeDecision:
    decision: str
    confidence: float
    notes: str | None = None


class Judge:
    def judge(self, text: str) -> JudgeDecision:
        return JudgeDecision(decision="ACCEPT", confidence=0.0, notes="stub")
