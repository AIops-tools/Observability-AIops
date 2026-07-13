"""Tests for the flagship analyses (pure fns + governed MCP tool markers)."""

import pytest

from observability_aiops.ops import analysis as ops

# ── firing_alert_rca ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_firing_alert_rca_ranks_by_severity_and_classifies():
    alerts = [
        {"alertname": "HighLatency", "severity": "warning", "labels": {}, "annotations": {}},
        {"alertname": "TargetDown", "severity": "critical", "labels": {},
         "annotations": {"summary": "db down", "runbook_url": "http://rb"}},
    ]
    rules = [
        {"name": "TargetDown", "query": "up == 0"},
        {"name": "HighLatency", "query": "latency_p99 > 1"},
    ]
    out = ops.firing_alert_rca(alerts, rules)
    assert out["firingCount"] == 2
    # critical ranks first
    top = out["rootCauses"][0]
    assert top["alertname"] == "TargetDown"
    assert "down" in top["cause"].lower()
    assert top["expr"] == "up == 0"
    assert top["runbookUrl"] == "http://rb"
    # latency classified distinctly
    latency = next(e for e in out["rootCauses"] if e["alertname"] == "HighLatency")
    assert "latency" in latency["cause"].lower()


@pytest.mark.unit
def test_firing_alert_rca_empty():
    out = ops.firing_alert_rca([], [])
    assert out["firingCount"] == 0 and out["rootCauses"] == []


# ── target_scrape_health_analysis ────────────────────────────────────────────


@pytest.mark.unit
def test_scrape_health_classifies_causes():
    targets = [
        {"job": "api", "instance": "a", "health": "up", "lastError": "",
         "lastScrapeDurationSeconds": 0.4},
        {"job": "db", "instance": "b", "health": "down",
         "lastError": "dial tcp: connection refused", "lastScrapeDurationSeconds": 0.0},
        {"job": "auth", "instance": "c", "health": "down",
         "lastError": "server returned HTTP status 401 Unauthorized",
         "lastScrapeDurationSeconds": 0.0},
    ]
    out = ops.target_scrape_health_analysis(targets)
    assert out["totalTargets"] == 3 and out["downCount"] == 2
    by_job = {t["job"]: t for t in out["downTargets"]}
    assert "not listening" in by_job["db"]["cause"].lower()
    assert "auth" in by_job["auth"]["cause"].lower()
    assert out["slowestHealthy"][0]["job"] == "api"


# ── alert_noise_and_flap_analysis ────────────────────────────────────────────


@pytest.mark.unit
def test_noise_analysis_flags_high_instance_count():
    alerts = [
        {"alertname": "TargetDown", "severity": "critical",
         "labels": {"instance": f"host-{i}:80"}}
        for i in range(6)
    ]
    out = ops.alert_noise_and_flap_analysis(alerts, noise_threshold=5)
    assert out["noisyGroups"] == 1
    rec = out["recommendations"][0]
    assert rec["alertname"] == "TargetDown" and rec["distinctInstances"] == 6
    assert "group_by" in rec["recommendation"]


@pytest.mark.unit
def test_noise_analysis_flags_exact_duplicates():
    alerts = [
        {"alertname": "Dup", "severity": "warning", "labels": {"instance": "x"}},
        {"alertname": "Dup", "severity": "warning", "labels": {"instance": "x"}},
    ]
    out = ops.alert_noise_and_flap_analysis(alerts, noise_threshold=99)
    assert out["noisyGroups"] == 1
    assert out["recommendations"][0]["duplicateInstances"] == 1


@pytest.mark.unit
def test_analysis_tools_are_governed_low_and_run():
    from mcp_server.tools import analysis

    for fn in (analysis.firing_alert_rca, analysis.target_scrape_health_analysis,
               analysis.alert_noise_and_flap_analysis):
        assert getattr(fn, "_is_governed_tool", False) is True
        assert fn._risk_level == "low"
