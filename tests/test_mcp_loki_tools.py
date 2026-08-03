"""MCP Loki tools: the flagship log analyses and the alert->log cross-signal.

``_get_connection`` and the Prometheus alert pull are patched at the tool
module's namespace so the governed tool bodies run end-to-end against canned
Loki/Prometheus telemetry — no real backend and no network.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mcp_server.tools import loki as t


def _loki_conn(query_payload):
    conn = MagicMock(name="loki")
    conn.target.platform = "loki"
    conn.loki_get.return_value = query_payload
    return conn


def _streams(*entries):
    """Build a Loki query_range streams payload from (labels, count) entries."""
    result = []
    for labels, count in entries:
        values = [[str(1700000000000000000 + i), f"err {i}"] for i in range(count)]
        result.append({"stream": labels, "values": values})
    return {"status": "success", "data": {"resultType": "streams", "result": result}}


def _counts(*entries):
    """Build a Loki instant-vector payload from (labels, count) entries.

    Each burst-RCA window now issues TWO reads: ``count_over_time`` for the exact
    per-stream count, then a bounded line query only for sample lines. Counting
    the rows of the bounded query saturated at the line limit and hid every
    large burst.
    """
    result = [{"metric": labels, "value": [1700000000, str(count)]}
              for labels, count in entries]
    return {"status": "success", "data": {"resultType": "vector", "result": result}}


@pytest.mark.unit
def test_log_error_burst_rca_runs_current_vs_baseline(monkeypatch):
    # Current window bursts; baseline is quiet. Each window: counts, then lines.
    conn = MagicMock(name="loki")
    conn.target.platform = "loki"
    conn.loki_get.side_effect = [
        _counts(({"app": "api"}, 30)), _streams(({"app": "api"}, 30)),
        _counts(({"app": "api"}, 1)), _streams(({"app": "api"}, 1)),
    ]
    monkeypatch.setattr(t, "_get_connection", lambda target=None: conn)

    out = t.log_error_burst_rca('{app="api"}', hours=1.0)
    assert out["burstCount"] == 1
    assert out["bursts"][0]["app"] == "api"
    # two windows x (exact count + bounded sample lines)
    assert conn.loki_get.call_count == 4


@pytest.mark.unit
def test_log_volume_analysis_ranks_and_hints(monkeypatch):
    payload = _streams(({"app": "api", "trace_id": "t1"}, 5), ({"app": "db"}, 2))
    conn = _loki_conn(payload)
    # index_stats issues a second loki_get; give it a stats-shaped reply
    conn.loki_get.side_effect = [payload, {"status": "success", "data": {"bytes": 1024}}]
    monkeypatch.setattr(t, "_get_connection", lambda target=None: conn)

    out = t.log_volume_analysis('{app="api"}', hours=1.0)
    assert "topStreams" in out
    assert out["topStreams"][0]["count"] == 5


@pytest.mark.unit
def test_log_volume_analysis_propagates_query_error(monkeypatch):
    conn = _loki_conn({"status": "error", "error": "parse fail"})
    monkeypatch.setattr(t, "_get_connection", lambda target=None: conn)
    out = t.log_volume_analysis('{app="api"}')
    assert "error" in out and "parse fail" in out["error"]


@pytest.mark.unit
def test_alert_log_context_no_matching_alert(monkeypatch):
    monkeypatch.setattr(t.alerts_ops, "pull_alerts", lambda conn, state=None: [])
    monkeypatch.setattr(t, "_get_connection", lambda target=None: MagicMock())
    out = t.alert_log_context("HighLatency")
    assert "error" in out and "HighLatency" in out["error"]


@pytest.mark.unit
def test_alert_log_context_no_correlatable_labels(monkeypatch):
    firing = [{"alertname": "DiskFull", "labels": {"severity": "critical"}}]
    monkeypatch.setattr(t.alerts_ops, "pull_alerts", lambda conn, state=None: firing)
    monkeypatch.setattr(t, "_get_connection", lambda target=None: MagicMock())
    out = t.alert_log_context("DiskFull")
    assert out["lokiSelector"] is None
    assert out["streams"] == 0
    assert "namespace" in out["note"]


@pytest.mark.unit
def test_alert_log_context_correlates_labels_to_selector(monkeypatch):
    firing = [{
        "alertname": "ApiErrors",
        "labels": {"namespace": "prod", "app": "api", "severity": "warning"},
    }]
    monkeypatch.setattr(t.alerts_ops, "pull_alerts", lambda conn, state=None: firing)
    loki = _loki_conn(_streams(({"namespace": "prod", "app": "api"}, 3)))

    def _fake_conn(target=None):
        # prom pull happens first (MagicMock ok), loki read second
        return loki

    monkeypatch.setattr(t, "_get_connection", _fake_conn)
    out = t.alert_log_context("ApiErrors")
    assert out["alertname"] == "ApiErrors"
    assert out["matchedLabels"] == {"namespace": "prod", "app": "api"}
    sel = out["lokiSelector"]
    assert 'namespace="prod"' in sel and 'app="api"' in sel


@pytest.mark.unit
def test_loki_tools_all_governed_low():
    for fn in (t.loki_labels, t.loki_label_values, t.loki_query, t.loki_tail_errors,
               t.log_error_burst_rca, t.log_volume_analysis, t.alert_log_context):
        assert fn._risk_level == "low"
        assert getattr(fn, "_is_governed_tool", False)
