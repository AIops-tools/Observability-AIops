"""Alert MCP tools: Prometheus rule alerts + Alertmanager alerts/silences (read-only)."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from observability_aiops.governance import governed_tool
from observability_aiops.ops import alerts as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def firing_alerts(target: Optional[str] = None) -> dict:
    """[READ] Currently firing Prometheus rule alerts, grouped by severity.

    Args:
        target: Prometheus target name from config; omit for the default.
    """
    return ops.firing_alerts(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def pending_alerts(target: Optional[str] = None) -> dict:
    """[READ] Pending (not-yet-firing) Prometheus rule alerts, by severity.

    Args:
        target: Prometheus target name from config; omit for the default.
    """
    return ops.pending_alerts(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def alertmanager_alerts(active_only: bool = True, target: Optional[str] = None) -> dict:
    """[READ] Alerts as Alertmanager sees them (post grouping/silence/inhibit).

    Args:
        active_only: If True, exclude silenced/inhibited alerts.
        target: Prometheus target name from config (its Alertmanager); omit for default.
    """
    return ops.alertmanager_alerts(_get_connection(target), active_only)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_silences(target: Optional[str] = None) -> dict:
    """[READ] Alertmanager silences (active, pending, expired).

    Args:
        target: Prometheus target name from config (its Alertmanager); omit for default.
    """
    return ops.list_silences(_get_connection(target))
