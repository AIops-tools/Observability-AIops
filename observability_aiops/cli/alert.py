"""``observability-aiops alert`` — firing alerts, silences, and RCA."""

from __future__ import annotations

import json

import typer

from observability_aiops.cli._common import TargetOption, cli_errors, console, get_connection

alert_app = typer.Typer(
    name="alert",
    help="Alerts: firing list, Alertmanager silences, and firing-alert RCA.",
    no_args_is_help=True,
)


@alert_app.command("firing")
@cli_errors
def alert_firing(target: TargetOption = None) -> None:
    """List currently firing Prometheus rule alerts, grouped by severity."""
    from observability_aiops.ops import alerts as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.firing_alerts(conn)))


@alert_app.command("silences")
@cli_errors
def alert_silences(target: TargetOption = None) -> None:
    """List Alertmanager silences (active, pending, expired)."""
    from observability_aiops.ops import alerts as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.list_silences(conn)))


@alert_app.command("rca")
@cli_errors
def alert_rca(target: TargetOption = None) -> None:
    """Root-cause firing alerts: join each to its rule expr → cause + action."""
    from observability_aiops.ops import alerts as alerts_ops
    from observability_aiops.ops import analysis as ops
    from observability_aiops.ops import rules as rules_ops

    conn, _ = get_connection(target)
    firing = alerts_ops.pull_alerts(conn, state="firing")
    rules = rules_ops.list_rules(conn, "alerting").get("rules", [])
    console.print_json(json.dumps(ops.firing_alert_rca(firing, rules)))
