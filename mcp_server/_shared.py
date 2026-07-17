"""Shared MCP server primitives: the FastMCP instance, connection helper,
error sanitisation, and the ``@tool_errors`` decorator.

Tool modules under ``mcp_server/tools/`` import ``mcp`` from here and register
their ``@mcp.tool()`` functions onto it. ``mcp_server/server.py`` then imports
those modules and runs the server.

Keep ``Optional[X]`` (never PEP 604 ``X | None``) in any FastMCP-reflected
tool signature — on older mcp/pydantic the union eval'd to ``types.UnionType``
crashes FastMCP's ``issubclass`` check.
"""

import functools
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from observability_aiops.config import load_config
from observability_aiops.connection import ConnectionManager, ObservabilityApiError
from observability_aiops.governance import sanitize

logger = logging.getLogger(__name__)

_DOCTOR_HINT = "Run 'observability-aiops doctor' to verify connectivity and credentials."


def _safe_error(exc: Exception, tool: str) -> str:
    """Return an agent-safe error string; log full detail server-side only."""
    logger.error("Tool %s failed", tool, exc_info=True)
    _passthrough = (
        ValueError,
        FileNotFoundError,
        KeyError,
        PermissionError,
        TimeoutError,
        ConnectionError,
        ObservabilityApiError,
    )
    if isinstance(exc, _passthrough):
        return sanitize(str(exc), 300)
    return f"{type(exc).__name__}: operation failed."


def tool_errors(shape: str = "dict") -> Callable:
    """Wrap a tool body in the canonical try/except → ``_safe_error`` pattern.

    Place this *between* ``@governed_tool`` and the function so the audit
    decorator and FastMCP still see the original signature.
    """

    def decorator(func: Callable) -> Callable:
        name = func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:  # noqa: BLE001 — sanitised below
                msg = _safe_error(e, name)
                if shape == "list":
                    return [{"error": msg, "hint": _DOCTOR_HINT}]
                if shape == "str":
                    return f"Error: {msg} {_DOCTOR_HINT}"
                return {"error": msg, "hint": _DOCTOR_HINT}

        return wrapper

    return decorator


mcp = FastMCP(
    "observability-aiops",
    instructions=(
        "Self-hosted observability operations (preview) over Prometheus, "
        "Alertmanager, Grafana, and Grafana Loki: PromQL instant/range queries, "
        "label + series metadata; scrape-target health and dropped targets; "
        "recording/alerting rules and their health; firing/pending alerts, "
        "Alertmanager alerts + silences; Grafana dashboards, datasources, folders, "
        "and health; bounded Loki LogQL reads (labels, label values, query, "
        "error-tail) with two flagship log analyses (log-error-burst RCA, "
        "log-volume/cardinality) and an alert->log cross-signal; three metric "
        "flagship analyses (firing-alert RCA, target-scrape-health, "
        "alert-noise/flap); and governed writes — create/expire silence, create "
        "annotation, update/delete dashboard, reload Prometheus config. Loki is "
        "read-only (no safe write surface). Destructive writes (delete dashboard) "
        "are risk=high with a dry_run preview and require an approver. Reversible "
        "writes capture the real before-state and record an undo. Every tool runs "
        "through the observability-aiops governance harness (audit / budget / "
        "risk-tier / undo)."
    ),
)

_conn_mgr: Optional[ConnectionManager] = None


def _get_connection(target: Optional[str] = None) -> Any:
    """Return a Monitoring connection, lazily initialising the manager."""
    global _conn_mgr  # noqa: PLW0603
    if _conn_mgr is None:
        config_path_str = os.environ.get("OBSERVABILITY_AIOPS_CONFIG")
        config_path = Path(config_path_str) if config_path_str else None
        _conn_mgr = ConnectionManager(load_config(config_path))
    return _conn_mgr.connect(target)
