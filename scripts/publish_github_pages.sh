#!/usr/bin/env bash
set -euo pipefail
STARTED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="$ROOT_DIR/output"
SITE_DIR="$ROOT_DIR/docs"
DIGESTS_DIR="$SITE_DIR/digests"
ASSETS_DIR="$SITE_DIR/assets"
DRY_RUN="${DRY_RUN:-0}"

cd "$ROOT_DIR"
export OUTPUT_DIR

mkdir -p "$DIGESTS_DIR"
mkdir -p "$ASSETS_DIR"

LATEST_FILE="$(python - <<'PY'
import os
import re
from pathlib import Path

output_dir = Path(os.environ["OUTPUT_DIR"])
pattern = re.compile(r"^digest_\d{4}-\d{2}-\d{2}\.html$")
files = [p for p in output_dir.glob("digest_*.html") if pattern.match(p.name)]
files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
if not files:
    raise SystemExit(1)
print(files[0])
PY
)"
if [[ -z "$LATEST_FILE" ]]; then
  echo "No digest found in output/ (digest_YYYY-MM-DD.html)."
  exit 1
fi

LATEST_BASENAME="$(basename "$LATEST_FILE")"
cp "$LATEST_FILE" "$DIGESTS_DIR/$LATEST_BASENAME"
RUN_DATE=""
if [[ "$LATEST_BASENAME" =~ ^digest_([0-9]{4}-[0-9]{2}-[0-9]{2})\.html$ ]]; then
  RUN_DATE="${BASH_REMATCH[1]}"
fi

LOGO_SOURCE="$ROOT_DIR/src/images/London_Lloyds_Market_News_Digest.png"
if [[ -f "$LOGO_SOURCE" ]]; then
  cp "$LOGO_SOURCE" "$DIGESTS_DIR/London_Lloyds_Market_News_Digest.png"
fi

if [[ -n "$RUN_DATE" ]]; then
  IMAGE_SOURCE="$OUTPUT_DIR/linkedin_images/linkedin_image_${RUN_DATE}.png"
  if [[ -f "$IMAGE_SOURCE" ]]; then
    cp "$IMAGE_SOURCE" "$ASSETS_DIR/linkedin_image_${RUN_DATE}.png"
    echo "Published LinkedIn image: docs/assets/linkedin_image_${RUN_DATE}.png"
  else
    echo "LinkedIn image not found for ${RUN_DATE}: $IMAGE_SOURCE"
  fi
fi

python scripts/update_github_pages_index.py \
  --site-dir "$SITE_DIR" \
  --archive-limit 30 \
  --allow-index-fallback

if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY_RUN=1: skipping git commit/push in publish_github_pages.sh"
else
  git add docs
  git commit -m "publish: $(date +%Y-%m-%d)" || true
  git push
fi

ENDED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
python scripts/log_phase_timing.py --phase publish_pages --started-at "$STARTED_AT" --ended-at "$ENDED_AT" || true
