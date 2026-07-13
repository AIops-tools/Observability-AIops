"""Shared helpers for the observability ops modules.

The Prometheus HTTP API wraps results in ``{"status":"success","data":{...}}``;
Grafana returns bare objects/arrays; Alertmanager returns bare arrays. ``prom_data``
unwraps the Prometheus envelope, ``rows`` / ``as_obj`` normalise list/dict access,
and ``s`` funnels every server-provided string through ``sanitize()``
(bounded length, output hygiene) before it reaches the caller.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from observability_aiops.governance import sanitize


def _seg(value: Any) -> str:
    """URL-encode one REST path segment.

    Agent-supplied identifiers (silence ids, dashboard UIDs, label names) are
    interpolated into URL paths; encoding with ``safe=""`` ensures ``/``, ``..``
    sequences, ``?`` etc. cannot rewrite the request path.
    """
    return quote(str(value), safe="")


def prom_data(payload: Any) -> Any:
    """Unwrap a Prometheus ``{"status","data"}`` envelope, returning ``data``.

    Raises ``ValueError`` when Prometheus reports ``status != "success"`` so the
    caller surfaces the API's own error text instead of silently returning empty.
    """
    if not isinstance(payload, dict):
        return payload
    if payload.get("status") == "error":
        raise ValueError(sanitize(str(payload.get("error", "prometheus error")), 200))
    return payload.get("data", payload)


def rows(data: Any, key: str = "") -> list[dict]:
    """Return a list of dict rows from a list, or from ``data[key]`` if a dict."""
    if isinstance(data, dict):
        items = data.get(key, []) if key else []
    else:
        items = data
    return [r for r in (items or []) if isinstance(r, dict)]


def as_obj(data: Any) -> dict:
    """Return ``data`` as a dict (empty dict if it isn't one)."""
    return data if isinstance(data, dict) else {}


def s(value: Any, limit: int = 256) -> str:
    """Sanitize an arbitrary value to a bounded, injection-safe string."""
    return sanitize(str(value if value is not None else ""), limit)


def num(value: Any, default: float = 0.0) -> float:
    """Coerce a value to float; ``default`` when absent/non-numeric.

    Prometheus sample values arrive as strings (``["<ts>", "<value>"]``); this
    tolerates that plus ``NaN``/``Inf`` markers by falling back to ``default``.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float("inf"), float("-inf")):  # NaN / Inf
        return default
    return f
