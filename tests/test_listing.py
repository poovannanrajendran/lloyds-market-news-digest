from __future__ import annotations

from lloyds_digest.discovery.csv_loader import CsvSourceRow
from lloyds_digest.discovery.listing import ListingDiscoverer, extract_links

SAMPLE_HTML = """
<html>
  <body>
    <a href="/article/1">Article One</a>
    <a href="https://example.com/article/1?utm_source=feed">Duplicate</a>
    <a href="https://external.com/story">External</a>
  </body>
</html>
"""


def test_extract_links() -> None:
    links = extract_links(SAMPLE_HTML)
    assert ("/article/1", "Article One") in links


def test_listing_discover_dedupes_and_filters() -> None:
    source = CsvSourceRow(
        source_type="primary",
        domain="example.com",
        url="https://example.com/listing",
        topics=["Market"],
        page_type="listing",
    )
    discoverer = ListingDiscoverer()
    discoverer._fetch_listing = lambda _url: SAMPLE_HTML  # type: ignore[assignment]

    candidates = discoverer.discover([source])

    assert len(candidates) == 1
    assert candidates[0].url == "https://example.com/article/1"
