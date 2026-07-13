"""Prometheus server-status MCP tools (read-only ``/api/v1/status``)."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from observability_aiops.governance import governed_tool
from observability_aiops.ops import prom_status as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def prometheus_config_status(target: Optional[str] = None) -> dict:
    """[READ] Running-config fingerprint + size (never the raw YAML/secrets).

    Args:
        target: Prometheus target name from config; omit for the default.
    """
    return ops.config_status(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def prometheus_tsdb_status(target: Optional[str] = None) -> dict:
    """[READ] TSDB head cardinality stats + the top metrics by series count.

    Args:
        target: Prometheus target name from config; omit for the default.
    """
    return ops.tsdb_status(_get_connection(target))
