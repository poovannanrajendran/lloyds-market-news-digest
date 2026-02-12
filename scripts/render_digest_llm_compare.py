from __future__ import annotations

import argparse
import json
import os
import time
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import httpx

from lloyds_digest.ai.base import OllamaClient
from lloyds_digest.ai.costing import compute_cost_usd
from lloyds_digest.config import load_config
from lloyds_digest.storage.postgres_repo import PostgresRepo
from lloyds_digest.utils import load_env_file


@dataclass(frozen=True)
class ArticleItem:
    article_id: str
    title: str
    url: str
    published_at: datetime | None
    excerpt: str
    source_id: str


TEMPLATE_PATH = Path("templates/exec_digest_template.html")


def main() -> None:
    load_env_file(Path(".env"))
    config = load_config(Path("config.yaml"))
    args = _parse_args()
    items = fetch_recent_articles(hours=24, limit=120)
    if not items:
        print("No recent articles found in the last 24 hours.")
        return

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    run_date = datetime.now(timezone.utc).date().isoformat()
    chunk_by = args.chunk_by
    chunk_size = int(os.environ.get("DIGEST_CHUNK_SIZE", str(args.chunk_size)))
    chunks = list(_chunk_items(items, chunk_by=chunk_by, chunk_size=chunk_size))

    render_start = datetime.now(timezone.utc)
    output = _run_provider_chunks(
        "chatgpt",
        chunks=chunks,
        config=config,
        template=template,
        run_date=run_date,
        max_chunks=args.max_chunks,
    )
    if not output:
        return

    min_items = int(os.environ.get("DIGEST_MIN_ITEMS", str(args.min_items)))
    item_count = len(output.get("items") or [])
    if item_count < min_items:
        print(
            f"Digest has only {item_count} items; minimum required is {min_items}.",
            flush=True,
        )
        sys.exit(2)

    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    digest_path = output_dir / f"digest_{run_date}.html"
    rotate_existing(digest_path)
    digest_html = render_html(template, output, run_date=run_date)
    digest_path.write_text(digest_html, encoding="utf-8")
    _ensure_logo_asset(output_dir)
    print(f"Wrote {digest_path}")
    _log_phase_timing("render_html", render_start, datetime.now(timezone.utc))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render digest using ChatGPT only.")
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=0,
        help="Limit chunks processed (0 = all).",
    )
    parser.add_argument(
        "--chunk-by",
        choices=["domain", "count"],
        default="domain",
        help="Chunk prompts by domain or by count.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=40,
        help="Max items per chunk (can be overridden by DIGEST_CHUNK_SIZE).",
    )
    parser.add_argument(
        "--min-items",
        type=int,
        default=10,
        help="Minimum number of items required to write the digest.",
    )
    return parser.parse_args()


def _run_provider(name: str, payload: dict[str, Any], config, run_date: str, chunk_label: str) -> dict[str, Any]:
    prompt = _build_prompt(payload, config, provider=name)
    input_size = len(prompt)
    start = time.time()
    started_at = datetime.now(timezone.utc)
    print(
        f"[{name}] start {started_at.isoformat()} chunk={chunk_label} input_size={input_size}",
        flush=True,
    )

    fn_map = {
        "local": generate_with_ollama,
        "chatgpt": generate_with_openai,
        "deepseek": generate_with_deepseek,
    }
    fn = fn_map[name]
    max_seconds = _provider_timeout_seconds(name)

    result: dict[str, Any] = {}
    error: str | None = None
    if name == "local":
        try:
            result = fn(payload, config, run_date)
        except Exception as exc:
            print(f"[{name}] failed: {exc}", flush=True)
            error = str(exc)
            result = {}
    else:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(fn, payload, config, run_date)
            try:
                result = future.result(timeout=max_seconds)
            except Exception as exc:
                print(f"[{name}] failed: {exc}", flush=True)
                error = str(exc)
                result = {}

    finished_at = datetime.now(timezone.utc)
    duration = time.time() - start
    output_size = len(json.dumps(result, ensure_ascii=False)) if result else 0
    print(
        f"[{name}] finish {finished_at.isoformat()} chunk={chunk_label} duration_s={duration:.1f} output_size={output_size}",
        flush=True,
    )
    _record_llm_usage(
        config,
        provider=name,
        model=_provider_model(name),
        prompt_version=_prompt_version(config, name),
        started_at=started_at,
        finished_at=finished_at,
        latency_ms=int(duration * 1000),
        input_size=input_size,
        output_size=output_size,
        success=bool(result),
        error=error,
    )
    _record_llm_cost(
        config=config,
        provider=name,
        model=_provider_model(name),
        stage=f"render_digest:{name}",
        tokens_prompt=_estimate_tokens(input_size),
        tokens_completion=_estimate_tokens(output_size),
    )
    return result


