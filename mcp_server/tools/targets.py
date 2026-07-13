"""Prometheus scrape-target MCP tools (read-only)."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from observability_aiops.governance import governed_tool
from observability_aiops.ops import targets as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_targets(health: Optional[str] = None, target: Optional[str] = None) -> dict:
    """[READ] Active scrape targets, optionally filtered by health (up/down).

    Args:
        health: Filter by health state ("up" or "down"); omit for all.
        target: Prometheus target name from config; omit for the default.
    """
    return ops.list_targets(_get_connection(target), health)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def target_scrape_health(target: Optional[str] = None) -> dict:
    """[READ] Up/down scrape-health summary plus the list of unhealthy targets.

    Args:
        target: Prometheus target name from config; omit for the default.
    """
    return ops.target_scrape_health(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def dropped_targets(target: Optional[str] = None) -> dict:
    """[READ] Targets discovered but dropped by relabeling.

    Args:
        target: Prometheus target name from config; omit for the default.
    """
    return ops.dropped_targets(_get_connection(target))
