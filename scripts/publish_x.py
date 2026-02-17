#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from requests_oauthlib import OAuth1Session

from lloyds_digest.ai.costing import compute_cost_usd
from lloyds_digest.storage.postgres_repo import PostgresRepo
from lloyds_digest.utils import load_env_file


@dataclass
class XCredentials:
    api_key: str
    api_secret: str
    access_token: str
    access_token_secret: str


def _latest_digest_path() -> Path | None:
    docs = Path("docs/digests")
    output = Path("output")
    candidates = []
    if docs.exists():
        candidates.extend(docs.glob("digest_*.html"))
    if output.exists():
        candidates.extend(output.glob("digest_*.html"))
    if not candidates:
        return None
    return sorted(candidates, key=lambda p: p.name, reverse=True)[0]


def _latest_linkedin_post() -> Path | None:
    folder = Path("output/linkedin")
    if not folder.exists():
        return None
    posts = sorted(folder.glob("linkedin_post_*.txt"), reverse=True)
    return posts[0] if posts else None


def _digest_date_from_name(path: Path) -> str | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    return match.group(1) if match else None


def _digest_url(date_str: str) -> str:
    base_url = os.environ.get(
        "GITHUB_PAGES_BASE_URL",
        "https://poovannanrajendran.github.io/lloyds-market-news-digest/digests/",
    )
    return f"{base_url}digest_{date_str}.html"


def _load_credentials() -> XCredentials:
    api_key = os.environ.get("X_API_KEY", "").strip()
    api_secret = os.environ.get("X_API_SECRET", "").strip()
    access_token = os.environ.get("X_ACCESS_TOKEN", "").strip()
    access_token_secret = os.environ.get("X_ACCESS_TOKEN_SECRET", "").strip()
    if not all([api_key, api_secret, access_token, access_token_secret]):
        raise SystemExit("Missing X API credentials in .env")
    return XCredentials(api_key, api_secret, access_token, access_token_secret)


def _hashtags() -> list[str]:
    raw = os.environ.get("X_HASHTAGS", "")
    tags = [tag.strip().lstrip("#") for tag in raw.split(",") if tag.strip()]
    return tags[:3]


def _openai_shortener(prompt: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("OPENAI_LINKEDIN_MODEL", os.environ.get("OPENAI_MODEL", "gpt-4o"))
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is required for shortening")
    service_tier = os.environ.get("OPENAI_LINKEDIN_SERVICE_TIER", "").strip()
    timeout = float(os.environ.get("OPENAI_LINKEDIN_TIMEOUT", "600"))
    max_attempts = int(os.environ.get("OPENAI_LINKEDIN_RETRIES", "3"))
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return only the final tweet text. No quotes, no markdown."},
            {"role": "user", "content": prompt},
        ],
    }
    if service_tier:
        body["service_tier"] = service_tier
    if not model.startswith("gpt-5"):
        body["temperature"] = 0.2

    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                started = time.time()
                resp = client.post(url, headers=headers, json=body)
                if resp.status_code >= 400:
                    raise RuntimeError(f"OpenAI error {resp.status_code}: {resp.text}")
                data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
            usage = data.get("usage", {}) if isinstance(data, dict) else {}
            _record_llm_usage_and_cost(
                model,
                prompt,
                text,
                service_tier or None,
                tokens_prompt=usage.get("prompt_tokens"),
                tokens_completion=usage.get("completion_tokens"),
            )
            elapsed = time.time() - started
            print(f"OpenAI shortener done in {elapsed:.1f}s", flush=True)
            return text
        except Exception as exc:
            if attempt == max_attempts:
                raise
            sleep_s = 2**attempt
            print(f"Shortener failed (attempt {attempt}): {exc}. Retrying in {sleep_s}s...", flush=True)
            time.sleep(sleep_s)
    return ""