def _run_provider_chunks(
    name: str,
    chunks: list[list[ArticleItem]],
    config,
    template: str,
    run_date: str,
    max_chunks: int,
) -> dict[str, Any]:
    if max_chunks and max_chunks > 0:
        chunks = chunks[:max_chunks]
    summaries: list[str] = []
    themes: list[str] = []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = len(chunks)

    max_attempts = int(os.environ.get("DIGEST_CHUNK_RETRIES", "2"))
    for idx, chunk in enumerate(chunks, start=1):
        payload = build_prompt_payload(chunk)
        chunk_label = f"{idx}/{total}"
        result: dict[str, Any] = {}
        for attempt in range(1, max_attempts + 1):
            result = _run_provider(name, payload, config, run_date, chunk_label)
            if _has_content(result):
                break
            if attempt < max_attempts:
                print(f"[{name}] retry chunk {chunk_label} (empty output)", flush=True)
        if not result:
            continue
        result = enrich_output(payload, result)
        exec_summary = result.get("executive_summary")
        if isinstance(exec_summary, str) and exec_summary.strip():
            summaries.append(exec_summary.strip())
        chunk_themes = result.get("themes", [])
        if isinstance(chunk_themes, list):
            themes.extend([str(theme) for theme in chunk_themes if theme])
        chunk_items = result.get("items", [])
        if isinstance(chunk_items, list):
            for item in chunk_items:
                item_id = item.get("id")
                if not item_id or item_id in seen:
                    continue
                seen.add(item_id)
                items.append(item)

        merged = {
            "executive_summary": "\n\n".join(summaries).strip(),
            "themes": _dedupe_list(themes),
            "items": _postprocess_items(items),
        }

    final_output = {
        "executive_summary": "\n\n".join(summaries).strip(),
        "themes": _dedupe_list(themes),
        "items": _postprocess_items(items),
    }
    final_output = _resummarize_executive_summary(
        name=name,
        output=final_output,
        config=config,
        run_date=run_date,
    )
    return final_output


def _provider_timeout_seconds(name: str) -> float:
    env_map = {
        "local": "OLLAMA_TIMEOUT",
        "chatgpt": "OPENAI_TIMEOUT",
        "deepseek": "OLLAMA_TIMEOUT",
    }
    default_map = {
        "local": "180",
        "chatgpt": "180",
        "deepseek": "180",
    }
    env_key = env_map[name]
    return float(os.environ.get(env_key, default_map[name]))


def _provider_model(name: str) -> str:
    if name == "local":
        return os.environ.get("OLLAMA_MODEL", "qwen3:14b")
    if name == "chatgpt":
        return os.environ.get("OPENAI_MODEL", "gpt-4o")
    if name == "deepseek":
        return os.environ.get("OLLAMA_DEEPSEEK_MODEL", "deepseek-v3.2:cloud")
    return "unknown"


def _prompt_version(config, provider: str) -> str:
    prompts = getattr(config, "llm_prompts", {}) or {}
    entry = prompts.get(provider, {}) or {}
    return entry.get("version", "v1")


