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

from lloyds_digest.utils import load_env_file
from lloyds_digest.storage.postgres_repo import PostgresRepo
from lloyds_digest.ai.costing import compute_cost_usd


PROMPT_TEMPLATE = """You are my LinkedIn editor for the London Lloyd’s Market News Digest.

TASK
1) Read today’s public digest HTML file from this repo and extract the key content:
   - Executive summary (if present)
   - Key themes (if present)
   - Highlights / story cards (titles, source domains, and any “why it matters” bullets)

2) Create a LinkedIn post that:
   - Sounds like a real person (not corporate, not “AI voice”)
   - Is relevant to London Market / specialty insurance professionals
   - Includes AT LEAST 3 clear highlights (bulleted or numbered)
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
- If the digest includes regulatory warnings or scam-related items, include at most ONE and only if it’s clearly relevant to insurers/brokers.
- Keep UK English spelling.
"""


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
    for story in soup.select("article.story"):
        title_node = story.select_one("h3 a")
        title = title_node.get_text(strip=True) if title_node else "Untitled"
        url = title_node["href"] if title_node and title_node.has_attr("href") else ""
        source = story.select_one(".meta")
        source_text = source.get_text(strip=True).replace("Source:", "").strip() if source else ""
        why_node = story.select_one(".why")
        why_text = ""
        if why_node:
            why_text = why_node.get_text(" ", strip=True).replace("Why it matters:", "").strip()
        bullets = [li.get_text(strip=True) for li in story.select("ul li") if li.get_text(strip=True)]

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

    return {
        "executive_summary": summary,
        "themes": themes,
        "highlights": highlights[:25],
    }


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
