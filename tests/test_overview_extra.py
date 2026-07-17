"""Platform-aware overview dispatch + partial-failure degradation.

The sub-reads are stubbed at the ops boundary so the test targets the overview
module's own dispatch, key mapping, and ``errors`` aggregation logic.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from observability_aiops.ops import overview as ov


def _conn(platform):
    conn = MagicMock(name="conn")
    conn.target.platform = platform
    conn.target.name = f"{platform}1"
    return conn


@pytest.mark.unit
def test_prometheus_overview_maps_all_subreads(monkeypatch):
    monkeypatch.setattr(ov.al, "firing_alerts", lambda c: {"total": 3})
    monkeypatch.setattr(ov.tg, "target_scrape_health", lambda c: {"up": 9, "down": 1})
    monkeypatch.setattr(ov.ru, "rule_health", lambda c: {"erroring": 2})
    out = ov.observability_overview(_conn("prometheus"))
    assert out["platform"] == "prometheus"
    assert out["target"] == "prometheus1"
    assert out["firingAlerts"] == 3
    assert out["targetsUp"] == 9 and out["targetsDown"] == 1
    assert out["rulesErroring"] == 2
    assert out["errors"] == []


@pytest.mark.unit
def test_prometheus_overview_degrades_on_subread_error(monkeypatch):
    monkeypatch.setattr(ov.al, "firing_alerts", lambda c: {"error": "am down"})
    monkeypatch.setattr(ov.tg, "target_scrape_health", lambda c: {"up": 4, "down": 0})
    monkeypatch.setattr(ov.ru, "rule_health", lambda c: {"error": "rules 500"})
    out = ov.observability_overview(_conn("prometheus"))
    # failing sub-calls degrade to None fields + an errors list, never raise
    assert out["firingAlerts"] is None
    assert out["targetsUp"] == 4
    assert out["rulesErroring"] is None
    assert any("alerts: am down" in e for e in out["errors"])
    assert any("rules: rules 500" in e for e in out["errors"])


@pytest.mark.unit
def test_grafana_overview_counts(monkeypatch):
    monkeypatch.setattr(ov.gf, "list_dashboards", lambda c: {"total": 12})
    monkeypatch.setattr(ov.gf, "list_datasources", lambda c: {"total": 4})
    monkeypatch.setattr(ov.gf, "list_folders", lambda c: {"error": "boom"})
    out = ov.observability_overview(_conn("grafana"))
    assert out["dashboards"] == 12 and out["datasources"] == 4
    assert out["folders"] is None
    assert out["errors"] == ["folders: boom"]


@pytest.mark.unit
def test_loki_overview_label_count(monkeypatch):
    monkeypatch.setattr(ov.lk, "loki_labels", lambda c: {"total": 7})
    out = ov.observability_overview(_conn("loki"))
    assert out["platform"] == "loki"
    assert out["labelNames"] == 7
    assert out["errors"] == []
