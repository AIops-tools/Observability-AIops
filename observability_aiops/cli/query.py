"""``observability-aiops query`` — Prometheus PromQL reads."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from observability_aiops.cli._common import (
    TargetOption,
    cli_errors,
    console,
    get_connection,
    warn_if_truncated,
)

query_app = typer.Typer(
    name="query",
    help="Prometheus PromQL: instant + range queries and label values.",
    no_args_is_help=True,
)


@query_app.command("instant")
@cli_errors
def query_instant(
    promql: Annotated[str, typer.Argument(help="A PromQL expression (e.g. 'up')")],
    target: TargetOption = None,
) -> None:
    """Evaluate a PromQL expression at the current instant."""
    from observability_aiops.ops import metrics as ops

    conn, _ = get_connection(target)
    result = ops.instant_query(conn, promql)
    console.print_json(json.dumps(result))
    warn_if_truncated(result, "a narrower PromQL selector")


@query_app.command("range")
@cli_errors
def query_range(
    promql: Annotated[str, typer.Argument(help="A PromQL expression")],
    start: Annotated[str, typer.Option("--start", help="Range start (RFC-3339/unix)")],
    end: Annotated[str, typer.Option("--end", help="Range end (RFC-3339/unix)")],
    step: Annotated[str, typer.Option("--step", help="Resolution step")] = "60s",
    target: TargetOption = None,
) -> None:
    """Evaluate a PromQL expression over a time range."""
    from observability_aiops.ops import metrics as ops

    conn, _ = get_connection(target)
    result = ops.range_query(conn, promql, start, end, step)
    console.print_json(json.dumps(result))
    warn_if_truncated(result, "a narrower PromQL selector")


@query_app.command("labels")
@cli_errors
def query_labels(
    label: Annotated[str, typer.Argument(help="Label name (default __name__)")] = "__name__",
    target: TargetOption = None,
) -> None:
    """List distinct values of a label (default __name__ = all metric names)."""
    from observability_aiops.ops import metrics as ops

    conn, _ = get_connection(target)
    result = ops.label_values(conn, label)
    console.print_json(json.dumps(result))
    warn_if_truncated(result, "a --match selector")
