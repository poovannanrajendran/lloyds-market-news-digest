from __future__ import annotations

from dataclasses import dataclass

from lloyds_digest.models import ExtractionResult


@dataclass
class Bs4HeuristicExtractor:
    name: str = "bs4_heuristic"

    def extract(self, html: str) -> ExtractionResult:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            return ExtractionResult(
                candidate_id="",
                method=self.name,
                success=False,
                error=f"beautifulsoup4 not installed: {exc}",
            )

        soup = BeautifulSoup(html, "html.parser")
        title = None
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        text = soup.get_text(" ", strip=True)
        return ExtractionResult(
            candidate_id="",
            method=self.name,
            title=title,
            text=text,
            html=None,
            success=bool(text),
            error=None if text else "No content extracted",
        )
