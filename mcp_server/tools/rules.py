"""Prometheus rules MCP tools (read-only)."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from observability_aiops.governance import governed_tool
from observability_aiops.ops import rules as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_rules(rule_type: Optional[str] = None, target: Optional[str] = None) -> dict:
    """[READ] All recording + alerting rules, optionally filtered by type.

    Args:
        rule_type: Filter by "alerting" or "recording"; omit for both.
        target: Prometheus target name from config; omit for the default.
    """
    return ops.list_rules(_get_connection(target), rule_type)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def rule_health(target: Optional[str] = None) -> dict:
    """[READ] Rule-evaluation health summary + the list of erroring rules.

    Args:
        target: Prometheus target name from config; omit for the default.
    """
    return ops.rule_health(_get_connection(target))
