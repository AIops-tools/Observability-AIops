"""Prometheus status reads: config-hash never leaks the raw YAML, and the TSDB
head-cardinality normalization. Errors degrade to a partial envelope.
"""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock

import pytest

from observability_aiops.ops import prom_status as ps


def _conn(payload=None, exc=None):
    conn = MagicMock(name="conn")
    conn.target.platform = "prometheus"
    if exc is not None:
        conn.prom_get.side_effect = exc
    else:
        conn.prom_get.return_value = payload
    return conn


@pytest.mark.unit
def test_config_hash_matches_sha256_of_yaml():
    yaml_text = "global:\n  scrape_interval: 15s\n"
    conn = _conn({"status": "success", "data": {"yaml": yaml_text}})
    expected = hashlib.sha256(yaml_text.encode("utf-8")).hexdigest()
    assert ps.config_hash(conn) == expected


@pytest.mark.unit
def test_config_hash_best_effort_empty_on_error_or_missing():
    assert ps.config_hash(_conn(exc=RuntimeError("boom"))) == ""
    assert ps.config_hash(_conn({"status": "success", "data": {}})) == ""


@pytest.mark.unit
def test_config_status_reports_fingerprint_not_raw_yaml():
    yaml_text = "scrape_configs: []\n"
    out = ps.config_status(_conn({"status": "success", "data": {"yaml": yaml_text}}))
    assert out["configLoaded"] is True
    assert out["configBytes"] == len(yaml_text.encode("utf-8"))
    assert out["configHash"] == hashlib.sha256(yaml_text.encode("utf-8")).hexdigest()
    # the raw YAML (which can embed scrape credentials) is never returned
    assert "yaml" not in out and yaml_text not in str(out)


@pytest.mark.unit
def test_config_status_error_is_partial():
    out = ps.config_status(_conn(exc=RuntimeError("status 503")))
    assert "error" in out


@pytest.mark.unit
def test_tsdb_status_head_stats_and_top_series():
    conn = _conn({"status": "success", "data": {
        "headStats": {"numSeries": 12000, "numLabelPairs": 400, "chunkCount": 999},
        "seriesCountByMetricName": [
            {"name": "http_requests_total", "value": 5000},
            {"name": "node_cpu_seconds_total", "value": 3000},
        ],
    }})
    out = ps.tsdb_status(conn)
    assert out["numSeries"] == 12000
    assert out["numLabelPairs"] == 400
    assert out["chunkCount"] == 999
    assert out["topSeriesByMetric"][0] == {"metric": "http_requests_total", "series": 5000}


@pytest.mark.unit
def test_tsdb_status_error_is_partial():
    out = ps.tsdb_status(_conn(exc=RuntimeError("nope")))
    assert "error" in out
