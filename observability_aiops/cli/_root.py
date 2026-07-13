"""Top-level Typer app: assembles sub-apps and top-level commands."""

from __future__ import annotations

import typer

from observability_aiops.cli._common import cli_errors
from observability_aiops.cli.alert import alert_app
from observability_aiops.cli.doctor import doctor_cmd
from observability_aiops.cli.init import init_cmd
from observability_aiops.cli.overview import overview_cmd
from observability_aiops.cli.query import query_app
from observability_aiops.cli.secret import secret_app

app = typer.Typer(
    name="observability-aiops",
    help="Governed AI-ops for self-hosted Prometheus + Grafana: PromQL, "
    "scrape-target & rule health, alerts/silences, dashboards, and RCA.",
    no_args_is_help=True,
)

app.add_typer(query_app, name="query")
app.add_typer(alert_app, name="alert")
app.add_typer(secret_app, name="secret")
app.command("init")(init_cmd)
app.command("overview")(overview_cmd)
app.command("doctor")(doctor_cmd)


@app.command("mcp")
@cli_errors
def mcp_cmd() -> None:
    """Start the MCP server (stdio transport).

    Single-command entry point for MCP clients (does not go through uvx/PyPI
    resolution at launch):
        observability-aiops mcp
    """
    import sys

    if sys.version_info < (3, 11):
        typer.echo(
            f"ERROR: observability-aiops requires Python >= 3.11 "
            f"(got {sys.version_info.major}.{sys.version_info.minor}).\n"
            f"Fix: uv python install 3.12 && "
            f"uv tool install --python 3.12 --force observability-aiops",
            err=True,
        )
        raise typer.Exit(2)

    from mcp_server.server import main as _mcp_main

    _mcp_main()


if __name__ == "__main__":
    app()