def _record_llm_usage(
    config,
    provider: str,
    model: str,
    prompt_version: str,
    started_at: datetime,
    finished_at: datetime,
    latency_ms: int,
    input_size: int,
    output_size: int,
    success: bool,
    error: str | None,
) -> None:
    try:
        dsn = build_postgres_dsn_from_env()
    except Exception:
        return
    try:
        postgres = PostgresRepo(dsn)
        run_id = _latest_run_id(postgres)
        tokens_prompt = max(1, input_size // 4) if input_size else None
        tokens_completion = max(1, output_size // 4) if output_size else None
        postgres.insert_llm_usage(
            run_id=run_id,
            candidate_id=None,
            stage=f"render_digest:{provider}",
            model=model,
            prompt_version=prompt_version,
            cached=False,
            started_at=started_at,
            ended_at=finished_at,
            latency_ms=latency_ms,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            metadata={
                "program": "render_digest_llm_compare.py",
                "provider": provider,
                "input_size": input_size,
                "output_size": output_size,
                "tokens_prompt_est": tokens_prompt,
                "tokens_completion_est": tokens_completion,
                "success": success,
                "error": error,
            },
        )
    except Exception as exc:
        print(f"[{provider}] failed to record llm_usage: {exc}", flush=True)


def _record_llm_cost(
    config,
    provider: str,
    model: str,
    stage: str,
    tokens_prompt: int | None,
    tokens_completion: int | None,
) -> None:
    if provider != "chatgpt":
        return
    if tokens_prompt is None or tokens_completion is None:
        return
    cost = compute_cost_usd(
        model=model,
        tokens_prompt=tokens_prompt,
        tokens_completion=tokens_completion,
        service_tier=os.environ.get("OPENAI_SERVICE_TIER"),
    )
    if cost is None:
        return
    input_cost, output_cost, total_cost = cost
    try:
        dsn = build_postgres_dsn_from_env()
    except Exception:
        return
    try:
        postgres = PostgresRepo(dsn)
        run_id = _latest_run_id(postgres)
        postgres.insert_llm_cost_call(
            run_id=run_id,
            candidate_id=None,
            stage=stage,
            provider="openai",
            model=model,
            service_tier=os.environ.get("OPENAI_SERVICE_TIER"),
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            cost_input_usd=input_cost,
            cost_output_usd=output_cost,
            cost_total_usd=total_cost,
            metadata={"program": "render_digest_llm_compare.py"},
        )
        usage_date = datetime.now(timezone.utc).date().isoformat()
        postgres.upsert_llm_cost_stage_daily(
            usage_date=usage_date,
            stage=stage,
            provider="openai",
            model=model,
            service_tier=os.environ.get("OPENAI_SERVICE_TIER"),
            calls=1,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            cost_total_usd=total_cost,
        )
    except Exception as exc:
        print(f"[{provider}] failed to record llm_cost: {exc}", flush=True)


def _estimate_tokens(size: int) -> int | None:
    if not size:
        return None
    return max(1, size // 4)


def _log_phase_timing(phase: str, started_at: datetime, ended_at: datetime) -> None:
    try:
        dsn = build_postgres_dsn_from_env()
    except Exception:
        return
    try:
        postgres = PostgresRepo(dsn)
        run_id = _latest_run_id(postgres)
        if not run_id:
            return
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)
        postgres.insert_run_phase_timing(
            run_id=run_id,
            phase=phase,
            duration_ms=duration_ms,
            started_at=started_at,
            ended_at=ended_at,
            metadata={"program": "render_digest_llm_compare.py"},
        )
    except Exception:
        return


def _latest_run_id(postgres: PostgresRepo) -> str | None:
    sql = "SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1"
    with postgres._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            if not row:
                return None
            return row[0]


def _chunk_items(
    items: list[ArticleItem],
    chunk_by: str,
    chunk_size: int,
) -> list[list[ArticleItem]]:
    if chunk_by == "count":
        return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]

    grouped: dict[str, list[ArticleItem]] = defaultdict(list)
    for item in items:
        grouped[_domain(item.url)].append(item)

    chunks: list[list[ArticleItem]] = []
    for domain_items in grouped.values():
        for i in range(0, len(domain_items), chunk_size):
            chunks.append(domain_items[i : i + chunk_size])
    return chunks


def _dedupe_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _has_content(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    summary = result.get("executive_summary")
    if isinstance(summary, str) and summary.strip():
        return True
    themes = result.get("themes")
    if isinstance(themes, list) and any(str(t).strip() for t in themes):
        return True
    items = result.get("items")
    if isinstance(items, list) and len(items) > 0:
        return True
    return False


def _postprocess_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered = [item for item in items if _is_article_item(item)]
    deduped = _dedupe_items(filtered)
    ordered = _order_items(deduped)
    max_per_domain = int(os.environ.get("DIGEST_MAX_PER_DOMAIN", "5"))
    return _cap_per_domain(ordered, max_per_domain)


def _cap_per_domain(items: list[dict[str, Any]], max_per_domain: int) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    capped: list[dict[str, Any]] = []
    for item in items:
        domain = _domain(item.get("url", ""))
        if not domain:
            continue
        counts.setdefault(domain, 0)
        if counts[domain] >= max_per_domain:
            continue
        counts[domain] += 1
        capped.append(item)
    return capped


def _is_article_item(item: dict[str, Any]) -> bool:
    url = str(item.get("url") or "")
    title = str(item.get("title") or "")
    excerpt = str(item.get("excerpt") or "")

    if not url:
        return False

    if _matches_url_blocklist(url) and _article_score(url, title, excerpt) < 2:
        return False

    title_lower = title.lower()
    if _matches_title_blocklist(title_lower) and _article_score(url, title, excerpt) < 3:
        return False

    if _article_score(url, title, excerpt) == 0:
        return False

    return True


def _article_score(url: str, title: str, excerpt: str) -> int:
    score = 0
    lower_url = url.lower()
    if re.search(r"/20\\d{2}/|[-_/](20\\d{2})[-_/](0[1-9]|1[0-2])[-_/](0[1-9]|[12]\\d|3[01])", lower_url):
        score += 1
    words = [w for w in re.split(r"\\s+", title.strip()) if w]
    if 6 <= len(words) <= 18:
        score += 1
    if len(excerpt) >= 400:
        score += 1
    if any(token in lower_url for token in ("/news/", "/press", "/release", "/insights/")):
        score += 1
    return score


def _matches_url_blocklist(url: str) -> bool:
    lower_url = url.lower()
    patterns = [
        "/subscribe",
        "/subscription",
        "/account",
        "/login",
        "/signin",
        "/register",
        "/signup",
        "/careers",
        "/jobs",
        "/job",
        "/recruit",
        "/vacancy",
        "/apply",
        "/contact",
        "/about",
        "/help",
        "/privacy",
        "/cookie",
        "/terms",
        "/legal",
        "/disclaimer",
        "/author/",
        "/authors/",
        "/profile/",
        "/team/",
        "/people/",
        "/topic/",
        "/topics/",
        "/tag/",
        "/tags/",
        "/category/",
        "/categories/",
    ]
    if any(pat in lower_url for pat in patterns):
        return True
    if "page=" in lower_url or "offset=" in lower_url:
        return True
    return False


def _matches_title_blocklist(title_lower: str) -> bool:
    cues = [
        "subscribe",
        "sign in",
        "log in",
        "register",
        "careers",
        "job",
        "vacancy",
        "author profile",
        "tag archive",
        "topic index",
        "search results",
        "newsletter",
    ]
    return any(cue in title_lower for cue in cues)


def _order_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(item: dict[str, Any]) -> tuple[int, str]:
        category = _category_rank(item)
        domain = _domain(item.get("url", ""))
        return (category, domain)

    return sorted(items, key=key)


def _category_rank(item: dict[str, Any]) -> int:
    url = str(item.get("url") or "").lower()
    title = str(item.get("title") or "").lower()
    source_id = str(item.get("source_id") or "").lower()
    combined = f"{title} {url}"

    if source_id.startswith("primary:") or "lloyd" in combined:
        return 0
    if source_id.startswith("secondary:"):
        return 1
    if _contains_any(combined, ["regulator", "regulatory", "fca", "boe", "bank of england"]):
        return 2
    if _contains_any(combined, ["compliance", "sanctions", "aml", "anti-money", "financial crime"]):
        return 3
    if _contains_any(combined, ["pra", "prudential regulation authority"]):
        return 4
    if _contains_any(
        combined,
        [
            "insurance",
            "reinsurance",
            "broker",
            "syndicate",
            "underwriter",
            "coverholder",
            "placing",
        ],
    ):
        return 5
    if _contains_any(combined, ["financial", "rates", "markets", "bank", "treasury", "capital"]):
        return 6
    return 7


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _clamp_summary(text: str, max_chars: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    cut = cleaned[: max_chars + 1]
    last_space = cut.rfind(" ")
    if last_space > 0:
        cut = cut[:last_space]
    return cut.rstrip() + "…"


def build_linkedin_payload(payload: dict[str, Any], run_date: str) -> dict[str, Any]:
    items = payload.get("items") or []
    if not isinstance(items, list):
        items = []

    items = _postprocess_items(items)
    items = _move_fca_to_bottom(items)
    limit = int(os.environ.get("LINKEDIN_MAX_ITEMS", "12"))
    min_london = int(os.environ.get("LINKEDIN_MIN_LONDON", "3"))
    top = _select_linkedin_top(items, min_london=min_london, limit=limit)

    summary = payload.get("executive_summary", "")
    summary = _clamp_summary(summary, 900)

    return {
        "executive_summary": summary,
        "themes": payload.get("themes") or [],
        "items": top,
        "footer": "Daily digest of public sources. Links included for attribution. Created by Poovannan Rajendran.",
    }


def _move_fca_to_bottom(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    non_fca = []
    fca = []
    for item in items:
        text = _item_text(item)
        if "fca" in text or "financial conduct authority" in text or "warning" in text:
            fca.append(item)
        else:
            non_fca.append(item)
    return non_fca + fca


def _select_linkedin_top(
    items: list[dict[str, Any]],
    min_london: int,
    limit: int,
) -> list[dict[str, Any]]:
    london = [item for item in items if _is_london_market(item)]
    other = [item for item in items if item not in london]
    selected: list[dict[str, Any]] = []

    selected.extend(london[:min_london])
    remaining = limit - len(selected)
    if remaining > 0:
        selected.extend(other[:remaining])
    return selected[:limit]


def _is_london_market(item: dict[str, Any]) -> bool:
    text = _item_text(item)
    keywords = [
        "lloyd",
        "syndicate",
        "broker",
        "lma",
        "london market",
        "ppl",
        "whitespace",
        "coverholder",
        "managing agent",
    ]
    return any(keyword in text for keyword in keywords)


def _item_text(item: dict[str, Any]) -> str:
    parts = [
        item.get("title", ""),
        item.get("why", ""),
        item.get("url", ""),
        item.get("source", ""),
        " ".join(item.get("bullets") or []),
    ]
    return " ".join(str(p).lower() for p in parts if p)


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    deduped: list[dict[str, Any]] = []
    for item in items:
        url = str(item.get("url") or "")
        title = str(item.get("title") or "")
        norm_url = _canonical_url(url)
        if norm_url and norm_url in by_url:
            by_url[norm_url] = _select_best(by_url[norm_url], item)
            continue

        matched = False
        for existing in deduped:
            if _titles_similar(existing, item):
                best = _select_best(existing, item)
                deduped[deduped.index(existing)] = best
                matched = True
                break
        if matched:
            continue

        if norm_url:
            by_url[norm_url] = item
        deduped.append(item)

    # Ensure URL-based best selection is reflected in list
    merged: list[dict[str, Any]] = []
    seen = set()
    for item in deduped:
        norm_url = _canonical_url(str(item.get("url") or ""))
        if norm_url and norm_url in by_url:
            item = by_url[norm_url]
        item_id = item.get("id")
        if item_id in seen:
            continue
        seen.add(item_id)
        merged.append(item)
    return merged


def _canonical_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except Exception:
        return url
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_")
        and k.lower() not in {"ref", "fbclid", "gclid", "mc_cid", "mc_eid"}
    ]
    new_query = urlencode(query, doseq=True)
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, new_query, ""))


def _titles_similar(a: dict[str, Any], b: dict[str, Any]) -> bool:
    a_title = _normalize_title(str(a.get("title") or ""))
    b_title = _normalize_title(str(b.get("title") or ""))
    if not a_title or not b_title:
        return False
    ratio = SequenceMatcher(None, a_title, b_title).ratio()
    return ratio >= 0.92


def _normalize_title(title: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\\s]+", " ", title.lower())
    cleaned = re.sub(r"\\s+", " ", cleaned).strip()
    return cleaned


def _select_best(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    score_a = _item_quality_score(a)
    score_b = _item_quality_score(b)
    if score_b > score_a:
        return b
    return a


def _item_quality_score(item: dict[str, Any]) -> int:
    url = str(item.get("url") or "")
    title = str(item.get("title") or "")
    excerpt = str(item.get("excerpt") or "")
    score = _article_score(url, title, excerpt)
    bullets = item.get("bullets") or []
    if isinstance(bullets, list):
        score += len([b for b in bullets if str(b).strip()])
    why = item.get("why")
    if isinstance(why, str) and why.strip():
        score += 1
    return score


def _resummarize_executive_summary(
    name: str,
    output: dict[str, Any],
    config,
    run_date: str,
) -> dict[str, Any]:
    summary = output.get("executive_summary", "")
    if not isinstance(summary, str):
        return output
    max_chars = int(os.environ.get("EXEC_SUMMARY_MAX_CHARS", "500"))
    if len(summary) <= max_chars:
        return output

    payload = {
        "instructions": "",
        "schema": {"executive_summary": "string"},
        "items": [],
        "summary_text": summary,
    }
    prompt = _build_summary_prompt(payload, config, provider=name)
    input_size = len(prompt)
    started_at = datetime.now(timezone.utc)
    print(
        f"[{name}] start {started_at.isoformat()} chunk=summary input_size={input_size}",
        flush=True,
    )

    fn_map = {
        "local": generate_with_ollama,
        "chatgpt": generate_with_openai,
        "deepseek": generate_with_deepseek,
    }
    fn = fn_map[name]
    try:
        result = fn(payload, config, run_date)
    except Exception as exc:
        print(f"[{name}] summary failed: {exc}", flush=True)
        return output

    new_summary = None
    if isinstance(result, dict):
        new_summary = result.get("executive_summary")
    if isinstance(new_summary, str) and new_summary.strip():
        output["executive_summary"] = _clamp_summary(new_summary.strip(), max_chars)
    finished_at = datetime.now(timezone.utc)
    duration = (finished_at - started_at).total_seconds()
    print(
        f"[{name}] finish {finished_at.isoformat()} chunk=summary duration_s={duration:.1f}",
        flush=True,
    )
    return output


def fetch_recent_articles(hours: int, limit: int) -> list[ArticleItem]:
    import psycopg

    dsn = build_postgres_dsn_from_env()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    sql = """
        SELECT article_id, source_id, url, title, published_at, body_text, created_at
        FROM articles
        WHERE (published_at >= %s)
           OR (published_at IS NULL AND created_at >= %s)
        ORDER BY COALESCE(published_at, created_at) DESC
        LIMIT %s
    """
    items: list[ArticleItem] = []
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (cutoff, cutoff, limit))
            for row in cur.fetchall():
                article_id, source_id, url, title, published_at, body_text, _created_at = row
                excerpt = _trim_text(body_text or "", 800)
                items.append(
                    ArticleItem(
                        article_id=article_id,
                        title=title or url,
                        url=url,
                        published_at=published_at,
                        excerpt=excerpt,
                        source_id=source_id,
                    )
                )
    return items


def build_postgres_dsn_from_env() -> str:
    required = ["POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError(f"Missing Postgres env vars: {', '.join(missing)}")
    return (
        f"host={os.environ['POSTGRES_HOST']} "
        f"port={os.environ['POSTGRES_PORT']} "
        f"dbname={os.environ['POSTGRES_DB']} "
        f"user={os.environ['POSTGRES_USER']} "
        f"password={os.environ['POSTGRES_PASSWORD']}"
    )


def build_prompt_payload(items: list[ArticleItem]) -> dict[str, Any]:
    records = []
    for item in items:
        records.append(
            {
                "id": item.article_id,
                "title": item.title,
                "url": item.url,
                "source": _domain(item.url),
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "excerpt": item.excerpt,
            }
        )
    return {
        "instructions": "",
        "schema": {
            "executive_summary": "string",
            "themes": ["string"],
            "items": [{"id": "string", "why": "string", "bullets": ["string"]}],
        },
        "items": records,
    }


def generate_with_ollama(payload: dict[str, Any], config, run_date: str, model: str | None = None) -> dict[str, Any]:
    model = model or os.environ.get("OLLAMA_MODEL", "qwen3:14b")
    prompt = (
        _build_summary_prompt(payload, config, provider="local")
        if "summary_text" in payload
        else _build_prompt(payload, config, provider="local")
    )
    client = OllamaClient(model=model)
    for attempt in range(1, 4):
        try:
            response = client.generate(prompt)
            return _parse_json(response.get("response", ""), provider="local", run_date=run_date)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2**attempt)


def generate_with_deepseek(payload: dict[str, Any], config, run_date: str) -> dict[str, Any]:
    model = os.environ.get("OLLAMA_DEEPSEEK_MODEL", "deepseek-v3.2:cloud")
    prompt = (
        _build_summary_prompt(payload, config, provider="deepseek")
        if "summary_text" in payload
        else _build_prompt(payload, config, provider="deepseek")
    )
    client = OllamaClient(model=model)
    for attempt in range(1, 4):
        try:
            response = client.generate(prompt)
            return _parse_json(response.get("response", ""), provider="deepseek", run_date=run_date)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2**attempt)


