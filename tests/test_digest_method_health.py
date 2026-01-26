from __future__ import annotations

from datetime import date
from pathlib import Path

from lloyds_digest.reporting.digest_renderer import DigestItem, render_digest


def test_digest_includes_method_health(tmp_path: Path) -> None:
    items = [
        DigestItem(
            title="Item",
            url="https://example.com",
            summary=None,
            score=0.9,
            source_type="primary",
            topic="Market",
        )
    ]
    health = [("example.com", "trafilatura", 0.5, 4, True)]
    output = render_digest(items, date(2026, 1, 26), tmp_path, method_health=health)
    content = output.read_text(encoding="utf-8")
    assert "Method Health" in content
    assert "example.com" in content
