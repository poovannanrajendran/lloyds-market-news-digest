from __future__ import annotations

from lloyds_digest.discovery.url_utils import canonicalise_url


def test_canonicalise_url_strips_utm_and_fragment() -> None:
    url = "https://example.com/path?utm_source=abc&utm_campaign=test&keep=1#section"
    assert canonicalise_url(url) == "https://example.com/path?keep=1"
