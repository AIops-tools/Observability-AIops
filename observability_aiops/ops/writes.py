"""Governed writes — Alertmanager silences, Grafana annotations/dashboards, reload.

Every reversible write captures its BEFORE state with a real fetch so the harness
can record a faithful undo:

  * ``create_silence`` returns the new silence id (undo = expire it).
  * ``update_dashboard`` / ``delete_dashboard`` GET the dashboard first and stash
    the prior model in ``priorState`` (undo = restore/recreate it). A 404 on the
    update prior-fetch is tolerated (create mode) so a recorded delete undo replays.
  * ``reload_prometheus_config`` records the pre-reload config hash (no undo).

The footgun write — ``delete_dashboard`` — is risk=high at the MCP layer with a
``dry_run`` preview. Timestamps are UTC ISO-8601.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from observability_aiops.connection import ObservabilityApiError
from observability_aiops.ops import grafana, prom_status
from observability_aiops.ops._util import _seg, s

_NOT_FOUND_STATUS = 404


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    """UTC ISO-8601 with a trailing Z (the format Alertmanager expects)."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _build_matchers(matchers: list[dict]) -> list[dict]:
    """Validate + normalise Alertmanager silence matchers."""
    if not matchers:
        raise ValueError(
            "create_silence requires at least one matcher, e.g. "
            '[{"name": "alertname", "value": "TargetDown"}].'
        )
    built = []
    for m in matchers:
        name = str(m.get("name") or "").strip()
        value = str(m.get("value") or "")
        if not name:
            raise ValueError("Each silence matcher needs a non-empty 'name'.")
        built.append({
            "name": name,
            "value": value,
            "isRegex": bool(m.get("isRegex", False)),
            "isEqual": bool(m.get("isEqual", True)),
        })
    return built


def create_silence(
    conn: Any,
    matchers: list[dict],
    minutes: int = 60,
    comment: str = "silenced via observability-aiops",
    created_by: str = "observability-aiops",
) -> dict:
    """[WRITE][med] Create a time-boxed Alertmanager silence. Inverse: expire_silence.

    ``minutes`` must be > 0 (silences are never open-ended). Returns the new
    ``silenceId`` so the harness can record an expire-silence undo.
    """
    if minutes <= 0:
        raise ValueError("create_silence requires minutes > 0 (silences are time-boxed).")
    built = _build_matchers(matchers)
    starts = _now()
    ends = starts + timedelta(minutes=minutes)
    body = {
        "matchers": built,
        "startsAt": _iso(starts),
        "endsAt": _iso(ends),
        "createdBy": created_by,
        "comment": comment,
    }
    resp = conn.am_post("/api/v2/silences", json=body)
    silence_id = ""
    if isinstance(resp, dict):
        silence_id = str(resp.get("silenceID") or resp.get("silenceId") or resp.get("id") or "")
    return {
        "action": "create_silence",
        "silenceId": s(silence_id, 64),
        "minutes": minutes,
        "matchers": built,
        "endsAt": body["endsAt"],
    }


def expire_silence(conn: Any, silence_id: str) -> dict:
    """[WRITE][med] Expire (delete) an Alertmanager silence by id."""
    conn.am_delete(f"/api/v2/silence/{_seg(s(silence_id, 64))}")
    return {"action": "expire_silence", "silenceId": s(silence_id, 64)}


def create_annotation(
    conn: Any, text: str, tags: list[str] | None = None, dashboard_uid: str = ""
) -> dict:
    """[WRITE][low] Create a Grafana annotation (an event marker)."""
    body: dict[str, Any] = {"text": text, "tags": list(tags or [])}
    if dashboard_uid:
        body["dashboardUID"] = dashboard_uid
    resp = conn.graf_post("/api/annotations", json=body)
    ann_id = resp.get("id") if isinstance(resp, dict) else None
    return {
        "action": "create_annotation",
        "annotationId": ann_id if isinstance(ann_id, int) else s(ann_id, 64),
        "text": s(text, 300),
    }


def _fetch_prior_dashboard(conn: Any, uid: str) -> dict | None:
    """Fetch the current dashboard model for undo capture; ``None`` if it doesn't exist.

    A missing uid (404) is a legitimate update_dashboard input: it happens when
    replaying a delete_dashboard undo, where the recorded descriptor re-creates
    the just-deleted dashboard via update_dashboard. In that case there is no
    prior state to capture and the write proceeds in create mode. Any other API
    error (auth, server, transport) still raises.
    """
    try:
        return grafana.fetch_dashboard_model(conn, uid)
    except ObservabilityApiError as exc:
        if exc.status_code == _NOT_FOUND_STATUS:
            return None
        raise


def update_dashboard(conn: Any, dashboard: dict, overwrite: bool = True) -> dict:
    """[WRITE][med] Update (or re-create) a Grafana dashboard. Captures prior model for undo.

    ``dashboard`` is a full dashboard model and MUST carry its ``uid``. The
    current model is fetched first and stashed in ``priorState`` so the harness
    records a restore undo. If the uid does not exist (404) the write proceeds
    as a create with ``priorState.dashboard = None`` — this is how a recorded
    delete_dashboard undo replays.
    """
    uid = str((dashboard or {}).get("uid") or "").strip()
    if not uid:
        raise ValueError(
            "update_dashboard requires the dashboard model to include its 'uid' "
            "(fetch it with get_dashboard first)."
        )
    prior = _fetch_prior_dashboard(conn, uid)
    prior_dash = prior.get("dashboard") if isinstance(prior, dict) else None
    conn.graf_post("/api/dashboards/db", json={"dashboard": dashboard, "overwrite": overwrite})
    return {
        "action": "update_dashboard",
        "uid": s(uid, 64),
        "priorState": {"dashboard": prior_dash},
    }


def delete_dashboard(conn: Any, uid: str) -> dict:
    """[WRITE][high] Delete a Grafana dashboard. Captures the prior model BEFORE delete.

    The full model is fetched first so ``priorState`` carries everything needed to
    recreate it (undo).
    """
    if not uid:
        raise ValueError("delete_dashboard requires a dashboard uid.")
    prior = grafana.fetch_dashboard_model(conn, uid)
    prior_dash = prior.get("dashboard") if isinstance(prior, dict) else None
    title = ""
    if isinstance(prior_dash, dict):
        title = str(prior_dash.get("title") or "")
    conn.graf_delete(f"/api/dashboards/uid/{_seg(s(uid, 64))}")
    return {
        "action": "delete_dashboard",
        "uid": s(uid, 64),
        "title": s(title),
        "priorState": {"dashboard": prior_dash},
    }


def reload_prometheus_config(conn: Any) -> dict:
    """[WRITE][med] Hot-reload the Prometheus config (POST /-/reload). No undo.

    Records the pre-reload config hash for the audit trail (a reload is not
    reversible — you re-apply the prior config file to roll back).
    """
    prior_hash = prom_status.config_hash(conn)
    conn.prom_reload()
    return {
        "action": "reload_prometheus_config",
        "priorConfigHash": prior_hash,
    }
