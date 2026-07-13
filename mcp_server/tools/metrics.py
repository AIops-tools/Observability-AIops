"""Prometheus metrics MCP tools (read-only PromQL + metadata)."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from observability_aiops.governance import governed_tool
from observability_aiops.ops import metrics as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def instant_query(query: str, time: Optional[str] = None, target: Optional[str] = None) -> dict:
    """[READ] Evaluate a PromQL expression at a single instant.

    Args:
        query: A PromQL expression (e.g. 'up' or 'rate(http_requests_total[5m])').
        time: Optional RFC-3339 or unix timestamp for the evaluation instant.
        target: Prometheus target name from config; omit for the default.
    """
    return ops.instant_query(_get_connection(target), query, time)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def range_query(
    query: str, start: str, end: str, step: str = "60s", target: Optional[str] = None
) -> dict:
    """[READ] Evaluate a PromQL expression over a time range.

    Args:
        query: A PromQL expression.
        start: Range start (RFC-3339 or unix timestamp).
        end: Range end (RFC-3339 or unix timestamp).
        step: Resolution step (e.g. '60s', '5m').
        target: Prometheus target name from config; omit for the default.
    """
    return ops.range_query(_get_connection(target), query, start, end, step)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def label_values(
    label: str = "__name__", match: Optional[str] = None, target: Optional[str] = None
) -> dict:
    """[READ] Distinct values of a label (default __name__ = all metric names).

    Args:
        label: Label name to enumerate (default __name__).
        match: Optional PromQL selector to scope the values (e.g. '{job="api"}').
        target: Prometheus target name from config; omit for the default.
    """
    return ops.label_values(_get_connection(target), label, match)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def series_metadata(
    match: str, start: Optional[str] = None, end: Optional[str] = None, target: Optional[str] = None
) -> dict:
    """[READ] Series (label-set) metadata for a PromQL selector.

    Args:
        match: A PromQL series selector (e.g. 'up{job="node"}').
        start: Optional range start (RFC-3339 or unix timestamp).
        end: Optional range end (RFC-3339 or unix timestamp).
        target: Prometheus target name from config; omit for the default.
    """
    return ops.series_metadata(_get_connection(target), match, start, end)
