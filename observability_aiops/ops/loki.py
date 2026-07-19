"""Grafana Loki log-store surface (read-only LogQL + label metadata).

Thin, resilient wrappers over the Loki HTTP API: label + label-value
enumeration, and bounded LogQL ``query_range`` reads. Loki shares Prometheus'
``{"status","data"}`` envelope, so ``prom_data`` unwraps it here too. Every call
funnels server text through ``sanitize()`` via ``s`` and reports a transport,
parse, or *validation-gate* failure as ``{"error": ...}`` instead of raising.

Query bounding (the safety gate that keeps an agent from asking Loki for "all
logs, forever"):

  * ``MAX_LOOKBACK_HOURS`` caps the time window of any ``query_range``.
  * ``MAX_LINE_LIMIT`` caps the number of returned log lines.
  * A LogQL query with **no stream selector** (no ``{label="value"}``) is rejected
    up front with a teaching error — an unbounded scan is never issued.

All label values interpolated into a selector are escaped (``\\`` and ``"``) so a
hostile label value cannot break out of the LogQL string, and label *names* in a
path segment are percent-encoded via ``_seg`` per the line convention.
"""

from __future__ import annotations

import time
from typing import Any

from observability_aiops.ops._util import _seg, as_obj, num, opt, prom_data, s

# ── Bounding constants (named, not magic numbers) ────────────────────────────
MAX_LOOKBACK_HOURS = 24
DEFAULT_LOOKBACK_HOURS = 1
MAX_LINE_LIMIT = 1000
DEFAULT_LINE_LIMIT = 100
MAX_STREAMS = 200
MAX_SAMPLE_LINES = 5

_NS_PER_SEC = 1_000_000_000

# Case-insensitive error-signature filter used by the canned error reads. Kept
# as a LogQL regex; wrapped in backticks (a LogQL raw string) at call sites so
# no backslash-escaping is needed.
ERROR_FILTER_REGEX = "(?i)(error|fatal|panic|exception|traceback|stacktrace)"

# Labels an alert commonly shares with a Loki stream, in mapping priority order.
# Used by the cross-signal correlation to turn a firing alert's labels into a
# best-effort LogQL selector.
LOKI_STREAM_LABELS = (
    "namespace", "job", "service", "app", "container", "pod", "instance", "component",
)


class LokiQueryError(ValueError):
    """A LogQL query failed the bounding gate; carries a teaching message."""


def _now_ns() -> int:
    return int(time.time() * _NS_PER_SEC)


def _extract_selector(query: str) -> str | None:
    """Return the content of the first ``{...}`` stream selector, or ``None``."""
    start = query.find("{")
    if start == -1:
        return None
    end = query.find("}", start + 1)
    if end == -1:
        return None
    return query[start + 1:end]


def validate_logql(query: str) -> str:
    """Reject obviously unbounded LogQL. Returns the trimmed query when it passes.

    An agent-supplied LogQL string must carry a stream selector — without one
    Loki would scan every stream. This is the single-query bounding gate.
    """
    q = (query or "").strip()
    if not q:
        raise LokiQueryError(
            "Empty LogQL query. Provide a stream selector, e.g. "
            '\'{app="api"} |= "error"\'.'
        )
    selector = _extract_selector(q)
    if selector is None or not selector.strip():
        raise LokiQueryError(
            "Unbounded LogQL query rejected: no stream selector. Every LogQL "
            'query must scope to at least one label, e.g. \'{job="api"}\' or '
            "'{namespace=\"prod\"} |= \"error\"'. A bare filter would scan all streams."
        )
    return q


def _validate_hours(hours: float) -> float:
    """Clamp/validate the lookback window against the cap; raise a teaching error."""
    if hours <= 0:
        raise LokiQueryError("Lookback hours must be > 0.")
    if hours > MAX_LOOKBACK_HOURS:
        raise LokiQueryError(
            f"Lookback {hours}h exceeds the {MAX_LOOKBACK_HOURS}h cap. Narrow the "
            f"window (a log scan over more than {MAX_LOOKBACK_HOURS}h is refused)."
        )
    return hours


def _clamp_limit(limit: int) -> int:
    """Clamp the returned line count into ``[1, MAX_LINE_LIMIT]``."""
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = DEFAULT_LINE_LIMIT
    return max(1, min(n, MAX_LINE_LIMIT))


