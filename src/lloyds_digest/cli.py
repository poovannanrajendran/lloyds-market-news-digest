from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from lloyds_digest.config import load_config

app = typer.Typer(help="Lloyd's Market News Digest CLI")


@app.command()
def run(
    now: bool = typer.Option(False, "--now", help="Run for today's date."),
    run_date: str | None = typer.Option(
        None, "--run-date", help="Run for a specific date (YYYY-MM-DD)."
    ),
    cache: bool | None = typer.Option(
        None,
        "--cache/--no-cache",
        help="Enable or disable caching (placeholder).",
    ),
    output_dir: Path | None = typer.Option(
        None, "--output-dir", help="Override output directory (placeholder)."
    ),
    config: Path = typer.Option(
        Path("config.yaml"), "--config", help="Path to config.yaml."
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

    config_data = load_config(config)

    typer.echo("Lloyd's Market News Digest (phase-01 skeleton)")
    typer.echo(f"Run date: {resolved_date or 'not set'}")
    typer.echo(f"Config: {config}")
    typer.echo(f"Cache flag: {cache}")
    typer.echo(f"Output override: {output_dir}")
    typer.echo(f"Topics CSV: {config_data.topics_csv}")


if __name__ == "__main__":
    app()
