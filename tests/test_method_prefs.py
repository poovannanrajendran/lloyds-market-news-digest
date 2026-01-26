from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lloyds_digest.scoring.method_prefs import MethodPrefs, MethodStats, select_method_prefs


def test_select_method_prefs_prefers_best() -> None:
    now = datetime.now(timezone.utc)
    stats = [
        MethodStats(method="a", attempts=5, successes=2),
        MethodStats(method="b", attempts=5, successes=4),
    ]
    prefs = select_method_prefs("example.com", stats, None, now)
    assert prefs is not None
    assert prefs.primary_method == "b"
    assert "a" in prefs.fallback_methods


def test_select_method_prefs_respects_cooldown() -> None:
    now = datetime.now(timezone.utc)
    current = MethodPrefs(
        domain="example.com",
        primary_method="a",
        fallback_methods=["b"],
        confidence=0.4,
        last_changed_at=now - timedelta(hours=1),
        locked_until=now + timedelta(hours=23),
    )
    stats = [
        MethodStats(method="a", attempts=5, successes=2),
        MethodStats(method="b", attempts=5, successes=5),
    ]
    prefs = select_method_prefs("example.com", stats, current, now)
    assert prefs is current
