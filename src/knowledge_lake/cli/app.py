"""Knowledge Lake CLI — Typer application entry point.

Entry point: klake = "knowledge_lake.cli.app:app"

This module is the thin start of the full klake command list.
Additional commands (ingest-url, search, lineage, demo) are added in later plans.
"""

from __future__ import annotations

import typer

import knowledge_lake

app = typer.Typer(
    name="klake",
    help="Knowledge Lake CLI — manage domain resources and AI-ready pipelines.",
    add_completion=False,
)


@app.command(name="version")
def cmd_version(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show verbose version info."
    ),
) -> None:
    """Print the package version and exit."""
    v = knowledge_lake.__version__
    if verbose:
        typer.echo(f"knowledge-lake {v}")
    else:
        typer.echo(v)


@app.command(name="status", hidden=True)
def cmd_status() -> None:
    """(Internal) reserved — will be wired in later plans."""
    typer.echo("ok")


if __name__ == "__main__":
    app()
