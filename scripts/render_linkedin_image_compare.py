#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Iterable

import requests
from PIL import Image, ImageDraw

from lloyds_digest.utils import load_env_file


def _latest_linkedin_post(path: Path) -> Path | None:
    if not path.exists():
        return None
    candidates = sorted(path.glob("linkedin_post_*.txt"), reverse=True)
    return candidates[0] if candidates else None


def _date_from_filename(path: Path) -> str | None:
    match = re.search(r"linkedin_post_(\d{4}-\d{2}-\d{2})\.txt$", path.name)
    return match.group(1) if match else None


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _build_prompt(post_text: str) -> str:
    return (
        "Can you please create an image for the below LinkedIn post?\n\n"
        f"{post_text}"
    )


def _openai_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _generate_image(api_key: str, model: str, quality: str, size: str, prompt: str) -> bytes:
    payload = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
    }
    response = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers=_openai_headers(api_key),
        data=json.dumps(payload),
        timeout=300,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"{model} ({quality}) failed: {response.status_code} {response.text}")
    data = response.json()
    return base64.b64decode(data["data"][0]["b64_json"])


def _safe_name(model: str) -> str:
    return model.replace("/", "-")


def _build_side_by_side(
    left_path: Path,
    right_path: Path,
    left_label: str,
    right_label: str,
    out_path: Path,
) -> None:
    left = Image.open(left_path).convert("RGB")
    right = Image.open(right_path).convert("RGB")
    if left.size != right.size:
        raise ValueError(f"Image sizes differ: {left.size} vs {right.size}")

    w, h = left.size
    top_pad = 72
    gap = 24
    canvas = Image.new("RGB", (w * 2 + gap, h + top_pad), (245, 245, 245))
    draw = ImageDraw.Draw(canvas)
    draw.text((24, 20), left_label, fill=(30, 30, 30))
    draw.text((w + gap + 24, 20), right_label, fill=(30, 30, 30))
    canvas.paste(left, (0, top_pad))
    canvas.paste(right, (w + gap, top_pad))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG")


def _cost_per_image(model: str, quality: str, size: str) -> float | None:
    # Official model docs pricing for 1024x1024 as of 2026-02-28.
    table = {
        ("chatgpt-image-latest", "medium", "1024x1024"): 0.034,
        ("gpt-image-1-mini", "high", "1024x1024"): 0.036,
        ("gpt-image-1", "medium", "1024x1024"): 0.063,
    }
    return table.get((model, quality, size))


def _print_costs(rows: Iterable[tuple[str, str, str]]) -> None:
    total_day = 0.0
    print("\nEstimated image generation costs:")
    for model, quality, size in rows:
        unit = _cost_per_image(model, quality, size)
        if unit is None:
            print(f"- {model} ({quality}, {size}): unknown")
            continue
        total_day += unit
        print(f"- {model} ({quality}, {size}): ${unit:.3f} per image")

    print(f"- Total per day (2 images): ${total_day:.3f}")
    print(f"- Total per month (30 days): ${total_day * 30:.2f}")
    print(f"- Total per month (31 days): ${total_day * 31:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate two LinkedIn images from the latest LinkedIn post text for side-by-side comparison: "
            "chatgpt-image-latest (medium) and gpt-image-1-mini (high), both 1024x1024."
        )
    )
    parser.add_argument("--post-file", type=Path, default=None, help="Optional explicit linkedin_post_YYYY-MM-DD.txt")
    parser.add_argument("--size", default="1024x1024", help="Image size (default: 1024x1024)")
    parser.add_argument("--out-dir", type=Path, default=Path("output/linkedin_images_compare"))
    args = parser.parse_args()

    load_env_file(".env")
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is required")

    post_dir = Path("output/linkedin")
    post_path = args.post_file or _latest_linkedin_post(post_dir)
    if not post_path:
        raise SystemExit("No LinkedIn post file found in output/linkedin")
    if not post_path.exists():
        raise SystemExit(f"Post file not found: {post_path}")

    run_date = _date_from_filename(post_path) or date.today().isoformat()
    prompt = _build_prompt(_read_text(post_path))

    jobs = [
        ("chatgpt-image-latest", "medium"),
        ("gpt-image-1-mini", "high"),
    ]

    args.out_dir.mkdir(parents=True, exist_ok=True)

    outputs: list[tuple[str, str, Path]] = []
    failures: list[str] = []
    for model, quality in jobs:
        print(f"Generating {model} ({quality}) at {args.size}...")
        try:
            img_bytes = _generate_image(
                api_key=api_key,
                model=model,
                quality=quality,
                size=args.size,
                prompt=prompt,
            )
            used_model = model
        except RuntimeError as exc:
            fallback_model = ""
            if model == "chatgpt-image-latest":
                fallback_model = os.environ.get("CHATGPT_IMAGE_LATEST_FALLBACK", "gpt-image-1").strip()
            if fallback_model:
                print(f"{exc}")
                print(f"Retrying with fallback model {fallback_model} ({quality})...")
                try:
                    img_bytes = _generate_image(
                        api_key=api_key,
                        model=fallback_model,
                        quality=quality,
                        size=args.size,
                        prompt=prompt,
                    )
                    used_model = fallback_model
                except RuntimeError as fallback_exc:
                    failures.append(str(fallback_exc))
                    continue
            else:
                failures.append(str(exc))
                continue

        name = f"linkedin_image_{run_date}_{_safe_name(used_model)}_{quality}_{args.size}.png"
        out_path = args.out_dir / name
        out_path.write_bytes(img_bytes)
        outputs.append((used_model, quality, out_path))
        print(f"Wrote {out_path}")

    if len(outputs) >= 2:
        side_by_side_path = args.out_dir / f"linkedin_image_{run_date}_side_by_side_{args.size}.png"
        _build_side_by_side(
            left_path=outputs[0][2],
            right_path=outputs[1][2],
            left_label=f"{outputs[0][0]} ({outputs[0][1]})",
            right_label=f"{outputs[1][0]} ({outputs[1][1]})",
            out_path=side_by_side_path,
        )
        print(f"Wrote {side_by_side_path}")
    elif outputs:
        print("Only one image generated; side-by-side file was not created.")
    else:
        raise SystemExit("No images generated. Check API access and model permissions.")

    _print_costs((model, quality, args.size) for model, quality, _ in outputs)
    if failures:
        print("\nGeneration warnings:")
        for item in failures:
            print(f"- {item}")


if __name__ == "__main__":
    main()
