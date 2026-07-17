"""Grafana Loki MCP tools — read-only LogQL + label metadata, flagship log RCA.

Loki has no safe write surface here, so every tool is a read (risk=low). The two
flagship analyses (``log_error_burst_rca``, ``log_volume_analysis``) pull Loki
telemetry and run the pure heuristics in ``ops.log_analysis``. ``alert_log_context``
is the cross-signal bridge: it reads a firing Prometheus alert's labels and
correlates them to Loki streams.
"""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from observability_aiops.governance import governed_tool
from observability_aiops.ops import alerts as alerts_ops
from observability_aiops.ops import log_analysis as log_ops
from observability_aiops.ops import loki as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def loki_labels(hours: float = ops.DEFAULT_LOOKBACK_HOURS, target: Optional[str] = None) -> dict:
    """[READ] Distinct Loki label names present in the lookback window.

    Args:
        hours: Lookback window in hours (capped at the tool's max lookback).
        target: Loki target name from config; omit for the default.
    """
    return ops.loki_labels(_get_connection(target), hours)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def loki_label_values(
    name: str, hours: float = ops.DEFAULT_LOOKBACK_HOURS, target: Optional[str] = None
) -> dict:
    """[READ] Distinct values of one Loki label (bounded).

    Args:
        name: Label name to enumerate (e.g. 'app', 'namespace').
        hours: Lookback window in hours (capped at the tool's max lookback).
        target: Loki target name from config; omit for the default.
    """
    return ops.loki_label_values(_get_connection(target), name, hours)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def loki_query(
    logql: str,
    hours: float = ops.DEFAULT_LOOKBACK_HOURS,
    limit: int = ops.DEFAULT_LINE_LIMIT,
    target: Optional[str] = None,
) -> dict:
    """[READ] Bounded LogQL query_range passthrough (validation-gated).

    The query MUST carry a stream selector (e.g. '{app="api"}') — an unbounded
    query with no selector is rejected. Lookback is capped and the line count is
    clamped.

    Args:
        logql: A LogQL query with a stream selector (e.g. '{job="api"} |= "error"').
        hours: Lookback window in hours (capped at the tool's max lookback).
        limit: Max log lines to return (clamped to the tool's max line limit).
        target: Loki target name from config; omit for the default.
    """
    return ops.loki_query(_get_connection(target), logql, hours, limit)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def loki_tail_errors(
    selector: str,
    hours: float = ops.DEFAULT_LOOKBACK_HOURS,
    limit: int = ops.DEFAULT_LINE_LIMIT,
    target: Optional[str] = None,
) -> dict:
    """[READ] Canned error-level read for a stream selector (error line-filter).

    Args:
        selector: A Loki stream selector (e.g. '{app="api"}' or 'app="api"').
        hours: Lookback window in hours (capped at the tool's max lookback).
        limit: Max log lines to return (clamped to the tool's max line limit).
        target: Loki target name from config; omit for the default.
    """
    return ops.loki_tail_errors(_get_connection(target), selector, hours, limit)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def log_error_burst_rca(
    selector: str,
    hours: float = ops.DEFAULT_LOOKBACK_HOURS,
    loki_target: Optional[str] = None,
) -> dict:
    """[READ][analysis] Root-cause an error burst: current window vs baseline, per stream.

    Pulls error streams for the current window (now-hours..now) and an equal-length
    baseline window (now-2*hours..now-hours), then classifies each burst as a new
    error signature, a volume spike, or a single-instance burst — with a cause +
    action. Advisory heuristic; verify against the raw logs.

    Args:
        selector: A Loki stream selector to scope the analysis (e.g. '{app="api"}').
        hours: Window length in hours for both current and baseline (capped).
        loki_target: Loki target name from config; omit for the default.
    """
    conn = _get_connection(loki_target)
    now = ops._now_ns()
    span = int(ops._validate_hours(hours) * 3600 * ops._NS_PER_SEC)
    current = ops.error_streams_window(conn, selector, now - span, now)
    baseline = ops.error_streams_window(conn, selector, now - 2 * span, now - span)
    return log_ops.log_error_burst_rca(current, baseline)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def log_volume_analysis(
    selector: str,
    hours: float = ops.DEFAULT_LOOKBACK_HOURS,
    loki_target: Optional[str] = None,
) -> dict:
    """[READ][analysis] Top streams by volume + high-cardinality (high-churn) label warnings.

    Ranks the highest-volume streams under the selector, flags labels with many
    distinct values as cardinality-explosion risks, and adds a retention hint from
    Loki index stats when available.

    Args:
        selector: A Loki stream selector to scope the analysis (e.g. '{namespace="prod"}').
        hours: Lookback window in hours (capped at the tool's max lookback).
        loki_target: Loki target name from config; omit for the default.
    """
    conn = _get_connection(loki_target)
    result = ops.loki_query(conn, ops.wrap_selector(selector), hours)
    if "error" in result:
        return result
    stats = ops.index_stats(conn, selector, hours)
    return log_ops.log_volume_analysis(
        result.get("results", []), None if "error" in stats else stats
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def alert_log_context(
    alertname: str,
    hours: float = ops.DEFAULT_LOOKBACK_HOURS,
    target: Optional[str] = None,
    loki_target: Optional[str] = None,
) -> dict:
    """[READ][cross-signal] Correlate a firing Prometheus alert to its Loki log streams.

    Reads the firing alert's labels from the Prometheus target, maps the
    Loki-friendly ones (namespace, job, service, app, container, pod, instance,
    component — first four, in that priority order) into a LogQL stream selector,
    and pulls the correlated error streams from the Loki target. Best-effort:
    label values are escaped into the selector and only labels the alert and Loki
    actually share will match.

    Args:
        alertname: The firing alert's name (from firing_alerts / firing_alert_rca).
        hours: Lookback window in hours (capped at the tool's max lookback).
        target: Prometheus target name from config; omit for the default.
        loki_target: Loki target name from config; omit for the default.
    """
    prom = _get_connection(target)
    firing = alerts_ops.pull_alerts(prom, state="firing")
    match = next((a for a in firing if a.get("alertname") == alertname), None)
    if match is None:
        return {
            "error": f"No firing alert named '{alertname}' on target '{target or 'default'}'.",
            "alertname": alertname,
        }
    labels = match.get("labels") or {}
    pairs = ops.build_selector_from_labels(labels)
    if not pairs:
        return {
            "alertname": alertname,
            "matchedLabels": {},
            "lokiSelector": None,
            "note": (
                "The firing alert carries no Loki-correlatable labels (namespace/"
                "job/service/app/container/pod/instance/component). Add one of these "
                "labels to the alerting rule to enable log correlation."
            ),
            "streams": 0,
            "results": [],
        }
    selector = ops.selector_from_pairs(pairs)
    context = ops.loki_tail_errors(_get_connection(loki_target), selector, hours)
    return {
        "alertname": alertname,
        "matchedLabels": dict(pairs),
        "lokiSelector": selector,
        "mapping": (
            "Alert labels mapped to a Loki stream selector by intersecting with "
            "namespace/job/service/app/container/pod/instance/component (first 4, "
            "priority order); values escaped for LogQL."
        ),
        **context,
    }