def _escape_label_value(value: str) -> str:
    """Escape a label value for safe interpolation into a LogQL double-quoted string."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def selector_from_pairs(pairs: list[tuple[str, str]]) -> str:
    """Build a ``{k="v",...}`` LogQL selector from (name, value) pairs (values escaped)."""
    inner = ",".join(f'{name}="{_escape_label_value(val)}"' for name, val in pairs)
    return "{" + inner + "}"


def build_selector_from_labels(
    labels: dict, max_matchers: int = 4
) -> list[tuple[str, str]]:
    """Pick up to ``max_matchers`` Loki-friendly labels from an alert label-set.

    Returns an ordered list of (name, value) pairs drawn from
    ``LOKI_STREAM_LABELS`` in priority order — the documented best-effort mapping
    a firing Prometheus alert's labels use to correlate with Loki streams.
    """
    picked: list[tuple[str, str]] = []
    for key in LOKI_STREAM_LABELS:
        val = labels.get(key)
        if val:
            picked.append((key, str(val)))
        if len(picked) >= max_matchers:
            break
    return picked


def wrap_selector(selector: str) -> str:
    """Ensure a raw selector is wrapped in braces (accept bare matchers too)."""
    sel = (selector or "").strip()
    if sel.startswith("{") and sel.endswith("}"):
        return sel
    return "{" + sel + "}"


def error_query(selector: str) -> str:
    """Canned error-level LogQL for a stream selector (line-filter on the error regex)."""
    return f"{wrap_selector(selector)} |~ `{ERROR_FILTER_REGEX}`"


def summarize_streams(data: Any, limit: int = MAX_STREAMS) -> list[dict]:
    """Normalise a ``query_range`` result into per-stream {labels, count, sampleLines}.

    Handles both ``streams`` (log) results (``stream`` + ``values``) and
    ``matrix`` (metric) results (``metric`` + ``values``). Every label and sample
    line passes through ``s`` (bounded + injection-safe).
    """
    result = data.get("result", []) if isinstance(data, dict) else []
    out: list[dict] = []
    for item in result[:limit]:
        if not isinstance(item, dict):
            continue
        labels = item.get("stream") or item.get("metric") or {}
        values = item.get("values") or []
        sample_lines = [
            s(v[1], 256)
            for v in values[:MAX_SAMPLE_LINES]
            if isinstance(v, (list, tuple)) and len(v) >= 2
        ]
        out.append({
            "labels": {str(k): s(v, 128) for k, v in labels.items()},
            "count": len(values) if isinstance(values, list) else 0,
            "sampleLines": sample_lines,
        })
    return out


def _window_ns(hours: float) -> tuple[int, int]:
    """Return (start_ns, end_ns) for a validated lookback window ending now."""
    end = _now_ns()
    start = end - int(_validate_hours(hours) * 3600 * _NS_PER_SEC)
    return start, end


def _validate_window(start_ns: int, end_ns: int) -> float:
    """Validate an explicit ``[start, end]`` window against the lookback cap."""
    span_hours = (end_ns - start_ns) / (3600 * _NS_PER_SEC)
    return _validate_hours(span_hours)


def error_streams_window(
    conn: Any, selector: str, start_ns: int, end_ns: int, limit: int = DEFAULT_LINE_LIMIT
) -> list[dict]:
    """Summarised error streams for an explicit window (may raise; used by the RCA).

    Both the current and the baseline window of ``log_error_burst_rca`` flow
    through here, so each is independently bounded by the same gate.
    """
    q = validate_logql(error_query(selector))
    _validate_window(start_ns, end_ns)
    data = _query_range_raw(conn, q, start_ns, end_ns, limit)
    return summarize_streams(data)


def _query_range_raw(
    conn: Any, logql: str, start_ns: int, end_ns: int, limit: int, probe: bool = False
) -> Any:
    """Issue a bounded ``/loki/api/v1/query_range`` and unwrap the envelope (may raise).

    With ``probe=True`` one extra line beyond the clamped limit is requested, so
    the caller can *measure* whether the result was truncated instead of
    inferring it from a length coincidence.
    """
    lines = _clamp_limit(limit) + (1 if probe else 0)
    params = {
        "query": logql,
        "start": str(start_ns),
        "end": str(end_ns),
        "limit": str(lines),
        "direction": "backward",
    }
    return prom_data(conn.loki_get("/loki/api/v1/query_range", params))


def count_entries(data: Any) -> int:
    """Total log/sample entries across every stream in a ``query_range`` result."""
    result = data.get("result", []) if isinstance(data, dict) else []
    total = 0
    for item in result:
        if isinstance(item, dict) and isinstance(item.get("values"), list):
            total += len(item["values"])
    return total


def trim_entries(data: Any, budget: int) -> Any:
    """Return a copy of a ``query_range`` result holding at most ``budget`` entries.

    Immutable by construction — the upstream payload is never mutated. Streams
    left with no entries are dropped rather than reported as empty.
    """
    if not isinstance(data, dict):
        return data
    remaining = max(0, int(budget))
    kept: list[dict] = []
    for item in data.get("result", []) or []:
        if not isinstance(item, dict):
            continue
        values = item.get("values") or []
        if not isinstance(values, list):
            kept.append(item)
            continue
        if remaining <= 0:
            break
        take = values[:remaining]
        remaining -= len(take)
        kept.append({**item, "values": take})
    return {**data, "result": kept}


def loki_labels(conn: Any, hours: float = DEFAULT_LOOKBACK_HOURS) -> dict:
    """[READ] Distinct label names present in the window (``/loki/api/v1/labels``)."""
    try:
        start, end = _window_ns(hours)
        data = prom_data(
            conn.loki_get("/loki/api/v1/labels", {"start": str(start), "end": str(end)})
        )
        labels = [s(v, 128) for v in (data or []) if isinstance(v, str)]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 300)}
    shown = labels[:MAX_STREAMS]
    return {
        "labels": shown,
        "total": len(labels),
        "returned": len(shown),
        "limit": MAX_STREAMS,
        "truncated": len(labels) > MAX_STREAMS,
    }


def loki_label_values(
    conn: Any, name: str, hours: float = DEFAULT_LOOKBACK_HOURS
) -> dict:
    """[READ] Distinct values of one label (``/loki/api/v1/label/<name>/values``).

    The label *name* is percent-encoded into the path segment.
    """
    try:
        start, end = _window_ns(hours)
        path = f"/loki/api/v1/label/{_seg(s(name, 64))}/values"
        data = prom_data(conn.loki_get(path, {"start": str(start), "end": str(end)}))
        values = [s(v, 128) for v in (data or []) if isinstance(v, str)]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 300), "label": s(name, 64)}
    shown = values[:MAX_STREAMS]
    return {
        "label": s(name, 64),
        "values": shown,
        "total": len(values),
        "returned": len(shown),
        "limit": MAX_STREAMS,
        "truncated": len(values) > MAX_STREAMS,
    }


def loki_query(
    conn: Any,
    logql: str,
    hours: float = DEFAULT_LOOKBACK_HOURS,
    limit: int = DEFAULT_LINE_LIMIT,
) -> dict:
    """[READ] Bounded LogQL ``query_range`` (validation-gated passthrough).

    Enforces the bounding gate (stream selector required, lookback <=
    ``MAX_LOOKBACK_HOURS``, lines <= ``MAX_LINE_LIMIT``) before issuing the query.

    One extra line is requested so ``truncated`` is *measured* rather than
    inferred from the line count happening to equal the limit — a long result
    that silently stops is exactly what gets reported as "no data returned".
    """
    try:
        q = validate_logql(logql)
        start, end = _window_ns(hours)
        requested = _clamp_limit(limit)
        probed = _query_range_raw(conn, q, start, end, requested, probe=True)
        truncated = count_entries(probed) > requested
        data = trim_entries(probed, requested)
        streams = summarize_streams(data)
        returned = count_entries(data)
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 300), "query": s(logql, 200)}
    return {
        "query": s(q, 200),
        "hours": _validate_hours(hours),
        "resultType": opt((data or {}).get("resultType"), 32) if isinstance(data, dict) else None,
        "streams": len(streams),
        "results": streams,
        "returned": returned,
        "limit": requested,
        "truncated": truncated,
    }


def loki_tail_errors(
    conn: Any,
    selector: str,
    hours: float = DEFAULT_LOOKBACK_HOURS,
    limit: int = DEFAULT_LINE_LIMIT,
) -> dict:
    """[READ] Canned error-level read for a stream selector (error line-filter).

    Returns ``returned`` / ``limit`` / ``truncated`` alongside the streams;
    ``truncated`` is measured by requesting one line beyond the limit.
    """
    try:
        q = validate_logql(error_query(selector))
        start, end = _window_ns(hours)
        requested = _clamp_limit(limit)
        probed = _query_range_raw(conn, q, start, end, requested, probe=True)
        truncated = count_entries(probed) > requested
        data = trim_entries(probed, requested)
        streams = summarize_streams(data)
        returned = count_entries(data)
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 300), "selector": s(selector, 200)}
    return {
        "selector": s(selector, 200),
        "query": s(q, 200),
        "hours": _validate_hours(hours),
        "streams": len(streams),
        "results": streams,
        "returned": returned,
        "limit": requested,
        "truncated": truncated,
    }


def index_stats(
    conn: Any, selector: str, hours: float = DEFAULT_LOOKBACK_HOURS
) -> dict:
    """[READ] Volume stats for a selector (``/loki/api/v1/index/stats``), best-effort.

    Not every Loki deployment/schema exposes index stats; a failure degrades to
    ``{"error": ...}`` and callers treat it as "unavailable".
    """
    try:
        q = validate_logql(wrap_selector(selector))
        start, end = _window_ns(hours)
        data = as_obj(prom_data(conn.loki_get(
            "/loki/api/v1/index/stats",
            {"query": q, "start": str(start), "end": str(end)},
        )))
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 300), "selector": s(selector, 200)}
    return {
        "selector": s(selector, 200),
        "streams": int(num(data.get("streams"))),
        "chunks": int(num(data.get("chunks"))),
        "entries": int(num(data.get("entries"))),
        "bytes": int(num(data.get("bytes"))),
    }
