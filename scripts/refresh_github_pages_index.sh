#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE_DIR="$ROOT_DIR/docs"
DIGESTS_DIR="$SITE_DIR/digests"

if [[ ! -d "$DIGESTS_DIR" ]]; then
  echo "Missing docs/digests/; nothing to refresh."
  exit 1
fi

python scripts/update_github_pages_index.py \
  --site-dir "$SITE_DIR" \
  --archive-limit 30 \
  --allow-index-fallback

git add docs/index.html
git commit -m "refresh index: $(date +%Y-%m-%d)" || true
git push
