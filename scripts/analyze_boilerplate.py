from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

import httpx

from lloyds_digest.discovery.csv_loader import load_sources_csv
from lloyds_digest.discovery.listing import ListingDiscoverer
from lloyds_digest.discovery.rss import RSSDiscoverer
from lloyds_digest.discovery.url_utils import canonicalise_url


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze boilerplate text per domain/path template.")
    parser.add_argument("--sources", default="sources.csv", help="Path to sources.csv")
    parser.add_argument("--samples", type=int, default=15, help="Samples per domain/path group")
    parser.add_argument("--min-share", type=float, default=0.7, help="Min share threshold for boilerplate")
    parser.add_argument("--output", default="boilerplate.yaml", help="Output YAML path")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout")
    parser.add_argument(
        "--ignore-path-prefix",
        action="append",
        default=[],
        help="Path prefix to ignore (repeatable, e.g. /newsroom)",
    )
    args = parser.parse_args()

    sources = load_sources_csv(args.sources)
    print(f"Loaded {len(sources)} sources from {args.sources}")
    candidates = discover_candidates(sources, ignore_prefixes=args.ignore_path_prefix)
    print(f"Discovered {len(candidates)} candidate URLs")

    grouped: dict[str, list[str]] = defaultdict(list)
    for url in candidates:
        key = template_key(url)
        grouped[key].append(url)

    rules: dict[str, list[str]] = {}
    for key, urls in grouped.items():
        unique_urls = _dedupe(urls)[: args.samples]
        if len(unique_urls) < 3:
            continue
        print(f"[{key}] analyzing {len(unique_urls)} URLs")
        blocks = analyze_group(unique_urls, timeout=args.timeout, min_share=args.min_share, label=key)
        if blocks:
            rules[key] = blocks

    dump_yaml(Path(args.output), rules, args.ignore_path_prefix)
    print(f"Wrote {len(rules)} boilerplate templates to {args.output}")


def discover_candidates(sources, ignore_prefixes: list[str]) -> list[str]:
    rss = RSSDiscoverer()
    listing = ListingDiscoverer()
    candidates = []
    candidates.extend(
        [c.url for c in rss.discover(sources, postgres=None, mongo=None, run_id=None, seen=set())]
    )
    candidates.extend(
        [c.url for c in listing.discover(sources, postgres=None, mongo=None, run_id=None, seen=set())]
    )
    urls = [canonicalise_url(url) for url in candidates]
    if not ignore_prefixes:
        return urls
    return [url for url in urls if not _is_ignored(url, ignore_prefixes)]


def template_key(url: str) -> str:
    parsed = urlsplit(url)
    domain = parsed.netloc.lower()
    path = parsed.path.strip("/")
    if not path:
        group = "root"
    else:
        parts = path.split("/")
        group = "/".join(parts[:2]).lower()
    return f"{domain}|{group}"


def analyze_group(urls: Iterable[str], timeout: float, min_share: float, label: str) -> list[str]:
    urls_list = list(urls)
    block_counts: Counter[str] = Counter()
    total = 0
    for idx, url in enumerate(urls_list, start=1):
        print(f"[{label}] ({idx}/{len(urls_list)}) fetching {url}")
        html = fetch(url, timeout=timeout)
        if not html:
            continue
        blocks = extract_blocks(html)
        if not blocks:
            continue
        total += 1
        for block in blocks:
            block_counts[block] += 1

    if total == 0:
        return []
    threshold = max(2, int(total * min_share))
    return [block for block, count in block_counts.items() if count >= threshold]


def fetch(url: str, timeout: float) -> str | None:
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": "lloyds-digest/0.1"}) as client:
            response = client.get(url)
            if response.status_code >= 400:
                return None
            return response.text
    except Exception:
        return None


def extract_blocks(html: str) -> list[str]:
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return []
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    blocks: list[str] = []
    for tag in soup.find_all(["header", "footer", "nav", "section", "article", "main", "p", "li", "h1", "h2", "h3"]):
        text = " ".join(tag.get_text(" ", strip=True).split())
        if len(text) < 40:
            continue
        blocks.append(text)
    return _dedupe(blocks)


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def dump_yaml(path: Path, data: dict[str, list[str]], ignore_paths: list[str]) -> None:
    import yaml

    payload = dict(data)
    if ignore_paths:
        payload["__ignore_paths__"] = ignore_paths
    path.write_text(yaml.safe_dump(payload, sort_keys=True, allow_unicode=True), encoding="utf-8")


def _is_ignored(url: str, prefixes: list[str]) -> bool:
    if not prefixes:
        return False
    path = urlsplit(url).path.lower()
    for prefix in prefixes:
        if path.startswith(prefix.lower()):
            return True
    return False


if __name__ == "__main__":
    main()
