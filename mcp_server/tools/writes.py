"""Governed-write MCP tools: silences, annotations, dashboards, config reload.

Reversible writes pass an ``undo=`` callback so the harness records an inverse
descriptor from the REAL captured before-state:

  * ``create_silence`` → expire the returned silence id.
  * ``update_dashboard`` / ``delete_dashboard`` → restore/recreate the dashboard
    from the model captured before the change.

``delete_dashboard`` is risk=high with a ``dry_run`` preview, carrying that risk
tier into the audit row. Every write supports ``dry_run``.
"""

from typing import Any, Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from observability_aiops.governance import governed_tool
from observability_aiops.ops import grafana as grafana_ops
from observability_aiops.ops import prom_status
from observability_aiops.ops import writes as ops


# ── undo callbacks ───────────────────────────────────────────────────────────
def _silence_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    """Inverse of create_silence: expire the returned silence id."""
    if not isinstance(result, dict) or not result.get("silenceId"):
        return None
    return {
        "tool": "expire_silence",
        "params": {"silence_id": result.get("silenceId")},
        "skill": "observability-aiops",
        "note": "Inverse of create_silence: expire the created silence.",
    }


def _update_dashboard_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    """Inverse of update_dashboard: restore the prior dashboard model."""
    if not isinstance(result, dict):
        return None
    prior = (result.get("priorState") or {}).get("dashboard")
    if not prior:
        return None
    return {
        "tool": "update_dashboard",
        "params": {"dashboard": prior},
        "skill": "observability-aiops",
        "note": "Inverse of update_dashboard: restore the captured prior model.",
    }


def _delete_dashboard_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    """Inverse of delete_dashboard: recreate from the captured prior model."""
    if not isinstance(result, dict):
        return None
    prior = (result.get("priorState") or {}).get("dashboard")
    if not prior:
        return None
    return {
        "tool": "update_dashboard",
        "params": {"dashboard": prior},
        "skill": "observability-aiops",
        "note": "Inverse of delete_dashboard: recreate the dashboard from its prior model.",
    }


# ── Alertmanager silences ────────────────────────────────────────────────────
@mcp.tool()
@governed_tool(risk_level="medium", undo=_silence_undo)
@tool_errors("dict")
def create_silence(
    matchers: list,
    minutes: int = 60,
    comment: str = "silenced via observability-aiops",
    dry_run: bool = False,
    target: Optional[str] = None,
) -> dict:
    """[WRITE][risk=medium] Create a time-boxed Alertmanager silence. Inverse: expire_silence.

    Args:
        matchers: List of {name, value, isRegex?} to match alerts to silence.
        minutes: Silence duration in minutes (must be > 0; silences are time-boxed).
        comment: Reason recorded on the silence.
        dry_run: If True, preview without creating.
        target: Prometheus target (its Alertmanager); omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        return {"dryRun": True, "wouldSilence": {"matchers": matchers, "minutes": minutes}}
    return ops.create_silence(conn, list(matchers), minutes, comment)


@mcp.tool()
@governed_tool(risk_level="medium")
@tool_errors("dict")
def expire_silence(silence_id: str, dry_run: bool = False, target: Optional[str] = None) -> dict:
    """[WRITE][risk=medium] Expire (delete) an Alertmanager silence by id.

    Args:
        silence_id: The silence id (from list_silences / create_silence).
        dry_run: If True, preview without expiring.
        target: Prometheus target (its Alertmanager); omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        return {"dryRun": True, "wouldExpire": {"silenceId": silence_id}}
    return ops.expire_silence(conn, silence_id)


# ── Grafana annotations ──────────────────────────────────────────────────────
@mcp.tool()
@governed_tool(risk_level="medium")
@tool_errors("dict")
def create_annotation(
    text: str,
    tags: Optional[list] = None,
    dashboard_uid: str = "",
    dry_run: bool = False,
    target: Optional[str] = None,
) -> dict:
    """[WRITE][risk=medium] Create a Grafana annotation (an event marker).

    Args:
        text: Annotation text.
        tags: Optional list of tag strings.
        dashboard_uid: Optional dashboard UID to attach the annotation to.
        dry_run: If True, preview without creating.
        target: Grafana target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        return {"dryRun": True, "wouldAnnotate": {"text": text, "tags": tags or []}}
    return ops.create_annotation(conn, text, list(tags or []), dashboard_uid)


# ── Grafana dashboards ───────────────────────────────────────────────────────
@mcp.tool()
@governed_tool(risk_level="medium", undo=_update_dashboard_undo)
@tool_errors("dict")
def update_dashboard(
    dashboard: dict, overwrite: bool = True, dry_run: bool = False, target: Optional[str] = None
) -> dict:
    """[WRITE][risk=medium] Update a Grafana dashboard. Captures the prior model for undo.

    The dashboard model must include its ``uid``. The current model is fetched
    first and stashed so the harness records a restore undo.

    Args:
        dashboard: Full dashboard model (must include "uid").
        overwrite: Overwrite the existing dashboard version (default True).
        dry_run: If True, preview without updating.
        target: Grafana target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        return {"dryRun": True, "wouldUpdate": {"uid": (dashboard or {}).get("uid")}}
    return ops.update_dashboard(conn, dashboard, overwrite)


@mcp.tool()
@governed_tool(risk_level="high", undo=_delete_dashboard_undo)
@tool_errors("dict")
def delete_dashboard(uid: str, dry_run: bool = False, target: Optional[str] = None) -> dict:
    """[WRITE][risk=high] Delete a Grafana dashboard. Captures the prior model BEFORE delete.

    Pass dry_run=True to preview (reports the dashboard title). Optionally set
    an approver (OBSERVABILITY_AUDIT_APPROVED_BY) to annotate the audit row —
    it is not required. The prior model is captured so the recorded undo can
    recreate it.

    Args:
        uid: Dashboard UID to delete (from list_dashboards).
        dry_run: If True, preview without deleting.
        target: Grafana target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        model = grafana_ops.fetch_dashboard_model(conn, uid)
        dash = model.get("dashboard") if isinstance(model, dict) else {}
        title = dash.get("title") if isinstance(dash, dict) else ""
        return {"dryRun": True, "wouldDelete": {"uid": uid, "title": title}}
    return ops.delete_dashboard(conn, uid)


# ── Prometheus config reload ─────────────────────────────────────────────────
@mcp.tool()
@governed_tool(risk_level="medium")
@tool_errors("dict")
def reload_prometheus_config(dry_run: bool = False, target: Optional[str] = None) -> dict:
    """[WRITE][risk=medium] Hot-reload the Prometheus config (POST /-/reload). No undo.

    Records the pre-reload config hash. Rollback = re-apply the prior config file.

    Args:
        dry_run: If True, preview (reports the current config hash) without reloading.
        target: Prometheus target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        return {
            "dryRun": True,
            "wouldReload": True,
            "currentConfigHash": prom_status.config_hash(conn),
        }
    return ops.reload_prometheus_config(conn)
