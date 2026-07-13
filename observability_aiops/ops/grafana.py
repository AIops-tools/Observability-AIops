"""Grafana surface (read-only): dashboards, datasources, folders, health.

Thin wrappers over the Grafana HTTP API. Reads are resilient (a transport/parse
failure surfaces as ``{"error": ...}``) and every server string passes through
``s``. ``fetch_dashboard_model`` returns a dashboard's *raw* model and is reused
by the governed ``update_dashboard`` / ``delete_dashboard`` writes to capture the
before-state for undo.
"""

from __future__ import annotations

from typing import Any

from observability_aiops.ops._util import _seg, as_obj, s

_MAX_ROWS = 500


def list_dashboards(conn: Any, query: str | None = None) -> dict:
    """[READ] Dashboards via ``/api/search`` (optionally filtered by title query)."""
    try:
        params: dict[str, Any] = {"type": "dash-db"}
        if query:
            params["query"] = query
        data = conn.graf_get("/api/search", params)
        dashboards = [{
            "uid": s(d.get("uid"), 64),
            "title": s(d.get("title")),
            "folderTitle": s(d.get("folderTitle")),
            "tags": [s(t, 64) for t in (d.get("tags") or [])],
            "url": s(d.get("url"), 256),
        } for d in (data or []) if isinstance(d, dict)]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(dashboards), "dashboards": dashboards[:_MAX_ROWS]}


def fetch_dashboard_model(conn: Any, uid: str) -> dict:
    """Fetch a dashboard's raw ``{dashboard, meta}`` model (may raise)."""
    return as_obj(conn.graf_get(f"/api/dashboards/uid/{_seg(s(uid, 64))}"))


def get_dashboard(conn: Any, uid: str) -> dict:
    """[READ] One dashboard's summary (title, version, panel + tag counts)."""
    try:
        model = fetch_dashboard_model(conn, uid)
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "uid": s(uid, 64)}
    dash = as_obj(model.get("dashboard"))
    meta = as_obj(model.get("meta"))
    panels = dash.get("panels")
    return {
        "uid": s(dash.get("uid") or uid, 64),
        "title": s(dash.get("title")),
        "version": dash.get("version") if isinstance(dash.get("version"), int) else None,
        "panelCount": len(panels) if isinstance(panels, list) else 0,
        "tags": [s(t, 64) for t in (dash.get("tags") or [])],
        "folderTitle": s(meta.get("folderTitle")),
        "isStarred": bool(meta.get("isStarred")),
    }


def list_datasources(conn: Any) -> dict:
    """[READ] Configured datasources (id, uid, name, type, default flag)."""
    try:
        data = conn.graf_get("/api/datasources")
        sources = [{
            "id": ds.get("id") if isinstance(ds.get("id"), int) else None,
            "uid": s(ds.get("uid"), 64),
            "name": s(ds.get("name")),
            "type": s(ds.get("type"), 64),
            "isDefault": bool(ds.get("isDefault")),
        } for ds in (data or []) if isinstance(ds, dict)]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(sources), "datasources": sources[:_MAX_ROWS]}


def datasource_health(conn: Any, datasource_id: int) -> dict:
    """[READ] Health of one datasource (``/api/datasources/{id}/health``)."""
    try:
        data = as_obj(conn.graf_get(f"/api/datasources/{int(datasource_id)}/health"))
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "datasourceId": int(datasource_id)}
    return {
        "datasourceId": int(datasource_id),
        "status": s(data.get("status"), 32),
        "message": s(data.get("message"), 300),
    }


def list_folders(conn: Any) -> dict:
    """[READ] Grafana folders (``/api/folders``)."""
    try:
        data = conn.graf_get("/api/folders")
        folders = [{
            "uid": s(f.get("uid"), 64),
            "title": s(f.get("title")),
        } for f in (data or []) if isinstance(f, dict)]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(folders), "folders": folders[:_MAX_ROWS]}