def generate_with_openai(payload: dict[str, Any], config, run_date: str) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    if not api_key:
        return {}
    prompt = _build_summary_prompt(payload, config, provider="chatgpt") if "summary_text" in payload else _build_prompt(payload, config, provider="chatgpt")
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    temperature = 1 if model.startswith("gpt-5") else 0.2
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return JSON only, no markdown."},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
    }
    timeout = float(os.environ.get("OPENAI_TIMEOUT", "120"))
    for attempt in range(1, 4):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, headers=headers, json=body)
                if resp.status_code >= 400:
                    raise httpx.HTTPStatusError(
                        f"OpenAI error {resp.status_code}: {resp.text}",
                        request=resp.request,
                        response=resp,
                    )
                data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return _parse_json(content, provider="chatgpt", run_date=run_date)
        except Exception as exc:
            if attempt == 3:
                print(f"[chatgpt] failed after retries: {exc}", flush=True)
                return {}
            time.sleep(2**attempt)


# OpenRouter/Claude support removed per request.


def render_html(template: str, payload: dict[str, Any], run_date: str) -> str:
    if not payload:
        payload = {"executive_summary": "No output produced.", "themes": [], "items": []}
    max_chars = int(os.environ.get("EXEC_SUMMARY_MAX_CHARS", "500"))
    summary = payload.get("executive_summary", "Summary unavailable.")
    if isinstance(summary, str):
        summary = _clamp_summary(summary, max_chars)
    themes = payload.get("themes") or []
    items = payload.get("items") or []
    footer = payload.get(
        "footer",
        "Daily digest of public sources. Links included for attribution. Created by Poovannan Rajendran.",
    )
    logo_src = payload.get("logo_src", "London_Lloyds_Market_News_Digest.png")
    home_href = payload.get("home_href", "../index.html")
    latest_href = payload.get("latest_href", f"digest_{run_date}.html")

    theme_html = "\n".join(f"<li>{_escape(item)}</li>" for item in themes[:6])
    story_html = "\n".join(_render_story(item) for item in items)

    html = template
    html = html.replace("{{ title }}", _escape(f"Lloyd's Market Digest · {run_date}"))
    html = html.replace("{{ heading }}", "Lloyd's Market Executive Digest")
    html = html.replace("{{ run_date }}", _escape(run_date))
    html = html.replace("{{ executive_summary }}", _escape(summary))
    html = html.replace("{{ themes }}", theme_html or "<li>No themes identified.</li>")
    html = html.replace("{{ stories }}", story_html or "<p>No stories selected.</p>")
    html = html.replace("{{ footer }}", _escape(footer))
    html = html.replace("{{ logo_src }}", _escape(logo_src))
    html = html.replace("{{ home_href }}", _escape(home_href))
    html = html.replace("{{ latest_href }}", _escape(latest_href))
    return html


