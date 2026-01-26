from __future__ import annotations

from dataclasses import dataclass

from lloyds_digest.models import ExtractionResult


@dataclass
class TrafilaturaExtractor:
    name: str = "trafilatura"

    def extract(self, html: str) -> ExtractionResult:
        try:
            import trafilatura
        except ImportError as exc:
            return ExtractionResult(
                candidate_id="",
                method=self.name,
                success=False,
                error=f"trafilatura not installed: {exc}",
            )

        text = trafilatura.extract(html) or ""
        title = None
        try:
            metadata = trafilatura.extract_metadata(html)
            title = metadata.title if metadata else None
        except Exception:
            title = None

        return ExtractionResult(
            candidate_id="",
            method=self.name,
            title=title,
            text=text,
            html=None,
            success=bool(text),
            error=None if text else "No content extracted",
        )