def _record_llm_usage_and_cost(
    model: str,
    prompt: str,
    output_text: str,
    service_tier: str | None,
    tokens_prompt: int | None = None,
    tokens_completion: int | None = None,
) -> None:
    if tokens_prompt is None:
        tokens_prompt = max(1, len(prompt) // 4) if prompt else None
    if tokens_completion is None:
        tokens_completion = max(1, len(output_text) // 4) if output_text else None
    try:
        dsn = _build_postgres_dsn_from_env()
    except Exception:
        return
    try:
        postgres = PostgresRepo(dsn)
        run_id = postgres.get_latest_run_id()
        now = datetime.now(timezone.utc)
        postgres.insert_llm_usage(
            run_id=run_id,
            candidate_id=None,
            stage="render_x",
            model=model,
            prompt_version="v1",
            cached=False,
            started_at=now,
            ended_at=now,
            latency_ms=0,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            metadata={"program": "publish_x.py"},
        )
        if tokens_prompt is None or tokens_completion is None:
            return
        cost = compute_cost_usd(
            model=model,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            service_tier=service_tier,
        )
        if cost is None:
            return
        input_cost, output_cost, total_cost = cost
        postgres.insert_llm_cost_call(
            run_id=run_id,
            candidate_id=None,
            stage="render_x",
            provider="openai",
            model=model,
            service_tier=service_tier,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            cost_input_usd=input_cost,
            cost_output_usd=output_cost,
            cost_total_usd=total_cost,
            metadata={"program": "publish_x.py"},
        )
        usage_date = datetime.now(timezone.utc).date().isoformat()
        postgres.upsert_llm_cost_stage_daily(
            usage_date=usage_date,
            stage="render_x",
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


def _build_postgres_dsn_from_env() -> str:
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    name = os.environ.get("POSTGRES_DB")
    user = os.environ.get("POSTGRES_USER")
    password = os.environ.get("POSTGRES_PASSWORD")
    if not all([name, user, password]):
        raise ValueError("Missing Postgres env vars")
    return f"host={host} port={port} dbname={name} user={user} password={password}"


def _upload_media(session: OAuth1Session, image_path: Path) -> str:
    url = "https://upload.twitter.com/1.1/media/upload.json"
    with image_path.open("rb") as handle:
        files = {"media": handle}
        resp = session.post(url, files=files)
    if resp.status_code >= 400:
        raise RuntimeError(f"Media upload failed: {resp.status_code} {resp.text}")
    return resp.json()["media_id_string"]


def _post_tweet(session: OAuth1Session, text: str, media_id: str | None) -> dict:
    url = "https://api.x.com/2/tweets"
    payload: dict[str, object] = {"text": text}
    if media_id:
        payload["media"] = {"media_ids": [media_id]}
    resp = session.post(url, json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(f"Tweet failed: {resp.status_code} {resp.text}")
    return resp.json()


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish digest to X")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_env_file(".env")
    creds = _load_credentials()

    digest_path = _latest_digest_path()
    if not digest_path:
        raise SystemExit("No digest HTML found")
    date_str = _digest_date_from_name(digest_path) or datetime.now().date().isoformat()
    digest_url = _digest_url(date_str)

    post_path = _latest_linkedin_post()
    if not post_path:
        raise SystemExit("No LinkedIn post found")
    base_text = post_path.read_text(encoding="utf-8").strip()

    tags = _hashtags()
    hashtags = " ".join([f"#{tag}" for tag in tags])

    prompt = (
        "Rewrite the following into a concise X post (max 260 characters). "
        "Keep a professional tone. Include the provided URL and the hashtags at the end. "
        "Do not use bullet points. Return only the post text.\n\n"
        f"URL: {digest_url}\n"
        f"Hashtags: {hashtags}\n\n"
        f"Source text:\n{base_text}\n"
    )

    text = _openai_shortener(prompt)
    if len(text) > 280:
        text = text[:277] + "..."

    image_path = Path(f"output/linkedin_images/linkedin_image_{date_str}.png")
    media_id = None

    if args.dry_run:
        print(text)
        return

    session = OAuth1Session(
        creds.api_key,
        client_secret=creds.api_secret,
        resource_owner_key=creds.access_token,
        resource_owner_secret=creds.access_token_secret,
    )

    if image_path.exists():
        media_id = _upload_media(session, image_path)

    result = _post_tweet(session, text, media_id)
    print(f"Posted: {result.get('data', {}).get('id', 'unknown')}")


if __name__ == "__main__":
    main()