def _render_story(item: dict[str, Any]) -> str:
    title = _escape(item.get("title", "Untitled"))
    url = _escape(item.get("url", "#"))
    why = _escape(item.get("why", ""))
    bullets = item.get("bullets") or []
    bullet_html = "\n".join(f"<li>{_escape(b)}</li>" for b in bullets[:4])
    return (
        "<article class=\"story\">"
        f"<h3><a href=\"{url}\">{title}</a></h3>"
        f"<div class=\"meta\">Source: {_escape(item.get('source', ''))}</div>"
        f"<div class=\"why\"><strong>Why it matters:</strong> {why}</div>"
        f"<ul>{bullet_html}</ul>"
        "</article>"
    )


def _build_prompt(payload: dict[str, Any], config, provider: str) -> str:
    prompts = (getattr(config, "llm_prompts", None) or {}).get(provider, {})
    system = prompts.get("system", "Return JSON only, no markdown.")
    user = prompts.get(
        "user",
        "You are a senior insurance market editor. Produce JSON only. "
        "Use a professional tone for C-suite executives and insurance consultants. "
        "Focus on Lloyd's market, global specialty, brokers, syndicates, and placement platforms. "
        "Do not include irrelevant items.",
    )
    return (
        f"{system}\n\n{user}\n\n"
        "You MUST end the response with a valid JSON object that closes all brackets (end with ']}').\n"
        "Return JSON exactly with keys: executive_summary, themes, items.\n"
        "Items must include only ids provided. For each item include why and 3 bullets.\n"
        f"Schema: {json.dumps(payload['schema'])}\n\n"
        f"Items: {json.dumps(payload['items'])}"
    )


