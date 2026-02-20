from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from lloyds_digest.models import FetchResult


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class PlaywrightFetcher:
    """
    Browser-based fetcher for JS-heavy / bot-protected sites.

    Notes:
    - This requires the optional `playwright` dependency and a browser install
      (e.g. via `playwright install`).
    - No stealth / fingerprint evasion is attempted; this is "plain" Playwright.
    """

    timeout_s: float = 30.0
    fetcher_name: str = "playwright"
    browser: str = "chromium"
    headless: bool = True

    def fetch(self, url: str, cache=None) -> FetchResult:
        cached = cache.get(url) if cache is not None else None
        if cached:
            return FetchResult(
                candidate_id=cached.get("candidate_id", ""),
                url=cached.get("final_url", url),
                status_code=cached.get("status_code"),
                fetched_at=cached.get("fetched_at", _utc_now()),
                content=cached.get("content"),
                from_cache=True,
            )

        started = _utc_now()
        try:
            # Lazy import so the package remains optional.
            from playwright.sync_api import sync_playwright  # type: ignore
            import os

            headless_env = os.environ.get("LLOYDS_DIGEST_PLAYWRIGHT_HEADLESS")
            if headless_env is not None:
                normalized = headless_env.strip().lower()
                if normalized in {"0", "false", "no", "off"}:
                    headless = False
                elif normalized in {"1", "true", "yes", "on"}:
                    headless = True
                else:
                    headless = self.headless
            else:
                headless = self.headless

            with sync_playwright() as p:
                browser_type = getattr(p, self.browser)
                def _run(headless_flag: bool) -> tuple[int, str, str]:
                    browser = browser_type.launch(headless=headless_flag)
                    try:
                        page = browser.new_page()
                        resp = page.goto(
                            url,
                            wait_until="domcontentloaded",
                            timeout=int(self.timeout_s * 1000),
                        )
                        # Some sites hydrate content after domcontentloaded; give it a moment.
                        page.wait_for_timeout(750)
                        final_url = page.url
                        content = page.content()
                        try:
                            from urllib.parse import urlsplit

                            host = urlsplit(final_url).netloc.lower()
                            main_only_env = os.environ.get("LLOYDS_DIGEST_PLAYWRIGHT_MAIN_ONLY", "").strip().lower()
                            main_only = main_only_env in {"1", "true", "yes", "on"}
                            # Default to main-only for TheInsurer to reduce nav/footer noise in extraction.
                            if host.endswith("theinsurer.com"):
                                main_only = True if main_only_env == "" else main_only
                            if main_only:
                                # Site-specific: TheInsurer article pages have a small teaser plus paywall.
                                # Extract the title/byline/published/teaser container to avoid footer noise.
                                if host.endswith("theinsurer.com"):
                                    try:
                                        teaser_text = page.evaluate(
                                            "() => {"
                                            "  const h1 = document.querySelector('h1');"
                                            "  const container = h1?.parentElement?.parentElement;"
                                            "  return container?.innerText || '';"
                                            "}"
                                        )
                                        if isinstance(teaser_text, str) and teaser_text.strip():
                                            lines = [ln.strip() for ln in teaser_text.splitlines() if ln.strip()]
                                            body = "\n".join(f"<p>{ln}</p>" for ln in lines[:60])
                                            content = f"<!DOCTYPE html><html><body>{body}</body></html>"
                                    except Exception:
                                        pass
                                else:
                                    main = page.locator("main")
                                    if main.count() > 0:
                                        # Prefer text extraction for noisy sites; then wrap it in minimal HTML
                                        # so downstream extractors see only the main content.
                                        try:
                                            main_text = main.first.inner_text()
                                            lines = [ln.strip() for ln in main_text.splitlines() if ln.strip()]
                                            cleaned_lines: list[str] = []
                                            for ln in lines:
                                                lowered = ln.lower()
                                                if "if you are a subscriber" in lowered:
                                                    break
                                                if lowered in {"sign in", "subscribe"}:
                                                    break
                                                cleaned_lines.append(ln)
                                            if cleaned_lines:
                                                body = "\n".join(f"<p>{ln}</p>" for ln in cleaned_lines[:60])
                                                content = f"<!DOCTYPE html><html><body><main>{body}</main></body></html>"
                                        except Exception:
                                            inner = main.first.inner_html()
                                            content = f"<!DOCTYPE html><html><body><main>{inner}</main></body></html>"
                        except Exception:
                            pass
                        status = resp.status if resp is not None else 200
                        return status, final_url, content
                    finally:
                        browser.close()

                status, final_url, content = _run(headless)
                # Some sites block headless browsers (e.g. DataDome on theinsurer.com).
                # Only retry headful if explicitly enabled.
                if (
                    headless
                    and status in {401, 403}
                    and os.environ.get("LLOYDS_DIGEST_PLAYWRIGHT_HEADFUL_FALLBACK", "").strip().lower()
                    in {"1", "true", "yes", "on"}
                ):
                    status, final_url, content = _run(False)

            result = FetchResult(
                candidate_id="",
                url=final_url,
                status_code=status,
                fetched_at=started,
                content=content,
                elapsed_ms=int((_utc_now() - started).total_seconds() * 1000),
                from_cache=False,
            )
            if cache is not None:
                cache.set(
                    url,
                    {
                        "status_code": status,
                        "content": content,
                        "fetched_at": started,
                    },
                    final_url=final_url,
                )
            return result
        except Exception as exc:
            return FetchResult(
                candidate_id="",
                url=url,
                status_code=None,
                fetched_at=started,
                content=None,
                error=str(exc),
            )
