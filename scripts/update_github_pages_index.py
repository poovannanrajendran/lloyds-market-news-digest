#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import html
import re
from collections import OrderedDict
from datetime import date
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

    grouped: "OrderedDict[tuple[int, int], list[Path]]" = OrderedDict()
    for f in files:
        match = re.match(r"digest_(\d{4})-(\d{2})-(\d{2})\.html$", f.name)
        if not match:
            continue
        year = int(match.group(1))
        month = int(match.group(2))
        key = (year, month)
        grouped.setdefault(key, []).append(f)

    if not grouped:
        return "\n".join(
            f'        <li><a href="digests/{html.escape(f.name)}">{html.escape(f.name)}</a></li>'
            for f in files
        )

    today_key = (date.today().year, date.today().month)
    open_key = today_key if today_key in grouped else next(iter(grouped.keys()))

    year_groups: "OrderedDict[int, list[tuple[int, list[Path]]]]" = OrderedDict()
    for (year, month), month_files in grouped.items():
        year_groups.setdefault(year, []).append((month, month_files))

    year_chunks: list[str] = []
    for year, months in year_groups.items():
        month_chunks: list[str] = []
        for month, month_files in months:
            key = (year, month)
            month_open = " open" if key == open_key else ""
            current_class = " current" if key == today_key else ""
            month_name = calendar.month_name[month]
            links = "\n".join(
                f'                <li><a href="digests/{html.escape(f.name)}">{html.escape(f.name)}</a></li>'
                for f in month_files
            )
            month_chunks.append(
                f"""          <details class="month-group{current_class}"{month_open}>
            <summary>{month_name} {year} <span>{len(month_files)} editions</span></summary>
            <ul class="archive-list month-list">
{links}
            </ul>
          </details>"""
            )

        year_open = " open" if year == open_key[0] else ""
        year_chunks.append(
            f"""        <details class="year-group"{year_open}>
          <summary>{year}</summary>
{"\n".join(month_chunks)}
        </details>"""
        )

    return "\n".join(year_chunks)


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
