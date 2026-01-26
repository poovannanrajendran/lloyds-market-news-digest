from __future__ import annotations

from datetime import datetime, timezone

import feedparser

from lloyds_digest.discovery.csv_loader import CsvSourceRow
from lloyds_digest.discovery.rss import parse_feed_entries

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Sample Feed</title>
    <link>https://example.com</link>
    <item>
      <title>News Item</title>
      <link>https://example.com/article</link>
      <pubDate>Mon, 26 Jan 2026 10:00:00 GMT</pubDate>
      <description>Summary</description>
    </item>
  </channel>
</rss>
"""


def test_rss_parsing_extracts_fields() -> None:
    source = CsvSourceRow(
        source_type="primary",
        domain="example.com",
        url="https://example.com/feed",
        topics=["Lloyds"],
        page_type="rss",
    )
    parsed = feedparser.parse(SAMPLE_RSS.encode("utf-8"))
    candidates = parse_feed_entries(parsed, source, snapshot_id=None)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.url == "https://example.com/article"
    assert candidate.title == "News Item"
    assert candidate.published_at == datetime(2026, 1, 26, 10, 0, tzinfo=timezone.utc)
