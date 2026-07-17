"""One-shot observability overview (read-only, platform-aware).

A single call an agent can lead with. For a Prometheus target: firing-alert count
+ scrape-target up/down + rule health. For a Grafana target: dashboard,
datasource, and folder counts. Resilient — a failing sub-call degrades to a
partial summary with an ``errors`` list.
"""

from __future__ import annotations

from typing import Any

from observability_aiops.config import PLATFORM_GRAFANA, PLATFORM_LOKI, PLATFORM_PROMETHEUS
from observability_aiops.ops import alerts as al
from observability_aiops.ops import grafana as gf
from observability_aiops.ops import loki as lk
from observability_aiops.ops import rules as ru
from observability_aiops.ops import targets as tg


def _prometheus_overview(conn: Any, errors: list[str]) -> dict:
    firing = al.firing_alerts(conn)
    if "error" in firing:
        errors.append(f"alerts: {firing['error']}")
        firing = {}
    scrape = tg.target_scrape_health(conn)
    if "error" in scrape:
        errors.append(f"targets: {scrape['error']}")
        scrape = {}
    health = ru.rule_health(conn)
    if "error" in health:
        errors.append(f"rules: {health['error']}")
        health = {}
    return {
        "firingAlerts": firing.get("total"),
        "targetsUp": scrape.get("up"),
        "targetsDown": scrape.get("down"),
        "rulesErroring": health.get("erroring"),
    }


def _grafana_overview(conn: Any, errors: list[str]) -> dict:
    dashboards = gf.list_dashboards(conn)
    if "error" in dashboards:
        errors.append(f"dashboards: {dashboards['error']}")
        dashboards = {}
    datasources = gf.list_datasources(conn)
    if "error" in datasources:
        errors.append(f"datasources: {datasources['error']}")
        datasources = {}
    folders = gf.list_folders(conn)
    if "error" in folders:
        errors.append(f"folders: {folders['error']}")
        folders = {}
    return {
        "dashboards": dashboards.get("total"),
        "datasources": datasources.get("total"),
        "folders": folders.get("total"),
    }


def _loki_overview(conn: Any, errors: list[str]) -> dict:
    labels = lk.loki_labels(conn)
    if "error" in labels:
        errors.append(f"labels: {labels['error']}")
        labels = {}
    return {"labelNames": labels.get("total")}


def observability_overview(conn: Any) -> dict:
    """[READ] Platform-aware health snapshot for the target."""
    errors: list[str] = []
    platform = conn.target.platform
    if platform == PLATFORM_PROMETHEUS:
        body = _prometheus_overview(conn, errors)
    elif platform == PLATFORM_GRAFANA:
        body = _grafana_overview(conn, errors)
    elif platform == PLATFORM_LOKI:
        body = _loki_overview(conn, errors)
    else:  # pragma: no cover — config validation prevents this
        body = {}
    return {
        "platform": platform,
        "target": conn.target.name,
        **body,
        "errors": errors,
    }
