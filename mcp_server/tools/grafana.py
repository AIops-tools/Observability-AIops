"""Grafana MCP tools (read-only): dashboards, datasources, folders."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from observability_aiops.governance import governed_tool
from observability_aiops.ops import grafana as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_dashboards(query: Optional[str] = None, target: Optional[str] = None) -> dict:
    """[READ] Grafana dashboards (optionally filtered by a title query).

    Args:
        query: Optional title substring to search for.
        target: Grafana target name from config; omit for the default.
    """
    return ops.list_dashboards(_get_connection(target), query)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def get_dashboard(uid: str, target: Optional[str] = None) -> dict:
    """[READ] One dashboard's summary (title, version, panel + tag counts).

    Args:
        uid: Dashboard UID (from list_dashboards).
        target: Grafana target name from config; omit for the default.
    """
    return ops.get_dashboard(_get_connection(target), uid)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_datasources(target: Optional[str] = None) -> dict:
    """[READ] Configured Grafana datasources (id, uid, name, type, default).

    Args:
        target: Grafana target name from config; omit for the default.
    """
    return ops.list_datasources(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def datasource_health(datasource_id: int, target: Optional[str] = None) -> dict:
    """[READ] Health of one Grafana datasource.

    Args:
        datasource_id: Numeric datasource id (from list_datasources).
        target: Grafana target name from config; omit for the default.
    """
    return ops.datasource_health(_get_connection(target), datasource_id)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_folders(target: Optional[str] = None) -> dict:
    """[READ] Grafana folders.

    Args:
        target: Grafana target name from config; omit for the default.
    """
    return ops.list_folders(_get_connection(target))
