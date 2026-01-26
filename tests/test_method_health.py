from __future__ import annotations

from lloyds_digest.reporting.method_health import build_method_health
from lloyds_digest.scoring.method_prefs import MethodStats


def test_build_method_health_orders() -> None:
    rows = [
        ("a.com", MethodStats("m1", attempts=4, successes=1), False),
        ("b.com", MethodStats("m2", attempts=4, successes=4), True),
    ]
    items = build_method_health(rows, max_items=2)
    assert items[0].domain == "a.com"
    assert items[1].domain == "b.com"
