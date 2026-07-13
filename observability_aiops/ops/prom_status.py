"""Prometheus server status (read-only ``/api/v1/status/...``).

Exposes the runtime config (as a stable hash, never the raw secrets-bearing
YAML) and TSDB head statistics — the cardinality signals an operator watches to
catch a metrics explosion. ``config_hash`` is reused by the governed
``reload_prometheus_config`` write to record the pre-reload config fingerprint.
"""

from __future__ import annotations

import hashlib
from typing import Any

from observability_aiops.ops._util import as_obj, num, prom_data, rows, s

_MAX_ROWS = 50


def config_hash(conn: Any) -> str:
    """Return a sha256 fingerprint of the running Prometheus config YAML.

    Best-effort — returns ``""`` if the status endpoint is unavailable. The raw
    YAML (which can embed scrape credentials) is never returned; only its hash.
    """
    try:
        data = as_obj(prom_data(conn.prom_get("/api/v1/status/config")))
        yaml_text = str(data.get("yaml", ""))
    except Exception:  # noqa: BLE001 — hashing is best-effort context
        return ""
    if not yaml_text:
        return ""
    return hashlib.sha256(yaml_text.encode("utf-8")).hexdigest()


def config_status(conn: Any) -> dict:
    """[READ] Running-config fingerprint + size (never the raw YAML/secrets)."""
    try:
        data = as_obj(prom_data(conn.prom_get("/api/v1/status/config")))
        yaml_text = str(data.get("yaml", ""))
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    digest = hashlib.sha256(yaml_text.encode("utf-8")).hexdigest() if yaml_text else ""
    return {
        "configLoaded": bool(yaml_text),
        "configHash": digest,
        "configBytes": len(yaml_text.encode("utf-8")),
    }


def tsdb_status(conn: Any) -> dict:
    """[READ] TSDB head cardinality stats + the top metrics by series count."""
    try:
        data = as_obj(prom_data(conn.prom_get("/api/v1/status/tsdb")))
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    head = as_obj(data.get("headStats"))
    top = [
        {"metric": s(r.get("name")), "series": int(num(r.get("value")))}
        for r in rows(data, "seriesCountByMetricName")
    ]
    return {
        "numSeries": int(num(head.get("numSeries"))),
        "numLabelPairs": int(num(head.get("numLabelPairs"))),
        "chunkCount": int(num(head.get("chunkCount"))),
        "topSeriesByMetric": top[:_MAX_ROWS],
    }
