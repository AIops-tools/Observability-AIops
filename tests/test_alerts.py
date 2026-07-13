"""Unit tests for the alert ops (Prometheus rule alerts + Alertmanager)."""

from unittest.mock import MagicMock

import pytest

from observability_aiops.ops import alerts as ops

_PROM_ALERTS = {
    "status": "success",
    "data": {"alerts": [
        {"labels": {"alertname": "TargetDown", "severity": "critical"},
         "annotations": {"summary": "db is down"}, "state": "firing", "value": "1"},
        {"labels": {"alertname": "HighLatency", "severity": "warning"},
         "annotations": {}, "state": "firing", "value": "2"},
        {"labels": {"alertname": "Warmup", "severity": "info"},
         "annotations": {}, "state": "pending", "value": "0"},
    ]},
}


def _prom(payload):
    conn = MagicMock(name="conn")
    conn.target.platform = "prometheus"
    conn.prom_get.return_value = payload
    return conn


@pytest.mark.unit
def test_firing_alerts_filters_and_groups_severity():
    out = ops.firing_alerts(_prom(_PROM_ALERTS))
    assert out["total"] == 2
    assert out["bySeverity"]["critical"] == 1 and out["bySeverity"]["warning"] == 1


@pytest.mark.unit
def test_pending_alerts_filters_state():
    out = ops.pending_alerts(_prom(_PROM_ALERTS))
    assert out["total"] == 1 and out["alerts"][0]["alertname"] == "Warmup"


@pytest.mark.unit
def test_pull_alerts_returns_all_when_unfiltered():
    conn = _prom(_PROM_ALERTS)
    assert len(ops.pull_alerts(conn)) == 3
    assert len(ops.pull_alerts(conn, state="firing")) == 2


@pytest.mark.unit
def test_alertmanager_alerts_normalizes():
    conn = MagicMock(name="conn")
    conn.target.platform = "prometheus"
    conn.am_get.return_value = [
        {"labels": {"alertname": "TargetDown", "severity": "critical"},
         "status": {"state": "active", "silencedBy": []},
         "fingerprint": "abc", "startsAt": "2026-07-13T00:00:00Z"},
    ]
    out = ops.alertmanager_alerts(conn)
    assert out["total"] == 1 and out["alerts"][0]["fingerprint"] == "abc"


@pytest.mark.unit
def test_list_silences_counts_active():
    conn = MagicMock(name="conn")
    conn.target.platform = "prometheus"
    conn.am_get.return_value = [
        {"id": "s1", "status": {"state": "active"},
         "matchers": [{"name": "alertname", "value": "TargetDown", "isRegex": False}],
         "createdBy": "op", "comment": "maint"},
        {"id": "s2", "status": {"state": "expired"}, "matchers": []},
    ]
    out = ops.list_silences(conn)
    assert out["total"] == 2 and out["active"] == 1
    assert out["silences"][0]["matchers"][0]["name"] == "alertname"


@pytest.mark.unit
def test_alert_tools_governed_low():
    from mcp_server.tools import alerts

    for fn in (alerts.firing_alerts, alerts.pending_alerts, alerts.alertmanager_alerts,
               alerts.list_silences):
        assert fn._risk_level == "low"
        assert getattr(fn, "_is_governed_tool", False)
