"""Alert surface: Prometheus rule alerts + Alertmanager alerts/silences (read-only).

  * ``firing_alerts`` / ``pending_alerts`` read Prometheus' own rule-alert view
    (``/api/v1/alerts``), which reflects rule evaluation state.
  * ``alertmanager_alerts`` / ``list_silences`` read Alertmanager (``/api/v2``),
    which reflects post-routing state (grouping, silencing, inhibition).

Every call is resilient and every server string passes through ``s``.
"""

from __future__ import annotations

from typing import Any

from observability_aiops.ops._util import as_obj, opt, prom_data, rows, s

_MAX_ROWS = 500

STATE_FIRING = "firing"
STATE_PENDING = "pending"


def _norm_prom_alert(alert: dict) -> dict:
    """Normalise one Prometheus rule alert (``/api/v1/alerts``)."""
    labels = as_obj(alert.get("labels"))
    annotations = as_obj(alert.get("annotations"))
    return {
        "alertname": s(labels.get("alertname")),
        "severity": opt(labels.get("severity"), 32),
        "state": s(alert.get("state"), 16),
        "activeAt": s(alert.get("activeAt"), 64),
        "value": opt(alert.get("value"), 64),
        "labels": {str(k): s(v, 128) for k, v in labels.items()},
        "annotations": {str(k): s(v, 300) for k, v in annotations.items()},
    }


def pull_alerts(conn: Any, state: str | None = None) -> list[dict]:
    """[READ] Normalised Prometheus rule alerts, optionally filtered by state.

    May raise — analysis callers pull through this so a failure propagates to the
    tool wrapper's error envelope.
    """
    data = as_obj(prom_data(conn.prom_get("/api/v1/alerts")))
    alerts = [_norm_prom_alert(a) for a in rows(data, "alerts")]
    if state is not None:
        alerts = [a for a in alerts if a["state"].lower() == state.lower()]
    return alerts


def _by_state(conn: Any, state: str) -> dict:
    """Shared read for firing/pending Prometheus alerts."""
    try:
        alerts = pull_alerts(conn, state=state)
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    by_severity: dict[str, int] = {}
    for a in alerts:
        by_severity[a["severity"] or "none"] = by_severity.get(a["severity"] or "none", 0) + 1
    return {"state": state, "total": len(alerts), "bySeverity": by_severity,
            "alerts": alerts[:_MAX_ROWS]}


def firing_alerts(conn: Any) -> dict:
    """[READ] Currently firing Prometheus rule alerts, grouped by severity."""
    return _by_state(conn, STATE_FIRING)


def pending_alerts(conn: Any) -> dict:
    """[READ] Pending (not-yet-firing) Prometheus rule alerts, by severity."""
    return _by_state(conn, STATE_PENDING)


def alertmanager_alerts(conn: Any, active_only: bool = True) -> dict:
    """[READ] Alerts as Alertmanager sees them (post grouping/silence/inhibit)."""
    try:
        params = (
            {"active": "true", "silenced": "false", "inhibited": "false"}
            if active_only else None
        )
        data = conn.am_get("/api/v2/alerts", params)
        alerts = []
        for a in (data or []):
            if not isinstance(a, dict):
                continue
            labels = as_obj(a.get("labels"))
            status = as_obj(a.get("status"))
            alerts.append({
                "alertname": s(labels.get("alertname")),
                "severity": opt(labels.get("severity"), 32),
                "fingerprint": s(a.get("fingerprint"), 64),
                "state": s(status.get("state"), 16),
                "startsAt": s(a.get("startsAt"), 64),
                "silencedBy": [s(x, 64) for x in (status.get("silencedBy") or [])],
                "labels": {str(k): s(v, 128) for k, v in labels.items()},
            })
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(alerts), "alerts": alerts[:_MAX_ROWS]}


def _norm_silence(sil: dict) -> dict:
    """Normalise one Alertmanager silence."""
    status = as_obj(sil.get("status"))
    matchers = [
        {"name": s(m.get("name"), 64), "value": s(m.get("value"), 128),
         "isRegex": bool(m.get("isRegex")), "isEqual": bool(m.get("isEqual", True))}
        for m in rows(sil, "matchers")
    ]
    return {
        "id": s(sil.get("id"), 64),
        "state": s(status.get("state"), 16),
        "startsAt": s(sil.get("startsAt"), 64),
        "endsAt": s(sil.get("endsAt"), 64),
        "createdBy": opt(sil.get("createdBy"), 128),
        "comment": opt(sil.get("comment"), 300),
        "matchers": matchers,
    }


def list_silences(conn: Any) -> dict:
    """[READ] Alertmanager silences (active, pending, expired)."""
    try:
        data = conn.am_get("/api/v2/silences")
        silences = [_norm_silence(x) for x in (data or []) if isinstance(x, dict)]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    active = sum(1 for x in silences if x["state"].lower() == "active")
    return {"total": len(silences), "active": active, "silences": silences[:_MAX_ROWS]}
