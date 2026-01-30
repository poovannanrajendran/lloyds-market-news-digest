#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="$ROOT_DIR/output"
SITE_DIR="$ROOT_DIR/docs"
DIGESTS_DIR="$SITE_DIR/digests"

mkdir -p "$DIGESTS_DIR"

LATEST_FILE="$(ls -1t "$OUTPUT_DIR"/digest_*_public.html 2>/dev/null | head -n 1 || true)"
if [[ -z "$LATEST_FILE" ]]; then
  echo "No public digest found in output/ (digest_YYYY-MM-DD_public.html)."
  exit 1
fi

LATEST_BASENAME="$(basename "$LATEST_FILE")"
cp "$LATEST_FILE" "$DIGESTS_DIR/$LATEST_BASENAME"

python - <<'PY'
from pathlib import Path
from datetime import datetime

site_dir = Path("site")
digests_dir = site_dir / "digests"
index_path = site_dir / "index.html"

files = sorted(digests_dir.glob("digest_*_public.html"), reverse=True)
if not files:
    raise SystemExit("No digests found in docs/digests/")

latest = files[0].name
archive = files[:30]

archive_html = "\n".join(
    f'<li><a href="digests/{f.name}">{f.name}</a></li>' for f in archive
)

template = index_path.read_text(encoding="utf-8")
template = template.replace("REPLACE_LATEST", latest)
template = template.replace("REPLACE_ARCHIVE", archive_html)
index_path.write_text(template, encoding="utf-8")
print(f"Updated {index_path}")
PY

git add site
git commit -m "publish: $(date +%Y-%m-%d)" || true
git push
