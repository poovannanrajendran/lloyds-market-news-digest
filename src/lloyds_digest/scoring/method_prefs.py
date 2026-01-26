from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable


@dataclass(frozen=True)
class MethodStats:
    method: str
    attempts: int
    successes: int
    median_duration_ms: int | None = None
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None

    @property
    def success_rate(self) -> float:
        if self.attempts <= 0:
            return 0.0
        return self.successes / self.attempts


@dataclass(frozen=True)
class MethodPrefs:
    domain: str
    primary_method: str
    fallback_methods: list[str]
    confidence: float
    last_changed_at: datetime | None = None
    locked_until: datetime | None = None
    drift_flag: bool = False
    drift_notes: str | None = None


def select_method_prefs(
    domain: str,
    stats: Iterable[MethodStats],
    current: MethodPrefs | None,
    now: datetime,
    *,
    min_attempts: int = 3,
    cooldown_hours: int = 24,
    promote_margin: float = 0.15,
    min_success_rate: float = 0.4,
) -> MethodPrefs | None:
    eligible = [s for s in stats if s.attempts >= min_attempts]
    if not eligible:
        return current

    eligible.sort(
        key=lambda s: (
            s.success_rate,
            -1 * (s.median_duration_ms or 0),
        ),
        reverse=True,
    )
    best = eligible[0]
    cooldown = timedelta(hours=cooldown_hours)

    if current and current.locked_until and current.locked_until > now:
        return current

    if current:
        current_stat = next((s for s in eligible if s.method == current.primary_method), None)
        if current_stat:
            if best.method != current.primary_method and (
                best.success_rate >= current_stat.success_rate + promote_margin
            ):
                return _build_prefs(domain, best, eligible, now, cooldown, min_success_rate)
            return _build_prefs(domain, current_stat, eligible, current.last_changed_at or now, None, min_success_rate)

    return _build_prefs(domain, best, eligible, now, cooldown, min_success_rate)


def _build_prefs(
    domain: str,
    primary: MethodStats,
    eligible: list[MethodStats],
    changed_at: datetime,
    cooldown: timedelta | None,
    min_success_rate: float,
) -> MethodPrefs:
    fallback = [stat.method for stat in eligible if stat.method != primary.method]
    drift_flag = primary.success_rate < min_success_rate
    drift_notes = (
        f"primary_success_rate={primary.success_rate:.2f}" if drift_flag else None
    )
    locked_until = changed_at + cooldown if cooldown else None
    return MethodPrefs(
        domain=domain,
        primary_method=primary.method,
        fallback_methods=fallback,
        confidence=primary.success_rate,
        last_changed_at=changed_at,
        locked_until=locked_until,
        drift_flag=drift_flag,
        drift_notes=drift_notes,
    )
