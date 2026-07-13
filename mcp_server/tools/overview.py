"""One-shot observability overview MCP tool (read-only, platform-aware)."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from observability_aiops.governance import governed_tool
from observability_aiops.ops import overview as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def observability_overview(target: Optional[str] = None) -> dict:
    """[READ] Platform-aware health snapshot for the target.

    Prometheus: firing-alert count + scrape up/down + rules erroring. Grafana:
    dashboard / datasource / folder counts.

    Args:
        target: Target name from config; omit for the default.
    """
    return ops.observability_overview(_get_connection(target))
