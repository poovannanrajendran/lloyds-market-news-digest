from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from lloyds_digest.ai.costing import compute_cost_usd
from lloyds_digest.storage.postgres_repo import PostgresRepo
from lloyds_digest.utils import load_env_file


PROMPT_TEMPLATE = """You are my LinkedIn editor for the London Lloyd’s Market News Digest.

TASK
1) Read today’s public digest HTML file from this repo and extract the key content:
   - Executive summary (if present)
   - Key themes (if present)
   - Highlights / story cards (titles, source domains, and any “why it matters” bullets)

2) Create a LinkedIn post that:
   - Sounds like a real person (not corporate, not “AI voice”)
   - Is relevant to London Market / specialty insurance professionals
   - Includes EXACTLY 4 clear highlights, each in this format:
     1) <specific topic> - Why it matters: <specific impact in 1 sentence>
   - Uses only concrete facts from the digest highlights; do not invent items
   - Includes a short “why it matters” framing (1–2 sentences)
   - Includes the public digest link
   - Uses 6–10 hashtags max (LondonMarket/Lloyds/Insurance/Reinsurance/InsurTech/AI etc.)
   - Avoids marketing fluff and avoids repeating the same point twice
   - Avoids “confidential/internal use” language (this is the public digest)

INPUTS
- Digest date: {run_date}
- Public digest link: {public_link}

EXECUTIVE SUMMARY
{executive_summary}

KEY THEMES
{themes}

HIGHLIGHTS
{highlights}

OUTPUT
Return ONLY:
A) A single LinkedIn post (plain text), ready to paste into LinkedIn
B) A short “Alt text” line for the banner image (1 sentence)

STYLE RULES
- Max 1,200 characters for the post unless the digest is unusually important.
- Start with a strong first line (hook) about the London Market signal.
- Highlights must be specific (not generic “market volatility”).
- Never output placeholders such as "N/A", "none identified", "no detail available", or "nothing urgent"
  when highlights are provided in the input.
- If the digest includes regulatory warnings or scam-related items, include at most ONE and only if it’s clearly relevant to insurers/brokers.
- Keep UK English spelling.
"""

_GENERIC_PHRASES = (
    "none identified",
    "n/a",
    "no detail available",
    "nothing urgent",
    "no items met",
    "blank digest",
    "no third-party articles",
    "story cards: n/a",
)

_NOISE_TITLE_PATTERNS = (
    "archive",
    "calendar",
    "search results",
    "page ",
)


def main() -> None:
    load_env_file(Path(".env"))
    args = _parse_args()

    digest_path = Path(args.digest_path) if args.digest_path else _find_latest_digest()
    if not digest_path or not digest_path.exists():
        print("Digest file not found. Run the pipeline/render step first.")
        return

    digest_date = _extract_date(digest_path.name)
    if digest_date is None:
        digest_date = datetime.now().date().isoformat()

    html = digest_path.read_text(encoding="utf-8")
    parsed = _parse_digest(html)

    public_link = _build_public_link(digest_path.name)
    prompt = PROMPT_TEMPLATE.format(
        run_date=digest_date,
        public_link=public_link,
        executive_summary=parsed["executive_summary"] or "N/A",
        themes="\n".join(f"- {theme}" for theme in parsed["themes"]) or "N/A",
        highlights="\n".join(parsed["highlights"]) or "N/A",
    )

    render_start = datetime.now(timezone.utc)
    response = _generate_with_openai(prompt)
    if not response:
        print("Failed to generate LinkedIn post. Check OPENAI_API_KEY.")
        return

    formatted = _format_linkedin_response(response, digest_date)
    if _should_use_fallback_post(formatted, parsed, public_link):
        print("LinkedIn output quality check failed; using digest-derived fallback.")
        formatted = _build_fallback_post(parsed, digest_date, public_link)
    print(formatted.strip())

    output_dir = Path("output") / "linkedin"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"linkedin_post_{digest_date}.txt"
    out_path.write_text(formatted.strip() + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}")
    _log_phase_timing("render_linkedin", render_start, datetime.now(timezone.utc))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a LinkedIn post from a digest HTML file.")
    parser.add_argument(
        "--digest-path",
        type=str,
        default="",
        help="Path to digest HTML file (defaults to latest in docs/digests or output).",
    )
    return parser.parse_args()


def _find_latest_digest() -> Path | None:
    candidates = []
    for base in (Path("docs") / "digests", Path("output")):
        if not base.exists():
            continue
        candidates.extend(base.glob("digest_*.html"))

    dated = []
    for path in candidates:
        date = _extract_date(path.name)
        if date:
            dated.append((date, path))

    if dated:
        dated.sort(key=lambda pair: pair[0], reverse=True)
        return dated[0][1]

    if candidates:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    return None


