from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from lloyds_digest.scoring.method_prefs import MethodStats


@dataclass(frozen=True)
class MethodHealth:
    domain: str
    method: str
    success_rate: float
    attempts: int
    drift_flag: bool


def build_method_health(
    rows: Iterable[tuple[str, MethodStats, bool]],
    *,
    max_items: int = 10,
    min_attempts: int = 3,
) -> list[MethodHealth]:
    items: list[MethodHealth] = []
    for domain, stats, drift_flag in rows:
        if stats.attempts < min_attempts:
            continue
        items.append(
            MethodHealth(
                domain=domain,
                method=stats.method,
                success_rate=stats.success_rate,
                attempts=stats.attempts,
                drift_flag=drift_flag,
            )
        )
    items.sort(key=lambda item: item.success_rate)
    return items[:max_items]
