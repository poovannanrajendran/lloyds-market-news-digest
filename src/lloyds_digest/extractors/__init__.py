"""Extraction methods and orchestration."""

from __future__ import annotations

__all__ = [
    "Extractor",
    "ExtractionEngine",
    "Bs4HeuristicExtractor",
    "Crawl4AIExtractor",
    "ReadabilityExtractor",
    "TrafilaturaExtractor",
]

from lloyds_digest.extractors.bs4_heuristic import Bs4HeuristicExtractor
from lloyds_digest.extractors.crawl4ai import Crawl4AIExtractor
from lloyds_digest.extractors.engine import ExtractionEngine, Extractor
from lloyds_digest.extractors.readability import ReadabilityExtractor
from lloyds_digest.extractors.trafilatura import TrafilaturaExtractor
