from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import os
import re
from typing import Callable, Iterable
from urllib.parse import urljoin, urlsplit

import httpx

from lloyds_digest.discovery.csv_loader import CsvSourceRow
from lloyds_digest.discovery.url_utils import candidate_id_from_url, canonicalise_url
from lloyds_digest.models import Candidate
from lloyds_digest.storage.mongo_repo import MongoRepo
from lloyds_digest.storage.postgres_repo import PostgresRepo


class _LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = None
        for key, value in attrs:
            if key.lower() == "href" and value:
                href = value
                break
        self._current_href = href
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a":
            return
        if self._current_href:
            text = " ".join(part.strip() for part in self._text_parts).strip()
            self.links.append((self._current_href, text))
        self._current_href = None
        self._text_parts = []


def extract_links(html: str) -> list[tuple[str, str]]:
    parser = _LinkExtractor()
    parser.feed(html)
    return parser.links


@dataclass
class ListingDiscoverer:
    timeout: float = 20.0

    def discover(
        self,
        sources: Iterable[CsvSourceRow],
        postgres: PostgresRepo | None = None,
        mongo: MongoRepo | None = None,
        run_id: str | None = None,
        seen: set[str] | None = None,
        allow_external: bool = False,
        log: Callable[[str], None] | None = None,
    ) -> list[Candidate]:
        candidates: list[Candidate] = []
        dedup = seen if seen is not None else set()

        for source in sources:
            if source.page_type != "listing":
                continue
            try:
                if log:
                    log(f"[listing] Fetching listing {source.url}")
                html = self._fetch_listing(source.url)
                links = extract_links(html)
                if log:
                    log(f"[listing] Extracted {len(links)} links from {source.domain}")
            except Exception as exc:
                # A single listing source may be paywalled/blocked (401/403) or temporarily down.
                # Don't fail the entire listing discovery pass; just skip this source.
                if log:
                    log(f"[listing] Listing failed {source.url}: {exc}")
                continue
            snapshot_id = None
            if mongo is not None:
                snapshot_id = mongo.insert_discovery_snapshot(
                    {
                        "source_id": source.to_source().source_id,
                        "url": source.url,
                        "fetched_at": _utc_now(),
                        "link_count": len(links),
                        "run_id": run_id,
                    }
                )

            for href, text in links:
                absolute = urljoin(source.url, href)
                if not _is_http_url(absolute):
                    continue
                if not allow_external and not _same_domain(absolute, source.domain):
                    continue
                canonical = canonicalise_url(absolute)
                if source.domain.strip().lower() == "theinsurer.com":
                    # TheInsurer listing pages include a lot of nav/topic links.
                    # Filter to article-like URLs to avoid wasting work downstream.
                    if not _looks_like_theinsurer_article(canonical):
                        continue
                candidate_id = candidate_id_from_url(canonical)
                if candidate_id in dedup:
                    continue
                dedup.add(candidate_id)

                metadata = {
                    "anchor_text": text or None,
                    "topics": source.topics,
                    "source_type": source.source_type,
                    "page_type": source.page_type,
                    "snapshot_id": snapshot_id,
                    "run_id": run_id,
                    "canonical_url": canonical,
                }
                candidate = Candidate(
                    candidate_id=candidate_id,
                    source_id=source.to_source().source_id,
                    url=canonical,
                    title=text or None,
                    metadata=metadata,
                )
                candidates.append(candidate)
                if log:
                    log(f"[listing] Candidate {candidate.url}")
                if postgres is not None:
                    postgres.insert_candidate(candidate)

        return candidates

    def _fetch_listing(self, url: str) -> str:
        mode = (os.environ.get("LLOYDS_DIGEST_DISCOVERY_FETCHER") or "httpx").strip().lower()
        if mode == "playwright":
            return self._fetch_listing_playwright(url)
        return self._fetch_listing_httpx(url)

    def _fetch_listing_httpx(self, url: str) -> str:
        with httpx.Client(
            timeout=self.timeout,
            headers={"User-Agent": "lloyds-digest/0.1"},
            follow_redirects=True,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.text

    def _fetch_listing_playwright(self, url: str) -> str:
        # Optional dependency; only used when explicitly enabled via env.
        from playwright.sync_api import sync_playwright  # type: ignore
        headless_env = os.environ.get("LLOYDS_DIGEST_PLAYWRIGHT_HEADLESS")
        if headless_env is not None:
            normalized = headless_env.strip().lower()
            if normalized in {"0", "false", "no", "off"}:
                headless = False
            elif normalized in {"1", "true", "yes", "on"}:
                headless = True
            else:
                headless = True
        else:
            headless = True

        with sync_playwright() as p:
            def _run(headless_flag: bool) -> tuple[int | None, str]:
                browser = p.chromium.launch(headless=headless_flag)
                try:
                    page = browser.new_page()
                    resp = page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=int(self.timeout * 1000),
                    )
                    page.wait_for_timeout(750)
                    return (resp.status if resp is not None else None), page.content()
                finally:
                    browser.close()

            status, html = _run(headless)
            if (
                headless
                and status in {401, 403}
                and os.environ.get("LLOYDS_DIGEST_PLAYWRIGHT_HEADFUL_FALLBACK", "").strip().lower()
                in {"1", "true", "yes", "on"}
            ):
                _, html = _run(False)
            return html


def _same_domain(url: str, domain: str) -> bool:
    netloc = urlsplit(url).netloc.lower()
    domain = domain.lower()
    if netloc == domain:
        return True
    return netloc.endswith(f".{domain}")


def _is_http_url(url: str) -> bool:
    scheme = urlsplit(url).scheme
    return scheme in {"http", "https"}


_THEINSURER_ARTICLE_RE = re.compile(
    r"/(news|analysis|commentary|viewpoint|interview)/.+\d{4}-\d{2}-\d{2}/?$",
    re.IGNORECASE,
)


def _looks_like_theinsurer_article(url: str) -> bool:
    path = urlsplit(url).path
    return bool(_THEINSURER_ARTICLE_RE.search(path))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
