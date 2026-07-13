"""Unit tests for the Prometheus metrics ops + MCP tools."""

from unittest.mock import MagicMock

import pytest

from observability_aiops.ops import metrics as ops


def _prom(payload):
    conn = MagicMock(name="conn")
    conn.target.platform = "prometheus"
    conn.prom_get.return_value = payload
    return conn


@pytest.mark.unit
def test_instant_query_normalizes_vector():
    conn = _prom({
        "status": "success",
        "data": {"resultType": "vector", "result": [
            {"metric": {"__name__": "up", "job": "api"}, "value": [1720000000, "1"]},
            {"metric": {"__name__": "up", "job": "db"}, "value": [1720000000, "0"]},
        ]},
    })
    out = ops.instant_query(conn, "up")
    assert out["resultType"] == "vector" and out["series"] == 2
    assert out["samples"][0]["value"] == 1.0
    assert out["samples"][1]["metric"]["job"] == "db"


@pytest.mark.unit
def test_instant_query_surfaces_prometheus_error():
    conn = _prom({"status": "error", "error": "parse error: unexpected )"})
    out = ops.instant_query(conn, "up)")
    assert "error" in out and "parse error" in out["error"]


@pytest.mark.unit
def test_range_query_collects_points():
    conn = _prom({
        "status": "success",
        "data": {"resultType": "matrix", "result": [
            {"metric": {"job": "api"}, "values": [[1, "0.1"], [2, "0.2"]]},
        ]},
    })
    out = ops.range_query(conn, "rate(x[5m])", "1", "2", "1s")
    assert out["series"] == 1
    assert out["results"][0]["points"][1]["value"] == 0.2


@pytest.mark.unit
def test_label_values_filters_strings():
    conn = _prom({"status": "success", "data": ["up", "http_requests_total", 42]})
    out = ops.label_values(conn, "__name__")
    assert out["total"] == 2 and "up" in out["values"]


@pytest.mark.unit
def test_metrics_tools_are_governed_low():
    from mcp_server.tools import metrics

    for fn in (metrics.instant_query, metrics.range_query, metrics.label_values,
               metrics.series_metadata):
        assert fn._risk_level == "low"
        assert getattr(fn, "_is_governed_tool", False)
