"""Prometheus metrics reads: outbound endpoint/params, sample normalization,
percent-encoding of hostile label names, and resilient error envelopes.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from observability_aiops.ops import metrics as ops


def _conn(payload):
    conn = MagicMock(name="conn")
    conn.target.platform = "prometheus"
    conn.prom_get.return_value = payload
    return conn


@pytest.mark.unit
def test_instant_query_endpoint_params_and_sample_shape():
    conn = _conn({
        "status": "success",
        "data": {"resultType": "vector", "result": [
            {"metric": {"__name__": "up", "job": "api"}, "value": [1700000000.0, "1"]},
            "not-a-dict",  # skipped
        ]},
    })
    out = ops.instant_query(conn, "up", time="1700000000")
    path, params = conn.prom_get.call_args[0]
    assert path == "/api/v1/query"
    assert params == {"query": "up", "time": "1700000000"}
    assert out["resultType"] == "vector"
    assert out["series"] == 1
    sample = out["samples"][0]
    assert sample["metric"]["__name__"] == "up"
    assert sample["timestamp"] == 1700000000.0
    assert sample["value"] == 1.0


@pytest.mark.unit
def test_range_query_normalizes_points_and_passes_step():
    conn = _conn({
        "status": "success",
        "data": {"resultType": "matrix", "result": [
            {"metric": {"job": "api"}, "values": [[1700000000, "0.5"], [1700000060, "0.7"]]},
        ]},
    })
    out = ops.range_query(conn, "rate(x[5m])", "s", "e", step="30s")
    _, params = conn.prom_get.call_args[0]
    assert params == {"query": "rate(x[5m])", "start": "s", "end": "e", "step": "30s"}
    pts = out["results"][0]["points"]
    assert pts[0] == {"timestamp": 1700000000.0, "value": 0.5}
    assert out["series"] == 1


@pytest.mark.unit
def test_label_values_percent_encodes_hostile_label_name():
    conn = _conn({"status": "success", "data": ["a", "b", 42]})
    out = ops.label_values(conn, "weird/../name")
    path = conn.prom_get.call_args[0][0]
    assert "%2F" in path and "/api/v1/label/" in path and "/values" in path
    # non-string values are filtered out
    assert out["total"] == 2 and out["values"] == ["a", "b"]


@pytest.mark.unit
def test_label_values_passes_match_selector():
    conn = _conn({"status": "success", "data": ["up"]})
    ops.label_values(conn, "__name__", match='{job="api"}')
    _, params = conn.prom_get.call_args[0]
    assert params == {"match[]": '{job="api"}'}


@pytest.mark.unit
def test_series_metadata_endpoint_and_rows():
    conn = _conn({"status": "success", "data": [
        {"__name__": "up", "job": "api"}, {"__name__": "up", "job": "db"},
    ]})
    out = ops.series_metadata(conn, '{__name__="up"}', start="s", end="e")
    path, params = conn.prom_get.call_args[0]
    assert path == "/api/v1/series"
    assert params["match[]"] == '{__name__="up"}'
    assert params["start"] == "s" and params["end"] == "e"
    assert out["total"] == 2


@pytest.mark.unit
def test_error_surfaces_as_envelope_not_raise():
    conn = MagicMock(name="conn")
    conn.prom_get.side_effect = RuntimeError("connection reset")
    out = ops.instant_query(conn, "up")
    assert "error" in out and out["query"] == "up"
    # a Prometheus status=error envelope is unwrapped into an error too
    conn2 = _conn({"status": "error", "error": "bad promql"})
    out2 = ops.range_query(conn2, "bad(", "s", "e")
    assert "error" in out2 and "bad promql" in out2["error"]
