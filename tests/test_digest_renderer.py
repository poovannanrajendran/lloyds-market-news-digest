from __future__ import annotations

from datetime import date
from pathlib import Path

from lloyds_digest.reporting.digest_renderer import DigestConfig, DigestItem, render_digest


def test_render_digest_creates_file(tmp_path: Path) -> None:
    items = [
        DigestItem(
            title="Item",
            url="https://example.com",
            summary=["Point"],
            score=0.9,
            source_type="primary",
            topic="Market",
        )
    ]
    output = render_digest(items, date(2026, 1, 26), tmp_path, DigestConfig())
    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "Lloyd's Market News Digest" in content
