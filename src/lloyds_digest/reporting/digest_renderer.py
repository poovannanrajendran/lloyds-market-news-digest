from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import html
import os
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

from lloyds_digest.storage.postgres_repo import PostgresRepo


@dataclass(frozen=True)
class DigestItem:
    title: str
    url: str
    summary: list[str] | None
    score: float | None
    source_type: str
    topic: str
    why_it_matters: str | None = None


@dataclass(frozen=True)
class DigestConfig:
    min_relevance: float = 0.4
    max_items: int = 40


def render_digest(
    items: Iterable[DigestItem],
    run_date: date,
    output_dir: Path,
    config: DigestConfig | None = None,
    postgres: PostgresRepo | None = None,
    method_health: list[tuple[str, str, float, int, bool]] | None = None,
) -> Path:
    config = config or DigestConfig()
    output_dir.mkdir(parents=True, exist_ok=True)
    selected = _select_items(list(items), config)
    html_out = _render_html(selected, run_date, method_health)
    output_path = output_dir / f"digest_{run_date.isoformat()}.html"
    _rotate_existing(output_path)
    output_path.write_text(html_out, encoding="utf-8")

    if postgres is not None:
        postgres.insert_digest(
            run_date=run_date,
            output_path=str(output_path),
            item_count=len(selected),
            status="rendered",
            metadata={"generated_at": datetime.now().isoformat()},
        )

    return output_path


def _rotate_existing(path: Path) -> None:
    if not path.exists():
        return
    try:
        ts = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d_%H%M%S")
    except Exception:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rotated = path.with_name(f"{ts}_{path.name}")
    path.rename(rotated)


def _select_items(items: list[DigestItem], config: DigestConfig) -> list[DigestItem]:
    filtered = [
        item
        for item in items
        if item.score is None or item.score >= config.min_relevance
    ]
    filtered.sort(key=lambda item: (item.score or 0.0), reverse=True)
    return filtered[: config.max_items]


def _render_html(
    items: list[DigestItem],
    run_date: date,
    method_health: list[tuple[str, str, float, int, bool]] | None,
) -> str:
    template_path = Path(os.environ.get("LLOYDS_DIGEST_TEMPLATE_PATH", "templates/exec_digest_template.html"))
    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")
        return _render_with_template(template, items, run_date, method_health)
    return _render_legacy(items, run_date, method_health)


def _render_with_template(
    template: str,
    items: list[DigestItem],
    run_date: date,
    method_health: list[tuple[str, str, float, int, bool]] | None,
) -> str:
    run_date_str = run_date.isoformat()
    # These relative paths match the GitHub Pages layout (`docs/digests/*.html`).
    # Keep defaults aligned with existing published digests and publish scripts.
    logo_src = os.environ.get("LLOYDS_DIGEST_TEMPLATE_LOGO_SRC", "London_Lloyds_Market_News_Digest.png")
    home_href = os.environ.get("LLOYDS_DIGEST_TEMPLATE_HOME_HREF", "../index.html")
    latest_href = os.environ.get("LLOYDS_DIGEST_TEMPLATE_LATEST_HREF", f"digest_{run_date_str}.html")

    selected_count = len(items)
    domains = sorted({_domain(item.url) for item in items if _domain(item.url)})
    executive_summary = (
        f"{selected_count} highlights selected for {run_date_str}. "
        + (f"Sources include: {', '.join(domains[:5])}." if domains else "")
    ).strip()

    themes = _top_themes(items, limit=6)
    theme_html = "\n".join(f"<li>{_escape(theme)}</li>" for theme in themes) or "<li>No themes identified.</li>"

    stories = []
    health_html = _render_method_health(method_health)
    if health_html:
        # Keep existing method health block, but place it inside the highlights grid so it shows up
        # in the template layout.
        stories.append(f"<article class=\"story\">{health_html}</article>")
    for item in items:
        stories.append(_render_story(item))
    story_html = "\n".join(stories) or "<p>No stories selected.</p>"

    footer = (
        f"Generated {datetime.utcnow().replace(microsecond=0).isoformat()}Z. "
        "Daily digest of public sources; links included for attribution."
    )

    html_out = template
    html_out = html_out.replace("{{ title }}", _escape(f"Lloyd's Market Digest · {run_date_str}"))
    html_out = html_out.replace("{{ heading }}", "Lloyd's Market Executive Digest")
    html_out = html_out.replace("{{ run_date }}", _escape(run_date_str))
    html_out = html_out.replace("{{ executive_summary }}", _escape(executive_summary))
    html_out = html_out.replace("{{ themes }}", theme_html)
    html_out = html_out.replace("{{ stories }}", story_html)
    html_out = html_out.replace("{{ footer }}", _escape(footer))
    html_out = html_out.replace("{{ logo_src }}", _escape(logo_src))
    html_out = html_out.replace("{{ home_href }}", _escape(home_href))
    html_out = html_out.replace("{{ latest_href }}", _escape(latest_href))
    return html_out


