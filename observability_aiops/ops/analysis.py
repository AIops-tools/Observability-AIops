"""Flagship signature analyses over Prometheus/Alertmanager telemetry.

These are the differentiators — transparent heuristics where every ranking is
reported with the numbers/text that drove it, never a black-box verdict:

  1. ``firing_alert_rca`` — join firing alerts to their rule expressions and map
     each to a likely cause + recommended action.
  2. ``target_scrape_health_analysis`` — rank down/erroring scrape targets and
     classify each ``lastError`` into a likely cause + fix.
  3. ``alert_noise_and_flap_analysis`` — find frequently-repeated / duplicate
     alerts and recommend a dedup / rollup (group_by, inhibition, longer ``for``).

All three are pure functions (no I/O): the MCP tool layer pulls the telemetry and
passes it in, so they are trivially testable with injected data.
"""

from __future__ import annotations

from observability_aiops.ops._util import opt, s

MAX_ROWS = 200

# ── 1. firing alert RCA ──────────────────────────────────────────────────────
_SEVERITY_WEIGHT = {"critical": 3, "warning": 2, "info": 1, "none": 0}

# Ordered (keyword-set → cause, action). First match wins; checked against the
# alertname + rule expression together (lower-cased).
_ALERT_SIGNATURES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("down", "up == 0", "up==0", "absent", "targetdown"),
     "Target/instance is down or not being scraped (up==0 or absent()).",
     "Check the scrape target's process + port and Prometheus /targets; restart the exporter."),
    (("cert", "certificate", "x509", "ssl", "tls expir"),
     "TLS certificate is expired or near expiry.",
     "Rotate/renew the certificate before endsAt; verify the cert chain."),
    (("latency", "slow", "duration", "p99", "p95", "responsetime"),
     "Latency SLO breach (request duration above threshold).",
     "Check downstream dependencies and saturation; scale or shed load."),
    (("error", "5xx", "4xx", "failrate", "failure"),
     "Elevated error rate.",
     "Inspect recent deploys/logs for the failing service; roll back if correlated."),
    (("cpu", "memory", "mem ", "oom", "disk", "space", "filesystem", "saturat"),
     "Resource saturation (CPU/memory/disk near limit).",
     "Add capacity or tune limits/requests; clear disk or raise the volume size."),
    (("throttl", "rate limit", "ratelimit", "429"),
     "Client/API throttling (rate limits hit).",
     "Back off callers or raise the limit; check for a runaway client."),
)


def _classify_alert(alertname: str, expr: str, severity: str) -> dict:
    """Map an alert (name + expr + severity) to a likely cause + action."""
    hay = f"{alertname} {expr}".lower()
    for keywords, cause, action in _ALERT_SIGNATURES:
        if any(k in hay for k in keywords):
            return {"cause": cause, "action": action}
    if severity == "critical":
        return {
            "cause": "Critical rule fired — no keyword signature matched.",
            "action": "Read the rule expression + annotations; correlate with recent changes.",
        }
    return {
        "cause": "Rule fired — cause not inferable from name/expr alone.",
        "action": "Inspect the rule expression and the alert's labels/annotations.",
    }


def firing_alert_rca(alerts: list[dict], rules: list[dict]) -> dict:
    """[READ] Join firing alerts to their rules and map each to cause + action.

    Pure analysis. ``alerts`` are normalised firing alerts ({alertname, severity,
    labels, annotations, value}); ``rules`` are normalised alerting rules
    ({name, query, ...}). Each firing alert is matched to its rule by name to
    recover the expression, ranked worst-first by severity, and annotated with a
    likely cause + recommended action. Every entry carries its severity + expr.
    """
    expr_by_name: dict[str, str] = {}
    for r in rules or []:
        name = r.get("name")
        if name and name not in expr_by_name:
            expr_by_name[str(name)] = str(r.get("query") or "")

    ranked = []
    for a in alerts or []:
        alertname = str(a.get("alertname") or "")
        severity = str(a.get("severity") or "none").lower()
        expr = expr_by_name.get(alertname, "")
        annotations = a.get("annotations") or {}
        entry = {
            "alertname": s(alertname),
            "severity": severity,
            "value": opt(a.get("value"), 64),
            "expr": s(expr, 400),
            "summary": opt(annotations.get("summary") or annotations.get("description")),
            "runbookUrl": opt(annotations.get("runbook_url"), 256),
            "_weight": _SEVERITY_WEIGHT.get(severity, 0),
        }
        entry.update(_classify_alert(alertname, expr, severity))
        ranked.append(entry)

    ranked.sort(key=lambda e: e["_weight"], reverse=True)
    for e in ranked:
        e.pop("_weight", None)
    by_severity: dict[str, int] = {}
    for e in ranked:
        by_severity[e["severity"]] = by_severity.get(e["severity"], 0) + 1
    return {
        "firingCount": len(ranked),
        "bySeverity": by_severity,
        "rootCauses": ranked[:MAX_ROWS],
        "note": (
            "Advisory read-only heuristic: firing alerts ranked by severity, each "
            "matched to its rule expr and mapped to a likely cause via keyword "
            "signatures. Verify against logs before acting."
        ),
    }


