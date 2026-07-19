"""Prometheus rules surface (read-only ``/api/v1/rules``).

Flattens recording + alerting rules across all rule groups and summarises their
evaluation health, so an operator can see which rules are erroring (a common
cause of missing recording metrics or silently-not-firing alerts). Resilient and
sanitized like the other read modules.
"""

from __future__ import annotations

from typing import Any

from observability_aiops.ops._util import as_obj, num, opt, prom_data, rows, s

_MAX_ROWS = 500

RULE_ALERTING = "alerting"
RULE_RECORDING = "recording"


def _rule(rule: dict, group: dict) -> dict:
    """Normalise one rule entry with its owning group's name/file."""
    return {
        "name": s(rule.get("name")),
        "type": s(rule.get("type"), 16),
        "group": s(group.get("name")),
        "file": s(group.get("file")),
        "query": s(rule.get("query"), 400),
        "health": s(rule.get("health"), 16),
        "lastError": opt(rule.get("lastError")),
        "state": opt(rule.get("state"), 16),
        "evaluationTimeSeconds": num(rule.get("evaluationTime")),
        "labels": {str(k): s(v, 128) for k, v in as_obj(rule.get("labels")).items()},
    }


def _all_rules(conn: Any) -> list[dict]:
    """Fetch + flatten every rule across groups (may raise)."""
    data = as_obj(prom_data(conn.prom_get("/api/v1/rules")))
    flat: list[dict] = []
    for group in rows(data, "groups"):
        for rule in rows(group, "rules"):
            flat.append(_rule(rule, group))
    return flat


def list_rules(conn: Any, rule_type: str | None = None) -> dict:
    """[READ] All recording + alerting rules, optionally filtered by type.

    ``rule_type`` is ``alerting`` or ``recording`` (omit for both).
    """
    try:
        flat = _all_rules(conn)
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    if rule_type is not None:
        want = rule_type.strip().lower()
        flat = [r for r in flat if r["type"] == want]
    return {
        "total": len(flat),
        "alerting": sum(1 for r in flat if r["type"] == RULE_ALERTING),
        "recording": sum(1 for r in flat if r["type"] == RULE_RECORDING),
        "rules": flat[:_MAX_ROWS],
    }


def rule_health(conn: Any) -> dict:
    """[READ] Rule-evaluation health summary + the list of erroring rules."""
    try:
        flat = _all_rules(conn)
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}
    ok = sum(1 for r in flat if r["health"].lower() == "ok")
    erroring = [r for r in flat if r["health"].lower() != "ok"]
    return {
        "totalRules": len(flat),
        "ok": ok,
        "erroring": len(erroring),
        "unhealthy": erroring[:_MAX_ROWS],
    }
