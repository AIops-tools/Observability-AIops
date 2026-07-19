"""Absent fields come back as null, not as an empty string.

An empty string reads as "this field exists and is empty"; a missing field is a
different fact. Collapsing the two hides information from any consumer, and a
smaller local model will confidently invent the difference. These tests pin the
contract end-to-end: helper, ops layer, and the consumers (analysis + CLI) that
now have to cope with a null.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from observability_aiops.cli import app
from observability_aiops.governance import opt_str
from observability_aiops.ops import alerts as alerts_ops
from observability_aiops.ops import analysis as an
from observability_aiops.ops import rules as rules_ops
from observability_aiops.ops import targets as targets_ops

runner = CliRunner()


def _prom(payload):
    conn = MagicMock(name="conn")
    conn.target.platform = "prometheus"
    conn.prom_get.return_value = payload
    return conn


# ── the helper itself ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_opt_str_distinguishes_absent_from_empty():
    assert opt_str(None) is None, "absent must stay absent"
    assert opt_str("") == "", "a genuinely empty value is not the same as absent"
    assert opt_str("critical", 64) == "critical"


@pytest.mark.unit
def test_opt_str_still_sanitizes_and_truncates():
    assert opt_str("a\x00b") == "ab"  # control character stripped
    assert opt_str("abcdef", 3) == "abc"


@pytest.mark.unit
def test_opt_str_accepts_non_string_values():
    assert opt_str(42) == "42"


# ── ops layer: alerts ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_alert_without_severity_label_reports_null():
    """An alert whose label-set carries no 'severity' must not read as ''."""
    conn = _prom({"status": "success", "data": {"alerts": [
        {"labels": {"alertname": "Unlabelled"}, "state": "firing"},
    ]}})
    alert = alerts_ops.pull_alerts(conn)[0]
    assert alert["alertname"] == "Unlabelled"
    assert alert["severity"] is None, "a missing severity label is not an empty severity"
    assert alert["value"] is None


@pytest.mark.unit
def test_alert_with_empty_severity_keeps_the_empty_string():
    """An explicitly empty upstream label is preserved as '' — not turned into null."""
    conn = _prom({"status": "success", "data": {"alerts": [
        {"labels": {"alertname": "Blank", "severity": ""}, "state": "firing"},
    ]}})
    assert alerts_ops.pull_alerts(conn)[0]["severity"] == ""


@pytest.mark.unit
def test_alert_rows_never_drop_the_key_itself():
    """Keys are always present; only their value may be null.

    Omitting a key entirely is worse than a null — the consumer cannot tell the
    field was even considered.
    """
    conn = _prom({"status": "success", "data": {"alerts": [{}]}})
    row = alerts_ops.pull_alerts(conn)[0]
    for key in ("alertname", "severity", "state", "activeAt", "value", "labels"):
        assert key in row, f"{key} must be present even when the source omitted it"


@pytest.mark.unit
def test_silence_without_comment_reports_null():
    conn = MagicMock(name="conn")
    conn.target.platform = "prometheus"
    conn.am_get.return_value = [{"id": "sil-1", "status": {"state": "active"}}]
    sil = alerts_ops.list_silences(conn)["silences"][0]
    assert sil["id"] == "sil-1"
    assert sil["comment"] is None and sil["createdBy"] is None


# ── ops layer: scrape targets + rules ────────────────────────────────────────


@pytest.mark.unit
def test_target_that_never_errored_reports_null_last_error():
    conn = _prom({"status": "success", "data": {"activeTargets": [
        {"labels": {"job": "api", "instance": "a:9100"}, "health": "up"},
    ]}})
    row = targets_ops.list_targets(conn)["targets"][0]
    assert row["job"] == "api"
    assert row["lastError"] is None, "never-errored is not the same as errored-with-''"
    assert row["lastScrape"] is None and row["scrapePool"] is None


@pytest.mark.unit
def test_recording_rule_without_state_reports_null():
    """Recording rules have no alert state — that absence must survive."""
    conn = _prom({"status": "success", "data": {"groups": [
        {"name": "g", "file": "/r.yml", "rules": [
            {"name": "job:up:sum", "type": "recording", "query": "sum(up)",
             "health": "ok"},
        ]},
    ]}})
    rule = rules_ops.list_rules(conn, "recording")["rules"][0]
    assert rule["name"] == "job:up:sum"
    assert rule["state"] is None and rule["lastError"] is None


# ── consumers must tolerate the null ─────────────────────────────────────────


@pytest.mark.unit
def test_firing_alert_rca_handles_null_severity_and_annotations():
    """The RCA groups by severity and reads annotations — neither may crash on None."""
    alerts = [{"alertname": "NoSev", "severity": None, "labels": {}, "annotations": {}}]
    out = an.firing_alert_rca(alerts, rules=[])
    entry = out["rootCauses"][0]
    assert entry["severity"] == "none", "a null severity buckets as 'none', not a crash"
    assert entry["summary"] is None and entry["runbookUrl"] is None
    assert out["bySeverity"] == {"none": 1}


@pytest.mark.unit
def test_scrape_health_analysis_handles_null_last_error():
    """A down target with no lastError must still classify, not raise."""
    out = an.target_scrape_health_analysis(
        [{"job": "api", "instance": "a:9100", "health": "down", "lastError": None}]
    )
    down = out["downTargets"][0]
    assert down["lastError"] is None
    assert down["cause"] and down["action"], "classification must still be produced"


@pytest.mark.unit
def test_alert_noise_analysis_handles_null_severity():
    """Severities are sorted — a None in the set would break the comparison."""
    alerts = [
        {"alertname": "Flappy", "severity": None, "labels": {"instance": "a"}},
        {"alertname": "Flappy", "severity": "warning", "labels": {"instance": "b"}},
    ]
    out = an.alert_noise_and_flap_analysis(alerts, noise_threshold=2)
    assert out["noisyGroups"] == 1
    assert out["recommendations"][0]["severities"] == ["none", "warning"]


@pytest.mark.unit
def test_rows_with_null_fields_survive_json_serialisation():
    """Nulls must round-trip as JSON null — that is how the CLI emits them."""
    conn = _prom({"status": "success", "data": {"alerts": [
        {"labels": {"alertname": "NoSev"}, "state": "firing"},
    ]}})
    payload = json.loads(json.dumps(alerts_ops.firing_alerts(conn)))
    assert payload["alerts"][0]["severity"] is None


@pytest.mark.unit
def test_cli_renders_rows_with_null_fields(monkeypatch):
    """The CLI must survive a null field rather than crashing on render."""
    import observability_aiops.cli.alert as alert_cli

    conn = _prom({"status": "success", "data": {"alerts": [
        {"labels": {"alertname": "NoSev"}, "state": "firing"},
    ]}})
    monkeypatch.setattr(alert_cli, "get_connection", lambda target=None: (conn, object()))

    result = runner.invoke(app, ["alert", "firing"])
    assert result.exit_code == 0, result.output
    assert "NoSev" in result.output