def _render_legacy(
    items: list[DigestItem],
    run_date: date,
    method_health: list[tuple[str, str, float, int, bool]] | None,
) -> str:
    grouped: dict[str, dict[str, list[DigestItem]]] = {}
    for item in items:
        grouped.setdefault(item.source_type or "unknown", {}).setdefault(
            item.topic or "General", []
        ).append(item)

    sections = []
    for source_type, topics in grouped.items():
        sections.append(f"<h2>{_escape(source_type.title())}</h2>")
        for topic, topic_items in topics.items():
            sections.append(f"<h3>{_escape(topic)}</h3>")
            for entry in topic_items:
                sections.append(_render_card(entry))

    body = "\n".join(sections) if sections else "<p>No items available.</p>"
    health = _render_method_health(method_health)
    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <title>Lloyd's Digest - {run_date.isoformat()}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1a1a1a; }}
    h1 {{ margin-bottom: 0; }}
    h2 {{ margin-top: 32px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
    h3 {{ margin-top: 16px; color: #444; }}
    .card {{ border: 1px solid #e0e0e0; padding: 12px; margin: 12px 0; border-radius: 6px; }}
    .meta {{ font-size: 0.9em; color: #666; }}
    ul {{ padding-left: 20px; }}
  </style>
</head>
<body>
  <h1>Lloyd's Market News Digest</h1>
  <p class=\"meta\">Run date: {run_date.isoformat()}</p>
  {health}
  {body}
</body>
</html>"""


def _escape(value: str) -> str:
    return html.escape(value or "", quote=True)


def _domain(url: str) -> str:
    try:
        return urlsplit(url).netloc.lower()
    except Exception:
        return ""


def _top_themes(items: list[DigestItem], limit: int) -> list[str]:
    counts: dict[str, int] = {}
    for item in items:
        raw = item.topic or ""
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        for part in parts[:3]:
            counts[part] = counts.get(part, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    return [name for name, _ in ordered[:limit]]


def _render_story(item: DigestItem) -> str:
    title = _escape(item.title)
    url = _escape(item.url)
    domain = _escape(_domain(item.url))
    score = f"{item.score:.2f}" if isinstance(item.score, (int, float)) else "n/a"
    meta = f"Source: {domain} · Score: {score}"
    why = _escape(item.why_it_matters or "")
    bullets = item.summary or []
    bullet_html = "\n".join(
        f"<li>{_escape(str(b))}</li>" for b in bullets[:4] if str(b).strip()
    )
    why_html = f"<div class=\"why\"><strong>Why it matters:</strong> {why}</div>" if why else ""
    bullets_html = f"<ul>{bullet_html}</ul>" if bullet_html else ""
    return (
        "<article class=\"story\">"
        f"<h3><a href=\"{url}\">{title}</a></h3>"
        f"<div class=\"meta\">{meta}</div>"
        f"{why_html}"
        f"{bullets_html}"
        "</article>"
    )


def _render_card(item: DigestItem) -> str:
    score = f"Score: {item.score:.2f}" if item.score is not None else "Score: n/a"
    why = f"<p><strong>Why it matters:</strong> {item.why_it_matters}</p>" if item.why_it_matters else ""
    bullets = ""
    if item.summary:
        bullets = "<ul>" + "".join(f"<li>{bullet}</li>" for bullet in item.summary) + "</ul>"
    return (
        "<div class=\"card\">"
        f"<a href=\"{item.url}\"><strong>{item.title}</strong></a>"
        f"<p class=\"meta\">{score}</p>"
        f"{why}"
        f"{bullets}"
        "</div>"
    )


def _render_method_health(
    items: list[tuple[str, str, float, int, bool]] | None,
) -> str:
    if not items:
        return ""
    rows = []
    for domain, method, rate, attempts, drift in items:
        flag = "⚠️" if drift else ""
        rows.append(
            f"<tr><td>{domain}</td><td>{method}</td><td>{rate:.2f}</td>"
            f"<td>{attempts}</td><td>{flag}</td></tr>"
        )
    return (
        "<h2>Method Health</h2>"
        "<table class=\"card\">"
        "<tr><th>Domain</th><th>Method</th><th>Success Rate</th><th>Attempts</th><th>Drift</th></tr>"
        + "".join(rows)
        + "</table>"
    )
