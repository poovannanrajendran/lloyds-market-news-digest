#!/usr/bin/env bash
set -euo pipefail

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

python - <<'PY'
from pathlib import Path
from datetime import datetime

site_dir = Path("docs")
digests_dir = site_dir / "digests"
index_path = site_dir / "index.html"
template_path = site_dir / "index.template.html"

files = sorted(digests_dir.glob("digest_*.html"), reverse=True)
if not files:
    raise SystemExit("No digests found in docs/digests/")

latest = files[0].name
archive = files[:30]

archive_html = "\n".join(
    f'<li><a href="digests/{f.name}">{f.name}</a></li>' for f in archive
)

if template_path.exists():
    template = template_path.read_text(encoding="utf-8")
else:
    template = index_path.read_text(encoding="utf-8")
template = template.replace("REPLACE_LATEST", latest)
template = template.replace("REPLACE_ARCHIVE", archive_html)
index_path.write_text(template, encoding="utf-8")
print(f"Updated {index_path}")
PY

git add docs
git commit -m "publish: $(date +%Y-%m-%d)" || true
git push