# ── 2. target scrape health analysis ────────────────────────────────────────
_SCRAPE_SIGNATURES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("connection refused", "refused"),
     "Exporter/process not listening (connection refused).",
     "Confirm the target process is up and bound to the scrape port."),
    (("context deadline exceeded", "timeout", "timed out", "deadline"),
     "Scrape timed out (slow endpoint or network).",
     "Raise scrape_timeout or fix the slow /metrics handler; check network latency."),
    (("no such host", "dns", "name resolution", "lookup"),
     "DNS/service-discovery failure (host cannot be resolved).",
     "Fix DNS or the SD config; the target address may be stale."),
    (("401", "403", "unauthorized", "forbidden", "authentication"),
     "Authentication/authorization rejected the scrape.",
     "Fix the bearer_token/basic_auth in the scrape config for this job."),
    (("x509", "certificate", "tls", "handshake"),
     "TLS handshake/certificate failure.",
     "Fix the cert or set the correct tls_config (ca_file/insecure_skip_verify)."),
    (("connection reset", "reset by peer", "broken pipe", "eof"),
     "Connection reset mid-scrape (firewall/proxy or crash).",
     "Check firewalls/proxies between Prometheus and the target; inspect target logs."),
    (("server returned http status 5", "500", "502", "503", "504"),
     "Target returned a 5xx on /metrics.",
     "The exporter is erroring — check its logs/health."),
)


def _classify_scrape(last_error: str) -> dict:
    """Map a scrape ``lastError`` string to a likely cause + fix."""
    err = (last_error or "").lower()
    if not err:
        return {"cause": "Marked down with no lastError text.",
                "action": "Re-check the target manually; the endpoint may be flapping."}
    for keywords, cause, action in _SCRAPE_SIGNATURES:
        if any(k in err for k in keywords):
            return {"cause": cause, "action": action}
    return {"cause": "Scrape failing — unrecognised error.",
            "action": "Read the lastError verbatim and curl the scrapeUrl from the Prom host."}


def target_scrape_health_analysis(targets: list[dict]) -> dict:
    """[READ] Rank down/erroring scrape targets and classify each cause.

    Pure analysis. ``targets`` are normalised active targets ({job, instance,
    scrapeUrl, health, lastError, lastScrapeDurationSeconds}). Down targets rank
    first, then healthy-but-slow ones by scrape duration; each unhealthy target
    is annotated with a likely cause + fix from its ``lastError``.
    """
    unhealthy = []
    slow = []
    for t in targets or []:
        health = str(t.get("health") or "").lower()
        base = {
            "job": s(t.get("job")),
            "instance": s(t.get("instance")),
            "scrapeUrl": s(t.get("scrapeUrl")),
            "health": health,
            "lastError": opt(t.get("lastError")),
            "scrapeDurationSeconds": t.get("lastScrapeDurationSeconds"),
        }
        if health != "up":
            entry = {**base}
            entry.update(_classify_scrape(str(t.get("lastError") or "")))
            unhealthy.append(entry)
        else:
            slow.append(base)

    slow.sort(key=lambda t: t.get("scrapeDurationSeconds") or 0.0, reverse=True)
    return {
        "totalTargets": len(targets or []),
        "downCount": len(unhealthy),
        "downTargets": unhealthy[:MAX_ROWS],
        "slowestHealthy": slow[:5],
        "note": (
            "Advisory read-only heuristic: down targets ranked first with a cause "
            "classified from lastError; slowestHealthy surfaces near-timeout scrapes."
        ),
    }


# ── 3. alert noise & flap analysis ──────────────────────────────────────────
DEFAULT_NOISE_THRESHOLD = 5


def alert_noise_and_flap_analysis(
    alerts: list[dict], noise_threshold: int = DEFAULT_NOISE_THRESHOLD
) -> dict:
    """[READ] Find noisy/duplicate alert groups and recommend dedup/rollup.

    Pure analysis. ``alerts`` are normalised alert instances ({alertname,
    severity, labels}). Groups by alertname and counts distinct instances; a
    group at/above ``noise_threshold`` instances (or with exact duplicate
    label-sets) is flagged noisy with a concrete recommendation (group_by +
    inhibition + a longer ``for``). Every flag carries its counts.
    """
    groups: dict[str, dict] = {}
    for a in alerts or []:
        name = str(a.get("alertname") or "(unnamed)")
        labels = a.get("labels") or {}
        instance = str(labels.get("instance") or labels.get("pod") or "")
        fingerprint = tuple(sorted((str(k), str(v)) for k, v in labels.items()))
        g = groups.setdefault(name, {
            "alertname": s(name), "count": 0,
            "instances": set(), "fingerprints": set(),
            "severities": set(),
        })
        g["count"] += 1
        if instance:
            g["instances"].add(instance)
        g["fingerprints"].add(fingerprint)
        g["severities"].add(str(a.get("severity") or "none"))

    noisy = []
    for g in groups.values():
        duplicates = g["count"] - len(g["fingerprints"])
        distinct_instances = len(g["instances"])
        is_noisy = g["count"] >= noise_threshold or duplicates > 0
        if not is_noisy:
            continue
        if duplicates > 0:
            rec = (
                "Exact-duplicate alert instances detected — deduplicate at the "
                "source rule or add an Alertmanager inhibition rule."
            )
        else:
            rec = (
                f"{distinct_instances} instances of one alert — add group_by "
                f"['alertname'] in Alertmanager to roll them into one notification, "
                f"and raise the rule 'for:' to suppress brief flaps."
            )
        noisy.append({
            "alertname": g["alertname"],
            "count": g["count"],
            "distinctInstances": distinct_instances,
            "duplicateInstances": duplicates,
            "severities": sorted(s(x, 32) for x in g["severities"]),
            "recommendation": rec,
        })

    noisy.sort(key=lambda e: e["count"], reverse=True)
    return {
        "alertsEvaluated": len(alerts or []),
        "distinctAlertnames": len(groups),
        "noisyGroups": len(noisy),
        "threshold": noise_threshold,
        "recommendations": noisy[:MAX_ROWS],
        "note": (
            "Advisory read-only heuristic: an alertname with >= threshold instances "
            "or exact-duplicate label-sets is flagged for group_by/inhibition/longer 'for'."
        ),
    }
