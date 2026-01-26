from __future__ import annotations

from dataclasses import dataclass

from lloyds_digest.models import ExtractionResult


@dataclass
class Crawl4AIExtractor:
    name: str = "crawl4ai"

    def extract(self, html: str) -> ExtractionResult:
        try:
            from crawl4ai import AsyncWebCrawler  # type: ignore
        except ImportError as exc:
            return ExtractionResult(
                candidate_id="",
                method=self.name,
                success=False,
                error=f"crawl4ai not installed: {exc}",
            )

        # Placeholder: crawl4ai expects URL-based crawling; this is a stub.
        return ExtractionResult(
            candidate_id="",
            method=self.name,
            success=False,
            error="crawl4ai integration stub",
            metadata={"note": "crawl4ai adapter stub"},
        )
