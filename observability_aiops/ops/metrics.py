"""Prometheus metrics surface (read-only PromQL + metadata).

Thin, resilient wrappers over the Prometheus HTTP query API: instant + range
PromQL evaluation, label-value enumeration, and series metadata. Every call
unwraps the ``{"status","data"}`` envelope, funnels server text through
``sanitize()`` via ``s``, and reports a transport/parse failure as
``{"error": ...}`` instead of raising.
"""

from __future__ import annotations

from typing import Any

from observability_aiops.ops._util import _seg, num, prom_data, rows, s

_MAX_SERIES = 500
_MAX_POINTS = 500


def _samples(result: list, limit: int = _MAX_SERIES) -> list[dict]:
    """Normalise an instant-vector result into {metric, value, timestamp} rows."""
    out: list[dict] = []
    for item in result[:limit]:
        if not isinstance(item, dict):
            continue
        value = item.get("value") or [None, None]
        out.append({
            "metric": {str(k): s(v, 128) for k, v in (item.get("metric") or {}).items()},
            "timestamp": num(value[0]) if len(value) > 0 else 0.0,
            "value": num(value[1]) if len(value) > 1 else 0.0,
        })
    return out


def instant_query(conn: Any, query: str, time: str | None = None) -> dict:
    """[READ] Evaluate a PromQL expression at a single instant (``/api/v1/query``)."""
    try:
        params: dict[str, Any] = {"query": query}
        if time:
            params["time"] = time
        data = prom_data(conn.prom_get("/api/v1/query", params))
        result = data.get("result", []) if isinstance(data, dict) else []
        samples = _samples(result)
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "query": s(query, 200)}
    return {
        "query": s(query, 200),
        "resultType": s((data or {}).get("resultType"), 32),
        "series": len(samples),
        "samples": samples,
    }


def range_query(
    conn: Any, query: str, start: str, end: str, step: str = "60s"
) -> dict:
    """[READ] Evaluate PromQL over a time range (``/api/v1/query_range``)."""
    try:
        params = {"query": query, "start": start, "end": end, "step": step}
        data = prom_data(conn.prom_get("/api/v1/query_range", params))
        result = data.get("result", []) if isinstance(data, dict) else []
        series = []
        for item in result[:_MAX_SERIES]:
            if not isinstance(item, dict):
                continue
            values = item.get("values") or []
            points = [
                {"timestamp": num(p[0]), "value": num(p[1])}
                for p in values[:_MAX_POINTS]
                if isinstance(p, (list, tuple)) and len(p) >= 2
            ]
            series.append({
                "metric": {str(k): s(v, 128) for k, v in (item.get("metric") or {}).items()},
                "points": points,
            })
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "query": s(query, 200)}
    return {
        "query": s(query, 200),
        "start": s(start, 64),
        "end": s(end, 64),
        "step": s(step, 32),
        "series": len(series),
        "results": series,
    }


def label_values(conn: Any, label: str = "__name__", match: str | None = None) -> dict:
    """[READ] Distinct values of a label (``/api/v1/label/<name>/values``).

    ``label`` defaults to ``__name__`` (the list of all metric names). Pass a
    PromQL ``match`` selector to scope the values to matching series.
    """
    try:
        params = {"match[]": match} if match else None
        data = prom_data(conn.prom_get(f"/api/v1/label/{_seg(s(label, 64))}/values", params))
        values = [s(v, 128) for v in (data or []) if isinstance(v, str)]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "label": s(label, 64)}
    return {"label": s(label, 64), "total": len(values), "values": values[:_MAX_SERIES]}


def series_metadata(
    conn: Any, match: str, start: str | None = None, end: str | None = None
) -> dict:
    """[READ] Series (label-set) metadata for a selector (``/api/v1/series``)."""
    try:
        params: dict[str, Any] = {"match[]": match}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        data = prom_data(conn.prom_get("/api/v1/series", params))
        series = [
            {str(k): s(v, 128) for k, v in r.items()}
            for r in rows(data)
        ]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "match": s(match, 200)}
    return {"match": s(match, 200), "total": len(series), "series": series[:_MAX_SERIES]}
