"""Unit tests for Prometheus scrape-target + rule ops and MCP tools."""

from unittest.mock import MagicMock

import pytest

from observability_aiops.ops import rules as rules_ops
from observability_aiops.ops import targets as targets_ops

_TARGETS = {
    "status": "success",
    "data": {
        "activeTargets": [
            {"labels": {"job": "api", "instance": "a:80"}, "scrapeUrl": "http://a:80/metrics",
             "health": "up", "lastError": "", "lastScrapeDuration": 0.01},
            {"labels": {"job": "db", "instance": "b:90"}, "scrapeUrl": "http://b:90/metrics",
             "health": "down", "lastError": "connection refused", "lastScrapeDuration": 0.0},
        ],
        "droppedTargets": [
            {"discoveredLabels": {"__address__": "z:99", "job": "old"}},
        ],
    },
}


def _prom(payload):
    conn = MagicMock(name="conn")
    conn.target.platform = "prometheus"
    conn.prom_get.return_value = payload
    return conn


@pytest.mark.unit
def test_list_targets_filters_by_health():
    conn = _prom(_TARGETS)
    assert targets_ops.list_targets(conn)["total"] == 2
    down = targets_ops.list_targets(conn, health="down")
    assert down["total"] == 1 and down["targets"][0]["job"] == "db"


@pytest.mark.unit
def test_target_scrape_health_counts_up_down():
    out = targets_ops.target_scrape_health(_prom(_TARGETS))
    assert out["totalTargets"] == 2 and out["up"] == 1 and out["down"] == 1
    assert out["unhealthy"][0]["lastError"] == "connection refused"


@pytest.mark.unit
def test_dropped_targets_normalizes_labels():
    out = targets_ops.dropped_targets(_prom(_TARGETS))
    assert out["total"] == 1 and out["dropped"][0]["job"] == "old"


_RULES = {
    "status": "success",
    "data": {"groups": [
        {"name": "g1", "file": "/etc/rules.yml", "rules": [
            {"name": "HighLatency", "type": "alerting", "query": "x > 1", "health": "ok"},
            {"name": "job:req:rate", "type": "recording", "query": "sum(rate(x[5m]))",
             "health": "err", "lastError": "boom"},
        ]},
    ]},
}


@pytest.mark.unit
def test_list_rules_counts_types_and_filters():
    conn = _prom(_RULES)
    allout = rules_ops.list_rules(conn)
    assert allout["total"] == 2 and allout["alerting"] == 1 and allout["recording"] == 1
    only_alerting = rules_ops.list_rules(conn, "alerting")
    assert only_alerting["total"] == 1 and only_alerting["rules"][0]["name"] == "HighLatency"


@pytest.mark.unit
def test_rule_health_flags_erroring():
    out = rules_ops.rule_health(_prom(_RULES))
    assert out["totalRules"] == 2 and out["ok"] == 1 and out["erroring"] == 1
    assert out["unhealthy"][0]["name"] == "job:req:rate"


@pytest.mark.unit
def test_target_and_rule_tools_governed_low():
    from mcp_server.tools import prometheus, rules, targets

    for fn in (targets.list_targets, targets.target_scrape_health, targets.dropped_targets,
               rules.list_rules, rules.rule_health, prometheus.prometheus_config_status,
               prometheus.prometheus_tsdb_status):
        assert fn._risk_level == "low"
        assert getattr(fn, "_is_governed_tool", False)
