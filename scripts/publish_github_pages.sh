#!/usr/bin/env bash
set -euo pipefail
STARTED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="$ROOT_DIR/output"
SITE_DIR="$ROOT_DIR/docs"
DIGESTS_DIR="$SITE_DIR/digests"

cd "$ROOT_DIR"
export OUTPUT_DIR

mkdir -p "$DIGESTS_DIR"

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

LOGO_SOURCE="$ROOT_DIR/src/images/London_Lloyds_Market_News_Digest.png"
if [[ -f "$LOGO_SOURCE" ]]; then
  cp "$LOGO_SOURCE" "$DIGESTS_DIR/London_Lloyds_Market_News_Digest.png"
fi

python scripts/update_github_pages_index.py \
  --site-dir "$SITE_DIR" \
  --archive-limit 30 \
  --allow-index-fallback

git add docs
git commit -m "publish: $(date +%Y-%m-%d)" || true
git push

ENDED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
python scripts/log_phase_timing.py --phase publish_pages --started-at "$STARTED_AT" --ended-at "$ENDED_AT" || true
