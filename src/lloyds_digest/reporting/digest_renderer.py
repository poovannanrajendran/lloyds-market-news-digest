from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

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
    html = _render_html(selected, run_date, method_health)
    output_path = output_dir / f"digest_{run_date.isoformat()}.html"
    _rotate_existing(output_path)
    output_path.write_text(html, encoding="utf-8")

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
    grouped: dict[str, dict[str, list[DigestItem]]] = {}
    for item in items:
        grouped.setdefault(item.source_type or "unknown", {}).setdefault(
            item.topic or "General", []
        ).append(item)

    sections = []
    for source_type, topics in grouped.items():
        sections.append(f"<h2>{source_type.title()}</h2>")
        for topic, topic_items in topics.items():
            sections.append(f"<h3>{topic}</h3>")
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