def _extract_date(filename: str) -> str | None:
    match = re.search(r"digest_(\d{4}-\d{2}-\d{2})\.html$", filename)
    return match.group(1) if match else None


def _parse_digest(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    summary = ""
    summary_node = soup.select_one(".summary")
    if summary_node:
        summary = summary_node.get_text(strip=True)

    themes = []
    for li in soup.select(".themes li"):
        text = li.get_text(strip=True)
        if text:
            themes.append(text)

    highlights = []
    stories: list[dict[str, Any]] = []
    for story in soup.select("article.story"):
        title_node = story.select_one("h3 a")
        title = _clean_title(title_node.get_text(strip=True) if title_node else "Untitled")
        url = title_node["href"] if title_node and title_node.has_attr("href") else ""
        source = story.select_one(".meta")
        source_text = source.get_text(strip=True).replace("Source:", "").strip() if source else ""
        why_node = story.select_one(".why")
        why_text = ""
        if why_node:
            why_text = why_node.get_text(" ", strip=True).replace("Why it matters:", "").strip()
            why_text = _clean_text(why_text)
        bullets = [li.get_text(strip=True) for li in story.select("ul li") if li.get_text(strip=True)]
        bullets = [_clean_text(item) for item in bullets if item]

        highlight_lines = [
            f"- Title: {title}",
            f"  Source: {source_text}" if source_text else "  Source: N/A",
            f"  URL: {url}" if url else "  URL: N/A",
        ]
        if why_text:
            highlight_lines.append(f"  Why: {why_text}")
        if bullets:
            highlight_lines.append(f"  Bullets: {', '.join(bullets)}")
        highlights.append("\n".join(highlight_lines))
        stories.append(
            {
                "title": title,
                "url": url,
                "source": source_text,
                "why": why_text,
                "bullets": bullets,
            }
        )

    return {
        "executive_summary": summary,
        "themes": themes,
        "highlights": highlights[:25],
        "stories": stories,
    }


def _clean_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    return cleaned.strip(" -,:;.")


def _clean_title(title: str) -> str:
    cleaned = _clean_text(title)
    cleaned = re.sub(r"\s*[-|]\s*Business Insurance$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*[-|]\s*Artemis\.bm$", "", cleaned, flags=re.IGNORECASE)
    return cleaned


def _is_generic_text(text: str) -> bool:
    low = text.lower()
    return any(phrase in low for phrase in _GENERIC_PHRASES)


def _is_noise_story(story: dict[str, Any]) -> bool:
    title = (story.get("title") or "").lower()
    source = (story.get("source") or "").lower()
    url = (story.get("url") or "").lower()
    if not title:
        return True
    if any(pattern in title for pattern in _NOISE_TITLE_PATTERNS):
        return True
    if "newsnow.co.uk" in source or "newsnow.co.uk" in url:
        return True
    if "ajax_calendar" in url:
        return True
    return False


def _score_story(story: dict[str, Any]) -> int:
    score = 0
    source = (story.get("source") or "").lower()
    title = (story.get("title") or "").lower()
    why = story.get("why") or ""
    if source in {"fca.org.uk", "ldc.lloyds.com"}:
        score += 5
    if any(token in title for token in ("lloyd", "fca", "reinsurance", "cat bond", "regulator")):
        score += 3
    if len(why) > 90:
        score += 2
    if story.get("bullets"):
        score += 1
    return score


def _select_relevant_stories(stories: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    seen: set[str] = set()
    for story in stories:
        if _is_noise_story(story):
            continue
        title = _clean_title(story.get("title", ""))
        if not title:
            continue
        key = re.sub(r"[^a-z0-9]+", "", title.lower())
        if not key or key in seen:
            continue
        seen.add(key)
        normalized = dict(story)
        normalized["title"] = title
        normalized["why"] = _clean_text(story.get("why", ""))
        normalized["bullets"] = [item for item in (story.get("bullets") or []) if item]
        clean.append(normalized)
    clean.sort(key=_score_story, reverse=True)
    return clean[:limit]


def _extract_post_highlight_lines(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [re.sub(r"^(?:\d+\)|[-*])\s*", "", line).strip() for line in lines if re.match(r"^(?:\d+\)|[-*])\s+", line)]


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _contains_public_link(text: str, public_link: str) -> bool:
    return public_link in text


def _should_use_fallback_post(post_text: str, parsed: dict[str, Any], public_link: str) -> bool:
    selected = _select_relevant_stories(parsed.get("stories", []), limit=8)
    available_count = len(selected)
    if available_count == 0:
        return False

    highlight_lines = _extract_post_highlight_lines(post_text)
    non_generic_highlights = [line for line in highlight_lines if line and not _is_generic_text(line)]
    headline = _first_line(post_text)
    weak_headline = not headline or _is_generic_text(headline)

    required = 4 if available_count >= 4 else 3 if available_count >= 3 else 2
    if len(non_generic_highlights) < required:
        return True
    if weak_headline:
        return True
    if not _contains_public_link(post_text, public_link):
        return True
    return False


def _shorten(text: str, max_chars: int) -> str:
    cleaned = _clean_text(text)
    if len(cleaned) <= max_chars:
        return cleaned
    trimmed = cleaned[: max_chars - 3].rstrip(" ,.-")
    return f"{trimmed}..."


def _story_detail(story: dict[str, Any]) -> str:
    why = _clean_text(story.get("why", ""))
    if why:
        return _shorten(why, 180)
    bullets = story.get("bullets") or []
    if bullets:
        return _shorten(_clean_text(bullets[0]), 180)
    return "Implications for underwriting, distribution, and risk governance should be reviewed."


def _build_fallback_headline(stories: list[dict[str, Any]], digest_date: str) -> str:
    try:
        dt = datetime.strptime(digest_date, "%Y-%m-%d")
        date_label = dt.strftime("%d %b %Y")
    except ValueError:
        date_label = digest_date
    if not stories:
        return f"London market signal for {date_label}: operational and regulatory watchpoints for insurance leaders."
    primary = _shorten(stories[0].get("title", "London market signal"), 90)
    if len(stories) > 1:
        secondary = _shorten(stories[1].get("title", ""), 70)
        return f"London market signal for {date_label}: {primary}; {secondary}."
    return f"London market signal for {date_label}: {primary}."


def _build_fallback_why(parsed: dict[str, Any], stories: list[dict[str, Any]]) -> str:
    summary = _clean_text(parsed.get("executive_summary", ""))
    if summary and not _is_generic_text(summary):
        return _shorten(summary, 230)
    if stories:
        return _shorten(_story_detail(stories[0]), 230)
    return "These developments affect placement confidence, controls, and capacity planning across the London specialty market."


def _build_fallback_post(parsed: dict[str, Any], digest_date: str, public_link: str) -> str:
    stories = _select_relevant_stories(parsed.get("stories", []), limit=8)
    highlights = stories[:4]
    while len(highlights) < 4 and parsed.get("themes"):
        idx = len(highlights)
        theme = parsed["themes"][idx % len(parsed["themes"])]
        highlights.append(
            {
                "title": _shorten(_clean_text(theme), 72),
                "why": "Monitor placement and underwriting impact across brokers, syndicates, and market platforms.",
                "bullets": [],
                "source": "",
                "url": "",
            }
        )
    while len(highlights) < 4:
        highlights.append(
            {
                "title": f"Market update {len(highlights) + 1}",
                "why": "Review portfolio impact and actions with underwriting and distribution teams.",
                "bullets": [],
                "source": "",
                "url": "",
            }
        )

    lines = [_build_fallback_headline(highlights, digest_date), "", "Highlights:"]
    for i, item in enumerate(highlights[:4], start=1):
        title = _shorten(item.get("title", ""), 84)
        detail = _story_detail(item)
        lines.append(f"{i}) {title} - Why it matters: {detail}")

    lines.extend(
        [
            "",
            f"Why it matters: {_build_fallback_why(parsed, highlights)}",
            "",
            f"Read the public digest: {public_link}",
            "",
            "#LondonMarket #Lloyds #Insurance #Reinsurance #SpecialtyInsurance #InsurTech",
            "",
            f"Alt text: {_shorten(_build_fallback_headline(highlights, digest_date), 140)}",
        ]
    )
    return _format_linkedin_response("\n".join(lines), digest_date)


def _build_public_link(filename: str) -> str:
    base_url = os.environ.get(
        "GITHUB_PAGES_BASE_URL",
        "https://poovannanrajendran.github.io/lloyds-market-news-digest/digests/",
    )
    return f"{base_url}{filename}"


def _format_linkedin_response(text: str, digest_date: str) -> str:
    output = text.strip()
    output = _replace_lead_todays(output, digest_date)
    output = re.sub(
        r"^(\d{2}-[A-Za-z]{3}'s\s+)([a-z])",
        lambda m: f"{m.group(1)}{m.group(2).upper()}",
        output,
        count=1,
    )
    output = _capitalize_heading_lines(output)
    output = re.sub(r":\s*([A-Za-z][^\s]*)", _capitalize_after_colon, output)
    return output


def _replace_lead_todays(text: str, digest_date: str) -> str:
    try:
        prefix = datetime.strptime(digest_date, "%Y-%m-%d").strftime("%d-%b")
    except ValueError:
        prefix = digest_date
    replacement = f"{prefix}'s"
    return re.sub(r"^\s*today'?s\b", replacement, text, count=1, flags=re.IGNORECASE)


def _capitalize_heading_lines(text: str) -> str:
    lines = text.splitlines()
    out_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and stripped.endswith(":") and not stripped.startswith(("#", "-", "*", "1.", "2.", "3.", "4.", "5.")):
            out_lines.append(line[: len(line) - len(stripped)] + stripped[:1].upper() + stripped[1:])
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def _capitalize_after_colon(match: re.Match[str]) -> str:
    token = match.group(1)
    if token.lower().startswith(("http://", "https://", "www.")):
        return f": {token}"
    return f": {token[:1].upper()}{token[1:]}"


def _generate_with_openai(prompt: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("OPENAI_LINKEDIN_MODEL", os.environ.get("OPENAI_MODEL", "gpt-5-mini"))
    if not api_key:
        return ""

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    use_temperature = not model.startswith("gpt-5")
    service_tier = os.environ.get("OPENAI_LINKEDIN_SERVICE_TIER", "flex").strip() or "flex"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return only the final output. No markdown."},
            {"role": "user", "content": prompt},
        ],
        "service_tier": service_tier,
    }
    if use_temperature:
        body["temperature"] = 0.3
    timeout = float(os.environ.get("OPENAI_LINKEDIN_TIMEOUT", "600"))
    max_attempts = int(os.environ.get("OPENAI_LINKEDIN_RETRIES", "3"))
    for attempt in range(1, max_attempts + 1):
        try:
            print(
                f"OpenAI request start (attempt {attempt}/{max_attempts}) "
                f"model={model} timeout_s={int(timeout)}",
                flush=True,
            )
            started = time.time()
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, headers=headers, json=body)
                if resp.status_code >= 500:
                    raise RuntimeError(f"OpenAI error {resp.status_code}: {resp.text}")
                if resp.status_code >= 400:
                    raise RuntimeError(f"OpenAI error {resp.status_code}: {resp.text}")
                data = resp.json()
            content = data["choices"][0]["message"]["content"]
            output_text = content.strip()
            usage = data.get("usage", {}) if isinstance(data, dict) else {}
            elapsed = time.time() - started
            print(f"OpenAI request done in {elapsed:.1f}s", flush=True)
            _record_llm_usage_and_cost(
                model=model,
                prompt=prompt,
                output_text=output_text,
                service_tier=service_tier,
                tokens_prompt=usage.get("prompt_tokens"),
                tokens_completion=usage.get("completion_tokens"),
                tokens_cached_input=((usage.get("prompt_tokens_details") or {}).get("cached_tokens")),
            )
            return output_text
        except Exception as exc:
            if attempt == max_attempts:
                raise
            sleep_s = 2**attempt
            print(f"OpenAI call failed (attempt {attempt}): {exc}. Retrying in {sleep_s}s...")
            time.sleep(sleep_s)
    return ""


def _record_llm_usage_and_cost(
    model: str,
    prompt: str,
    output_text: str,
    service_tier: str | None,
    tokens_prompt: int | None = None,
    tokens_completion: int | None = None,
    tokens_cached_input: int | None = None,
) -> None:
    if tokens_prompt is None:
        tokens_prompt = _estimate_tokens(prompt)
    if tokens_completion is None:
        tokens_completion = _estimate_tokens(output_text)
    try:
        dsn = _build_postgres_dsn_from_env()
    except Exception:
        return
    try:
        postgres = PostgresRepo(dsn)
        run_id = _latest_run_id(postgres)
        started_at = datetime.now()
        postgres.insert_llm_usage(
            run_id=run_id,
            candidate_id=None,
            stage="render_linkedin",
            model=model,
            prompt_version="v1",
            cached=False,
            started_at=started_at,
            ended_at=started_at,
            latency_ms=0,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            metadata={"program": "render_linkedin_post.py"},
        )
        cost = compute_cost_usd(
            model=model,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            service_tier=service_tier,
            tokens_cached_input=tokens_cached_input,
        )
        if cost is None:
            return
        input_cost, output_cost, total_cost = cost
        postgres.insert_llm_cost_call(
            run_id=run_id,
            candidate_id=None,
            stage="render_linkedin",
            provider="openai",
            model=model,
            service_tier=service_tier,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            cost_input_usd=input_cost,
            cost_output_usd=output_cost,
            cost_total_usd=total_cost,
            metadata={"program": "render_linkedin_post.py"},
        )
        usage_date = datetime.now().date().isoformat()
        postgres.upsert_llm_cost_stage_daily(
            usage_date=usage_date,
            stage="render_linkedin",
            provider="openai",
            model=model,
            service_tier=service_tier,
            calls=1,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            cost_total_usd=total_cost,
        )
    except Exception:
        return


def _log_phase_timing(phase: str, started_at: datetime, ended_at: datetime) -> None:
    try:
        dsn = _build_postgres_dsn_from_env()
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
            metadata={"program": "render_linkedin_post.py"},
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


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _build_postgres_dsn_from_env() -> str:
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


if __name__ == "__main__":
    main()
