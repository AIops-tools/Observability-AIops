"""Flagship signature analyses over Grafana Loki log streams.

Transparent heuristics — every ranking reports the counts that drove it, never a
black-box verdict:

  1. ``log_error_burst_rca`` — compare per-stream error counts in a window against
     a baseline window and classify each burst: a **new error signature** (absent
     in baseline), a **volume spike** (existing stream, rate jumped), or a
     **single-instance** burst (localized to one pod/instance within its app).
  2. ``log_volume_analysis`` — rank the highest-volume streams, warn on
     high-cardinality (high-churn) labels, and emit a retention hint from total
     ingest bytes when available.

Both are pure functions (no I/O): the MCP tool layer pulls the Loki telemetry and
passes normalised streams in, so they are trivially testable with canned data.
Every server-provided string is bounded via ``s``.
"""

from __future__ import annotations

from observability_aiops.ops._util import num, s

MAX_ROWS = 200

# ── 1. log error-burst RCA ───────────────────────────────────────────────────
CLASS_NEW_SIGNATURE = "new_signature"
CLASS_VOLUME_SPIKE = "volume_spike"
CLASS_SINGLE_INSTANCE = "single_instance"

DEFAULT_BURST_RATIO = 3.0
DEFAULT_MIN_ERRORS = 1

# Labels used to group streams into an "app" (what burst) and to identify the
# distinct "instance" a burst is localized to. First present wins.
_APP_KEYS = ("app", "service", "namespace", "job", "container")
_INSTANCE_KEYS = ("instance", "pod", "host", "node")

_CLASS_GUIDANCE = {
    CLASS_NEW_SIGNATURE: (
        "New error signature — this stream logged no errors in the baseline "
        "window; it appeared with this burst.",
        "Inspect the most recent deploy/config change for this app; a new error "
        "signature across instances usually means a regression — roll back if correlated.",
    ),
    CLASS_VOLUME_SPIKE: (
        "Volume spike — an existing error stream's rate jumped sharply vs baseline.",
        "Check upstream/downstream saturation or a retry storm; compare against "
        "request volume before scaling.",
    ),
    CLASS_SINGLE_INSTANCE: (
        "Single-instance burst — errors are localized to one instance/pod while its "
        "siblings stayed quiet.",
        "Cordon/restart or replace the affected instance; likely a bad node, a hot "
        "shard, or local resource exhaustion rather than an app-wide fault.",
    ),
}


def _first(labels: dict, keys: tuple[str, ...]) -> str:
    for k in keys:
        v = labels.get(k)
        if v:
            return str(v)
    return ""


def _fingerprint(labels: dict) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def log_error_burst_rca(
    current: list[dict],
    baseline: list[dict],
    burst_ratio: float = DEFAULT_BURST_RATIO,
    min_errors: int = DEFAULT_MIN_ERRORS,
) -> dict:
    """[READ] Classify error bursts per stream against a baseline window.

    Pure analysis. ``current`` / ``baseline`` are normalised streams
    ({labels, count, sampleLines}) from equal-length windows. A current stream is
    a *burst* when its error count is >= ``min_errors`` and either it is new
    (baseline count 0) or its count is >= ``burst_ratio`` x baseline. Each burst
    is classified (new signature / volume spike / single-instance) and annotated
    with a cause + action; sample lines are surfaced (already sanitised upstream).
    """
    base_by_fp: dict[tuple, int] = {}
    for st in baseline or []:
        base_by_fp[_fingerprint(st.get("labels") or {})] = int(num(st.get("count")))

    # Pass 1 — collect burst candidates and the instances bursting per app group.
    candidates: list[dict] = []
    bursting_instances: dict[str, set[str]] = {}
    for st in current or []:
        labels = st.get("labels") or {}
        count = int(num(st.get("count")))
        if count < max(1, int(min_errors)):
            continue
        base = base_by_fp.get(_fingerprint(labels), 0)
        is_new = base == 0
        is_spike = base > 0 and count >= base * burst_ratio
        if not (is_new or is_spike):
            continue
        app = _first(labels, _APP_KEYS) or "(unlabeled)"
        instance = _first(labels, _INSTANCE_KEYS)
        if instance:
            bursting_instances.setdefault(app, set()).add(instance)
        candidates.append({
            "labels": labels,
            "count": count,
            "base": base,
            "is_new": is_new,
            "app": app,
            "instance": instance,
            "sampleLines": [s(x, 256) for x in (st.get("sampleLines") or [])][:5],
        })

    # Pass 2 — classify. Single-instance wins when a burst is the only bursting
    # instance within its app group (and it carries an instance label).
    bursts = []
    for c in candidates:
        instances = bursting_instances.get(c["app"], set())
        if c["instance"] and len(instances) == 1:
            klass = CLASS_SINGLE_INSTANCE
        elif c["is_new"]:
            klass = CLASS_NEW_SIGNATURE
        else:
            klass = CLASS_VOLUME_SPIKE
        cause, action = _CLASS_GUIDANCE[klass]
        bursts.append({
            "labels": {str(k): s(v, 128) for k, v in c["labels"].items()},
            "app": s(c["app"], 128),
            "currentErrors": c["count"],
            "baselineErrors": c["base"],
            "classification": klass,
            "cause": cause,
            "action": action,
            "sampleLines": c["sampleLines"],
        })

    bursts.sort(key=lambda e: e["currentErrors"], reverse=True)
    by_class: dict[str, int] = {}
    for e in bursts:
        by_class[e["classification"]] = by_class.get(e["classification"], 0) + 1
    return {
        "streamsEvaluated": len(current or []),
        "burstCount": len(bursts),
        "byClassification": by_class,
        "burstRatio": burst_ratio,
        "bursts": bursts[:MAX_ROWS],
        "note": (
            "Advisory read-only heuristic: per-stream error counts compared to a "
            "baseline window; a burst is new-signature, volume-spike, or "
            "single-instance. Sample lines are illustrative — verify before acting."
        ),
    }


