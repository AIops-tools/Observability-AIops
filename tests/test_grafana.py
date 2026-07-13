"""Unit tests for the Grafana read ops + MCP tools."""

from unittest.mock import MagicMock

import pytest

from observability_aiops.ops import grafana as ops


def _graf(return_value):
    conn = MagicMock(name="conn")
    conn.target.platform = "grafana"
    conn.graf_get.return_value = return_value
    return conn


@pytest.mark.unit
def test_list_dashboards_normalizes_search():
    conn = _graf([
        {"uid": "abc", "title": "API", "type": "dash-db", "folderTitle": "Prod",
         "tags": ["api"], "url": "/d/abc"},
    ])
    out = ops.list_dashboards(conn)
    assert out["total"] == 1 and out["dashboards"][0]["uid"] == "abc"


@pytest.mark.unit
def test_get_dashboard_summarizes_model():
    conn = _graf({
        "dashboard": {"uid": "abc", "title": "API", "version": 4,
                      "panels": [{}, {}], "tags": ["api"]},
        "meta": {"folderTitle": "Prod", "isStarred": True},
    })
    out = ops.get_dashboard(conn, "abc")
    assert out["title"] == "API" and out["version"] == 4
    assert out["panelCount"] == 2 and out["folderTitle"] == "Prod"


@pytest.mark.unit
def test_datasource_health_shape():
    conn = _graf({"status": "OK", "message": "1.0"})
    out = ops.datasource_health(conn, 3)
    assert out["datasourceId"] == 3 and out["status"] == "OK"


@pytest.mark.unit
def test_list_datasources_and_folders():
    conn = _graf([{"id": 1, "uid": "p", "name": "Prom", "type": "prometheus",
                   "isDefault": True}])
    assert ops.list_datasources(conn)["datasources"][0]["isDefault"] is True
    conn.graf_get.return_value = [{"uid": "f1", "title": "Prod"}]
    assert ops.list_folders(conn)["folders"][0]["title"] == "Prod"


@pytest.mark.unit
def test_grafana_tools_governed_low():
    from mcp_server.tools import grafana

    for fn in (grafana.list_dashboards, grafana.get_dashboard, grafana.list_datasources,
               grafana.datasource_health, grafana.list_folders):
        assert fn._risk_level == "low"
        assert getattr(fn, "_is_governed_tool", False)
