#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def _digest_files(digests_dir: Path) -> list[Path]:
    return sorted(digests_dir.glob("digest_*.html"), reverse=True)


def _refresh_digest_nav_links(files: list[Path], latest: str) -> None:
    for digest_path in files:
        html = digest_path.read_text(encoding="utf-8")
        original = html
        html = re.sub(
            r'(<a class="nav-btn nav-home" href=")[^"]*(">)',
            r"\1../index.html\2",
            html,
        )
        html = re.sub(
            r'(<a class="nav-btn nav-latest" href=")[^"]*(">)',
            rf"\1{latest}\2",
            html,
        )
        if html != original:
            digest_path.write_text(html, encoding="utf-8")


def _archive_html(files: list[Path]) -> str:
    if not files:
        return ""
    first = f'<li><a href="digests/{files[0].name}">{files[0].name}</a></li>'
    if len(files) == 1:
        return first
    rest = "\n".join(
        f'          <li><a href="digests/{f.name}">{f.name}</a></li>' for f in files[1:]
    )
    return f"{first}\n{rest}"


def update_index(site_dir: Path, archive_limit: int, allow_index_fallback: bool) -> Path:
    digests_dir = site_dir / "digests"
    index_path = site_dir / "index.html"
    template_path = site_dir / "index.template.html"

    files = _digest_files(digests_dir)
    if not files:
        raise SystemExit("No digests found in docs/digests/")

    latest = files[0].name
    archive = files[:archive_limit]
    _refresh_digest_nav_links(files, latest)

    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")
    elif allow_index_fallback and index_path.exists():
        template = index_path.read_text(encoding="utf-8")
    else:
        raise SystemExit(f"Missing template at {template_path}")

    template = template.replace("REPLACE_LATEST", latest)
    template = template.replace("REPLACE_ARCHIVE", _archive_html(archive))
    index_path.write_text(template, encoding="utf-8")
    return index_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh docs/index.html and digest nav links.")
    parser.add_argument("--site-dir", default="docs")
    parser.add_argument("--archive-limit", type=int, default=30)
    parser.add_argument("--allow-index-fallback", action="store_true")
    args = parser.parse_args()

    index_path = update_index(
        site_dir=Path(args.site_dir),
        archive_limit=args.archive_limit,
        allow_index_fallback=args.allow_index_fallback,
    )
    print(f"Updated {index_path}")


if __name__ == "__main__":
    main()
