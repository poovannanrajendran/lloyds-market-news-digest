"""Discovery layer for sources and candidates."""

from __future__ import annotations

__all__ = [
    "CsvSourceRow",
    "load_sources_csv",
    "upsert_sources",
    "RSSDiscoverer",
    "ListingDiscoverer",
    "canonicalise_url",
]

from lloyds_digest.discovery.csv_loader import CsvSourceRow, load_sources_csv, upsert_sources
from lloyds_digest.discovery.url_utils import canonicalise_url

try:  # Optional deps for discovery modules.
    from lloyds_digest.discovery.listing import ListingDiscoverer
except Exception:  # pragma: no cover - optional dependency
    ListingDiscoverer = None  # type: ignore[assignment]

try:  # Optional deps for discovery modules.
    from lloyds_digest.discovery.rss import RSSDiscoverer
except Exception:  # pragma: no cover - optional dependency
    RSSDiscoverer = None  # type: ignore[assignment]
