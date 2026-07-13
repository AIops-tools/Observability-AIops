"""Flagship analysis MCP tools — pull telemetry, then run the pure heuristics."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from observability_aiops.governance import governed_tool
from observability_aiops.ops import alerts as alerts_ops
from observability_aiops.ops import analysis as ops
from observability_aiops.ops import rules as rules_ops
from observability_aiops.ops import targets as targets_ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def firing_alert_rca(target: Optional[str] = None) -> dict:
    """[READ][analysis] Root-cause firing alerts: join each to its rule expr → cause+action.

    Pulls firing alerts + alerting rules, matches them, and maps each to a likely
    cause and recommended action. Advisory heuristic — verify before acting.

    Args:
        target: Prometheus target name from config; omit for the default.
    """
    conn = _get_connection(target)
    firing = alerts_ops.pull_alerts(conn, state="firing")
    rules = rules_ops.list_rules(conn, "alerting").get("rules", [])
    return ops.firing_alert_rca(firing, rules)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def target_scrape_health_analysis(target: Optional[str] = None) -> dict:
    """[READ][analysis] Rank down/erroring scrape targets and classify each cause.

    Args:
        target: Prometheus target name from config; omit for the default.
    """
    conn = _get_connection(target)
    active = targets_ops.list_targets(conn).get("targets", [])
    return ops.target_scrape_health_analysis(active)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def alert_noise_and_flap_analysis(
    noise_threshold: int = ops.DEFAULT_NOISE_THRESHOLD, target: Optional[str] = None
) -> dict:
    """[READ][analysis] Find noisy/duplicate alerts → dedup/rollup recommendation.

    Args:
        noise_threshold: Instance count at/above which an alertname is "noisy".
        target: Prometheus target name from config; omit for the default.
    """
    conn = _get_connection(target)
    stream = alerts_ops.pull_alerts(conn)
    return ops.alert_noise_and_flap_analysis(stream, noise_threshold)
