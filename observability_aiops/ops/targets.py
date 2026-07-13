"""Prometheus scrape-target surface (read-only ``/api/v1/targets``).

Normalises active + dropped scrape targets so an operator can see which endpoints
Prometheus is actually scraping, which are up/down, and what the last scrape
error was. Every call is resilient (a transport/parse failure surfaces as
``{"error": ...}``) and every server string passes through ``s``.
"""

from __future__ import annotations

from typing import Any

from observability_aiops.ops._util import as_obj, num, prom_data, rows, s

_MAX_ROWS = 500


def _active(target: dict) -> dict:
    """Normalise one activeTarget entry."""
    labels = as_obj(target.get("labels"))
    return {
        "job": s(labels.get("job")),
        "instance": s(labels.get("instance")),
        "scrapePool": s(target.get("scrapePool")),
        "scrapeUrl": s(target.get("scrapeUrl")),
        "health": s(target.get("health"), 16),
        "lastError": s(target.get("lastError")),
        "lastScrape": s(target.get("lastScrape"), 64),
        "lastScrapeDurationSeconds": num(target.get("lastScrapeDuration")),
    }


def _pull_targets(conn: Any) -> dict:
    """Fetch and unwrap the raw targets payload (may raise)."""
    return as_obj(prom_data(conn.prom_get("/api/v1/targets")))


def list_targets(conn: Any, health: str | None = None) -> dict:
    """[READ] Active scrape targets, optionally filtered by health (up/down)."""
    try:
        data = _pull_targets(conn)
        targets = [_active(t) for t in rows(data, "activeTargets")]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    if health is not None:
        want = health.strip().lower()
        targets = [t for t in targets if t["health"].lower() == want]
    return {"total": len(targets), "targets": targets[:_MAX_ROWS]}


def target_scrape_health(conn: Any) -> dict:
    """[READ] Up/down scrape-health summary plus the list of unhealthy targets."""
    try:
        data = _pull_targets(conn)
        active = [_active(t) for t in rows(data, "activeTargets")]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    up = sum(1 for t in active if t["health"].lower() == "up")
    down = [t for t in active if t["health"].lower() != "up"]
    return {
        "totalTargets": len(active),
        "up": up,
        "down": len(down),
        "unhealthy": down[:_MAX_ROWS],
    }


def dropped_targets(conn: Any) -> dict:
    """[READ] Targets discovered but dropped by relabeling (``droppedTargets``)."""
    try:
        data = _pull_targets(conn)
        dropped = [
            {str(k): s(v, 128) for k, v in as_obj(t.get("discoveredLabels")).items()}
            for t in rows(data, "droppedTargets")
        ]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    return {"total": len(dropped), "dropped": dropped[:_MAX_ROWS]}
