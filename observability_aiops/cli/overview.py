"""``observability-aiops overview`` — one-shot platform-aware health snapshot."""

from __future__ import annotations

import json

from observability_aiops.cli._common import TargetOption, cli_errors, console, get_connection


@cli_errors
def overview_cmd(target: TargetOption = None) -> None:
    """One-shot snapshot: Prometheus alerts/targets/rules or Grafana counts."""
    from observability_aiops.ops import overview as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.observability_overview(conn)))
