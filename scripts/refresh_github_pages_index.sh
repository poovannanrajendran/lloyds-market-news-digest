#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE_DIR="$ROOT_DIR/docs"
DIGESTS_DIR="$SITE_DIR/digests"

if [[ ! -d "$DIGESTS_DIR" ]]; then
  echo "Missing docs/digests/; nothing to refresh."
  exit 1
fi

python - <<'PY'
from pathlib import Path
import re

site_dir = Path("docs")
digests_dir = site_dir / "digests"
index_path = site_dir / "index.html"
template_path = site_dir / "index.template.html"

files = sorted(digests_dir.glob("digest_*.html"), reverse=True)
if not files:
    raise SystemExit("No digests found in docs/digests/")

latest = files[0].name
archive = files[:30]

def refresh_digest_nav_links() -> None:
    for digest_path in files:
        html = digest_path.read_text(encoding="utf-8")
        original = html
        html = re.sub(
            r'(<a class="nav-btn nav-home" href=")[^"]*(">)',
            r'\1../index.html\2',
            html,
        )
        html = re.sub(
            r'(<a class="nav-btn nav-latest" href=")[^"]*(">)',
            rf'\1{latest}\2',
            html,
        )
        if html != original:
            digest_path.write_text(html, encoding="utf-8")

refresh_digest_nav_links()

archive_html = "\n".join(
    f'<li><a href="digests/{f.name}">{f.name}</a></li>' for f in archive
)

template = template_path.read_text(encoding="utf-8")
template = template.replace("REPLACE_LATEST", latest)
template = template.replace("REPLACE_ARCHIVE", archive_html)
index_path.write_text(template, encoding="utf-8")
print(f"Updated {index_path}")
PY

git add docs/index.html
git commit -m "refresh index: $(date +%Y-%m-%d)" || true
git push
