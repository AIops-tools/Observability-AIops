"""``observability-aiops logs`` — Grafana Loki LogQL reads (bounded)."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from observability_aiops.cli._common import TargetOption, cli_errors, console, get_connection

logs_app = typer.Typer(
    name="logs",
    help="Grafana Loki: labels, bounded LogQL query, and a canned error tail.",
    no_args_is_help=True,
)


@logs_app.command("labels")
@cli_errors
def logs_labels(
    hours: Annotated[float, typer.Option("--hours", help="Lookback window (hours)")] = 1.0,
    target: TargetOption = None,
) -> None:
    """List distinct Loki label names present in the lookback window."""
    from observability_aiops.ops import loki as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.loki_labels(conn, hours)))


@logs_app.command("query")
@cli_errors
def logs_query(
    logql: Annotated[str, typer.Argument(help="LogQL with a stream selector, e.g. {app=\"api\"}")],
    hours: Annotated[float, typer.Option("--hours", help="Lookback window (hours)")] = 1.0,
    limit: Annotated[int, typer.Option("--limit", help="Max log lines")] = 100,
    target: TargetOption = None,
) -> None:
    """Run a bounded LogQL query_range (a stream selector is required)."""
    from observability_aiops.ops import loki as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.loki_query(conn, logql, hours, limit)))


@logs_app.command("errors")
@cli_errors
def logs_errors(
    selector: Annotated[str, typer.Argument(help="Stream selector, e.g. '{app=\"api\"}'")],
    hours: Annotated[float, typer.Option("--hours", help="Lookback window (hours)")] = 1.0,
    limit: Annotated[int, typer.Option("--limit", help="Max log lines")] = 100,
    target: TargetOption = None,
) -> None:
    """Tail error-level lines for a stream selector (canned error filter)."""
    from observability_aiops.ops import loki as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.loki_tail_errors(conn, selector, hours, limit)))