def _build_summary_prompt(payload: dict[str, Any], config, provider: str) -> str:
    prompts = (getattr(config, "llm_prompts", None) or {}).get(provider, {})
    system = prompts.get("system", "Return JSON only, no markdown.")
    user = prompts.get(
        "user",
        "You are a senior insurance market editor. Produce JSON only. "
        "Use a professional tone for C-suite executives and insurance consultants.",
    )
    return (
        f"{system}\n\n{user}\n\n"
        "You MUST end the response with a valid JSON object that closes all brackets (end with ']}').\n"
        "Rewrite the executive summary to be concise and punchy (max 4 sentences, ~90 words). "
        "Return JSON exactly with key: executive_summary.\n"
        f"Schema: {json.dumps(payload['schema'])}\n\n"
        f"Executive summary: {payload['summary_text']}"
    )


def _parse_json(text: str, provider: str, run_date: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        recovered = _recover_json(text)
        if recovered is not None:
            return recovered
        _write_raw_response(provider, run_date, text)
        return {}


def _recover_json(text: str) -> dict[str, Any] | None:
    fenced = _extract_fenced_json(text)
    if fenced:
        try:
            return json.loads(fenced)
        except Exception:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            return None
    return None


def _extract_fenced_json(text: str) -> str | None:
    marker = "```"
    if marker not in text:
        return None
    parts = text.split(marker)
    for idx in range(1, len(parts), 2):
        block = parts[idx].strip()
        if block.lower().startswith("json"):
            block = block[4:].strip()
        if block.startswith("{") and block.endswith("}"):
            return block
    return None


def _write_raw_response(provider: str, run_date: str, text: str) -> None:
    output_dir = Path("output") / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / f"raw_{provider}_{run_date}.txt"
    rotate_existing(raw_path)
    raw_path.write_text(text, encoding="utf-8")


def enrich_output(prompt_payload: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    items = output.get("items") if isinstance(output, dict) else None
    if not isinstance(items, list):
        return output
    by_id = {item["id"]: item for item in prompt_payload["items"]}
    enriched = []
    for item in items:
        article_id = item.get("id")
        if article_id not in by_id:
            continue
        enriched_item = dict(item)
        enriched_item["title"] = by_id[article_id]["title"]
        enriched_item["url"] = by_id[article_id]["url"]
        enriched_item["source"] = by_id[article_id]["source"]
        enriched_item["excerpt"] = by_id[article_id].get("excerpt", "")
        enriched.append(enriched_item)
    output["items"] = enriched
    return output


def _trim_text(text: str, max_chars: int) -> str:
    cleaned = " ".join(text.split())
    return cleaned[:max_chars]


def _domain(url: str) -> str:
    return urlsplit(url).netloc.replace("www.", "")


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\"", "&quot;")
        .replace("'", "&#39;")
    )


def rotate_existing(path: Path) -> None:
    if not path.exists():
        return
    try:
        ts = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d_%H%M%S")
    except Exception:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rotated = path.with_name(f"{ts}_{path.name}")
    path.rename(rotated)


def _ensure_logo_asset(target_dir: Path) -> None:
    logo = Path("src/images/London_Lloyds_Market_News_Digest.png")
    if not logo.exists():
        return
    target = target_dir / logo.name
    if target.exists():
        return
    try:
        target.write_bytes(logo.read_bytes())
    except Exception:
        return


if __name__ == "__main__":
    main()
