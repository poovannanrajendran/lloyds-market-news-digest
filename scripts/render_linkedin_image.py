#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
from datetime import date
from pathlib import Path

import requests
from PIL import Image
from io import BytesIO

from lloyds_digest.utils import load_env_file


def _latest_linkedin_post(path: Path) -> Path | None:
    if not path.exists():
        return None
    candidates = sorted(path.glob("linkedin_post_*.txt"), reverse=True)
    return candidates[0] if candidates else None


def _date_from_filename(path: Path) -> str | None:
    stem = path.stem
    if stem.startswith("linkedin_post_"):
        return stem.replace("linkedin_post_", "")
    return None


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _build_prompt(title: str, run_date: str, post_text: str) -> str:
    return (
        "Create a clean, executive LinkedIn banner image for an insurance market digest. "
        "Use a professional, high-contrast layout with room for text. "
        "Include the provided logo as a prominent but tasteful mark (top-left preferred). "
        "Overlay the title and date in a refined serif/sans pairing. "
        "Keep the background in navy/teal with subtle gradient, and accents in muted gold. "
        "Place the LinkedIn post text as a short excerpt area (3–5 lines max), "
        "ensuring legibility and generous margins. "
        f"Title: {title}. Date: {run_date}. "
        "Post excerpt (do not add hashtags):\n"
        f"{post_text}\n"
    )


def _openrouter_headers(api_key: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    site = os.environ.get("OPENROUTER_SITE_URL")
    app = os.environ.get("OPENROUTER_APP_NAME")
    if site:
        headers["HTTP-Referer"] = site
    if app:
        headers["X-Title"] = app
    return headers


def _openai_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _image_bytes_from_response(data: dict) -> bytes:
    try:
        images = data["choices"][0]["message"]["images"]
        image_url = images[0]["image_url"]["url"]
    except Exception as exc:
        raise RuntimeError(f"Unexpected response format: {exc}") from exc

    if not image_url.startswith("data:image/"):
        raise RuntimeError("Image response missing data URL")
    _, b64 = image_url.split(",", 1)
    return base64.b64decode(b64)


def _overlay_logo(base_image: bytes, logo_path: Path) -> bytes:
    with Image.open(BytesIO(base_image)).convert("RGBA") as img:
        with Image.open(logo_path).convert("RGBA") as logo:
            logo = logo.resize((160, 160), Image.LANCZOS)
            margin = 40
            img.paste(logo, (margin, margin), logo)
        output = BytesIO()
        img.save(output, format="PNG")
        return output.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description="Render LinkedIn image via OpenRouter")
    parser.add_argument("--post-file", type=Path, default=None)
    parser.add_argument("--logo", type=Path, default=Path("src/images/London_Lloyds_Market_News_Digest.png"))
    parser.add_argument("--title", default="Lloyd's Market Executive Digest")
    parser.add_argument("--date", dest="run_date", default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    load_env_file(".env")
    openai_model = os.environ.get("OPENAI_IMAGE_MODEL")
    openrouter_model = os.environ.get("OPENROUTER_IMAGE_MODEL")
    if not openai_model and not openrouter_model:
        raise SystemExit("Set OPENAI_IMAGE_MODEL or OPENROUTER_IMAGE_MODEL")

    openai_timeout_s = int(os.environ.get("OPENAI_IMAGE_TIMEOUT", "180"))
    openrouter_timeout_s = int(os.environ.get("OPENROUTER_IMAGE_TIMEOUT", "180"))
    aspect_ratio = os.environ.get("OPENROUTER_IMAGE_ASPECT_RATIO", "16:9")
    image_size = os.environ.get("OPENAI_IMAGE_SIZE", "1024x1024")
    image_quality = os.environ.get("OPENAI_IMAGE_QUALITY", "low")

    post_dir = Path("output/linkedin")
    post_path = args.post_file or _latest_linkedin_post(post_dir)
    if not post_path:
        raise SystemExit("No LinkedIn post file found.")

    run_date = args.run_date or _date_from_filename(post_path) or date.today().isoformat()
    post_text = _read_text(post_path)

    logo_path = args.logo
    if not logo_path.exists():
        raise SystemExit(f"Logo not found: {logo_path}")
    prompt = _build_prompt(args.title, run_date, post_text)

    image_bytes: bytes
    if openai_model:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise SystemExit("OPENAI_API_KEY is required for OPENAI_IMAGE_MODEL")
        payload = {
            "model": openai_model,
            "prompt": prompt,
            "size": image_size,
            "quality": image_quality,
        }
        response = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers=_openai_headers(api_key),
            data=json.dumps(payload),
            timeout=openai_timeout_s,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"OpenAI error {response.status_code}: {response.text}")
        data = response.json()
        image_bytes = base64.b64decode(data["data"][0]["b64_json"])
    else:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise SystemExit("OPENROUTER_API_KEY is required for OPENROUTER_IMAGE_MODEL")
        payload = {
            "model": openrouter_model,
            "messages": [{"role": "user", "content": prompt}],
            "modalities": ["image", "text"],
            "image_config": {"aspect_ratio": aspect_ratio},
            "stream": False,
        }
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=_openrouter_headers(api_key),
            data=json.dumps(payload),
            timeout=openrouter_timeout_s,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"OpenRouter error {response.status_code}: {response.text}")
        image_bytes = _image_bytes_from_response(response.json())

    out_dir = Path("output/linkedin_images")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out or out_dir / f"linkedin_image_{run_date}.png"
    base_path = out_path.with_name(out_path.stem + "_base.png")
    base_path.write_bytes(image_bytes)

    # composite logo locally
    composite_bytes = _overlay_logo(image_bytes, logo_path)
    out_path.write_bytes(composite_bytes)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