# ── 2. log volume & cardinality analysis ─────────────────────────────────────
DEFAULT_HIGH_CARDINALITY = 20


def log_volume_analysis(
    streams: list[dict],
    total_stats: dict | None = None,
    high_cardinality_threshold: int = DEFAULT_HIGH_CARDINALITY,
) -> dict:
    """[READ] Rank top streams by volume and warn on high-churn (high-cardinality) labels.

    Pure analysis. ``streams`` are normalised ({labels, count}). Ranks the biggest
    log producers, then counts distinct values per label across all streams; a
    label whose distinct-value count is >= ``high_cardinality_threshold`` is
    flagged as high-churn (a cardinality-explosion risk). ``total_stats`` (from
    Loki ``index/stats``) drives an optional retention hint.
    """
    ranked = []
    values_by_label: dict[str, set[str]] = {}
    total_lines = 0
    for st in streams or []:
        labels = st.get("labels") or {}
        count = int(num(st.get("count")))
        total_lines += count
        ranked.append({
            "labels": {str(k): s(v, 128) for k, v in labels.items()},
            "count": count,
        })
        for k, v in labels.items():
            values_by_label.setdefault(str(k), set()).add(str(v))

    ranked.sort(key=lambda e: e["count"], reverse=True)

    high_churn = []
    for label, vals in values_by_label.items():
        distinct = len(vals)
        if distinct >= high_cardinality_threshold:
            high_churn.append({
                "label": s(label, 64),
                "distinctValues": distinct,
                "warning": (
                    f"'{s(label, 64)}' has {distinct} distinct values across streams — "
                    "high-cardinality labels multiply stream count and index size; "
                    "avoid putting unbounded values (ids, timestamps) in stream labels."
                ),
            })
    high_churn.sort(key=lambda e: e["distinctValues"], reverse=True)

    retention_hint = ""
    if isinstance(total_stats, dict) and not total_stats.get("error"):
        total_bytes = int(num(total_stats.get("bytes")))
        if total_bytes > 0:
            gib = total_bytes / (1024 ** 3)
            retention_hint = (
                f"~{gib:.2f} GiB ingested over the sampled window for this selector. "
                "Size retention against your disk budget; drop or aggregate the "
                "highest-volume streams above if retention is tight."
            )

    return {
        "streamsEvaluated": len(streams or []),
        "totalLines": total_lines,
        "topStreams": ranked[:MAX_ROWS],
        "highCardinalityLabels": high_churn[:MAX_ROWS],
        "retentionHint": retention_hint,
        "note": (
            "Advisory read-only heuristic: streams ranked by line volume; labels "
            "with many distinct values flagged as high-churn cardinality risks."
        ),
    }
