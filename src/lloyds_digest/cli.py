from __future__ import annotations

from datetime import date
import os
from pathlib import Path
from typing import Optional

import typer

from lloyds_digest.config import load_config
from lloyds_digest.pipeline import run_pipeline
from lloyds_digest.utils import load_env_file

app = typer.Typer(help="Lloyd's Market News Digest CLI")


@app.callback()
def main() -> None:
    """Lloyd's Market News Digest CLI."""
    return None


@app.command()
def run(
    now: bool = typer.Option(False, "--now", help="Run for today's date."),
    run_date: Optional[str] = typer.Option(
        None, "--run-date", help="Run for a specific date (YYYY-MM-DD)."
    ),
    cache: Optional[bool] = typer.Option(
        None,
        "--cache/--no-cache",
        help="Enable or disable caching (placeholder).",
    ),
    output_dir: Optional[Path] = typer.Option(
        None, "--output-dir", help="Override output directory (placeholder)."
    ),
    max_candidates: Optional[int] = typer.Option(
        None,
        "--max-candidates",
        "--limit-articles",
        help="Limit the number of candidates processed.",
    ),
    max_urls: Optional[int] = typer.Option(
        None,
        "--max-urls",
        help="Limit the number of source URLs loaded from sources.csv.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Show detailed per-URL and LLM progress logs.",
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        help="Ignore any cache even if enabled.",
    ),
    config: Path = typer.Option(
        Path("config.yaml"), "--config", help="Path to config.yaml."
    ),
    sources: Path = typer.Option(
        Path("sources.csv"), "--sources", help="Path to sources CSV."
    ),
) -> None:
    """Run the digest pipeline (placeholder)."""
    if now and run_date:
        raise typer.BadParameter("Use either --now or --run-date, not both.")

    if now:
        resolved_date = date.today()
    elif run_date:
        try:
            resolved_date = date.fromisoformat(run_date)
        except ValueError as exc:
            raise typer.BadParameter("--run-date must be YYYY-MM-DD.") from exc
    else:
        resolved_date = None

    resolved_date = resolved_date or date.today()

    load_env_file(Path(".env"))
    os.environ.setdefault("LLOYDS_DIGEST_LLM_MODE", "on")
    config_data = load_config(config)

    typer.echo("Lloyd's Market News Digest")
    typer.echo(f"Run date: {resolved_date.isoformat()}")
    typer.echo(f"Config: {config}")

    log = typer.echo
    log_detail = typer.echo if verbose else (lambda _message: None)

    result = run_pipeline(
        run_date=resolved_date,
        config=config_data,
        sources_path=sources,
        output_dir_override=output_dir,
        cache_override=False if force_refresh else cache,
        max_candidates=max_candidates,
        max_sources=max_urls,
        skip_seen=not force_refresh,
        log=log,
        log_detail=log_detail,
    )

    if result.output_path is not None:
        typer.echo(f"Digest written: {result.output_path}")
    typer.echo(
        "Counts: "
        f"sources={result.total_sources}, "
        f"candidates={result.total_candidates}, "
        f"fetched={result.fetched}, "
        f"extracted={result.extracted}, "
        f"errors={result.errors}"
    )
    if result.warnings:
        for warning in result.warnings:
            typer.secho(f"Warning: {warning}", fg=typer.colors.YELLOW)


if __name__ == "__main__":
    app()
