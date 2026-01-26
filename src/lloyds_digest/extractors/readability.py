from __future__ import annotations

from dataclasses import dataclass

from lloyds_digest.models import ExtractionResult


@dataclass
class ReadabilityExtractor:
    name: str = "readability"

    def extract(self, html: str) -> ExtractionResult:
        try:
            from readability import Document
        except ImportError as exc:
            return ExtractionResult(
                candidate_id="",
                method=self.name,
                success=False,
                error=f"readability-lxml not installed: {exc}",
            )

        doc = Document(html)
        title = doc.short_title() or None
        content = doc.summary(html_partial=True)
        text = _strip_tags(content)

        return ExtractionResult(
            candidate_id="",
            method=self.name,
            title=title,
            text=text,
            html=content,
            success=bool(text),
            error=None if text else "No content extracted",
        )


def _strip_tags(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(" ", strip=True)
