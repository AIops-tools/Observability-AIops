"""A truncated result announces itself.

A bare list cannot say "there is more" — the consumer has to infer it from the
length happening to equal the limit, and a smaller model faced with a long
result set tends to report that nothing came back at all. Every bounded read
therefore returns ``returned`` / ``limit`` / ``truncated``, and ``truncated`` is
*measured* (one extra row is fetched) rather than guessed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from observability_aiops.ops import loki as lk
from observability_aiops.ops import metrics as mx


def _prom(payload):
    conn = MagicMock(name="conn")
    conn.target.platform = "prometheus"
    conn.prom_get.return_value = payload
    return conn


def _loki(payload):
    conn = MagicMock(name="conn")
    conn.target.platform = "loki"
    conn.loki_get.return_value = payload
    return conn


def _streams(n_lines: int) -> dict:
    values = [[str(1_700_000_000 + i), f"line {i}"] for i in range(n_lines)]
    return {"status": "success", "data": {
        "resultType": "streams",
        "result": [{"stream": {"app": "api"}, "values": values}],
    }}


# ── Loki ─────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_loki_query_reports_untruncated_result():
    conn = _loki(_streams(3))
    out = lk.loki_query(conn, '{app="api"}', limit=10)
    assert out["returned"] == 3
    assert out["limit"] == 10
    assert out["truncated"] is False


@pytest.mark.unit
def test_loki_query_measures_truncation_with_a_probe_line():
    """Loki returns limit+1 lines; exactly `limit` come back, flagged truncated."""
    conn = _loki(_streams(6))  # probe fetched 6 for a limit of 5
    out = lk.loki_query(conn, '{app="api"}', limit=5)
    assert out["truncated"] is True
    assert out["returned"] == 5, "only `limit` rows are returned; the probe is dropped"
    assert out["limit"] == 5


@pytest.mark.unit
def test_loki_query_requests_one_extra_line():
    """The probe is what makes truncation measured rather than guessed."""
    conn = _loki(_streams(2))
    lk.loki_query(conn, '{app="api"}', limit=5)
    params = conn.loki_get.call_args[0][1]
    assert params["limit"] == "6", "one line beyond the limit must be requested"


@pytest.mark.unit
def test_loki_query_exactly_at_the_limit_is_not_truncated():
    """A length coincidence must not be reported as truncation."""
    conn = _loki(_streams(5))
    out = lk.loki_query(conn, '{app="api"}', limit=5)
    assert out["returned"] == 5 and out["truncated"] is False


@pytest.mark.unit
def test_loki_tail_errors_carries_the_envelope():
    conn = _loki(_streams(4))
    out = lk.loki_tail_errors(conn, '{app="api"}', limit=3)
    assert out["returned"] == 3 and out["limit"] == 3 and out["truncated"] is True


@pytest.mark.unit
def test_trim_entries_does_not_mutate_the_upstream_payload():
    data = {"resultType": "streams",
            "result": [{"stream": {"app": "api"}, "values": [["1", "a"], ["2", "b"]]}]}
    trimmed = lk.trim_entries(data, 1)
    assert lk.count_entries(trimmed) == 1
    assert lk.count_entries(data) == 2, "the original payload must be untouched"


@pytest.mark.unit
def test_loki_label_values_announce_truncation():
    conn = _loki({"status": "success",
                  "data": [f"v{i}" for i in range(lk.MAX_STREAMS + 5)]})
    out = lk.loki_label_values(conn, "app")
    assert out["total"] == lk.MAX_STREAMS + 5
    assert out["returned"] == lk.MAX_STREAMS
    assert out["truncated"] is True


# ── Prometheus / PromQL ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_instant_query_reports_untruncated_result():
    conn = _prom({"status": "success", "data": {"resultType": "vector", "result": [
        {"metric": {"job": "api"}, "value": [1, "1"]},
    ]}})
    out = mx.instant_query(conn, "up")
    assert out["returned"] == 1 and out["truncated"] is False
    assert out["limit"] == mx._MAX_SERIES


@pytest.mark.unit
def test_instant_query_announces_series_truncation():
    """A PromQL result wider than the series cap must not silently shrink."""
    result = [{"metric": {"i": str(i)}, "value": [1, "1"]}
              for i in range(mx._MAX_SERIES + 10)]
    conn = _prom({"status": "success",
                  "data": {"resultType": "vector", "result": result}})
    out = mx.instant_query(conn, "up")
    assert out["truncated"] is True
    assert out["returned"] == mx._MAX_SERIES
    assert len(out["samples"]) == mx._MAX_SERIES


@pytest.mark.unit
def test_range_query_announces_series_truncation():
    result = [{"metric": {"i": str(i)}, "values": [[1, "1"]]}
              for i in range(mx._MAX_SERIES + 3)]
    conn = _prom({"status": "success",
                  "data": {"resultType": "matrix", "result": result}})
    out = mx.range_query(conn, "up", "0", "1")
    assert out["truncated"] is True and out["returned"] == mx._MAX_SERIES


@pytest.mark.unit
def test_label_values_announce_truncation():
    conn = _prom({"status": "success",
                  "data": [f"m{i}" for i in range(mx._MAX_SERIES + 2)]})
    out = mx.label_values(conn, "__name__")
    assert out["total"] == mx._MAX_SERIES + 2
    assert out["returned"] == mx._MAX_SERIES and out["truncated"] is True


@pytest.mark.unit
def test_series_metadata_announces_truncation():
    conn = _prom({"status": "success",
                  "data": [{"__name__": f"m{i}"} for i in range(mx._MAX_SERIES + 1)]})
    out = mx.series_metadata(conn, "{job='api'}")
    assert out["returned"] == mx._MAX_SERIES and out["truncated"] is True


# ── undo token listing ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_undo_list_measures_truncation(monkeypatch):
    from mcp_server.tools import undo as undo_tools

    rows = [{"undo_id": f"u{i}", "ts": i, "tool": "create_silence",
             "undo_tool": "expire_silence", "note": ""} for i in range(4)]

    class _Store:
        def list(self, status, limit):
            return rows[:limit]

    monkeypatch.setattr(undo_tools, "get_undo_store", lambda: _Store())
    out = undo_tools.undo_list(limit=3)
    assert out["returned"] == 3 and out["limit"] == 3 and out["truncated"] is True
    assert len(out["undos"]) == 3

    out = undo_tools.undo_list(limit=10)
    assert out["returned"] == 4 and out["truncated"] is False
