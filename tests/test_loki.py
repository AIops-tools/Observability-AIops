"""Unit tests for the Grafana Loki read ops, log analyses, and cross-signal.

No real Loki is needed — the connection is a MagicMock and the analyses are pure
functions fed canned responses. Covers: the LogQL bounding gate, hostile
label-value escaping, RCA burst classification, volume/cardinality analysis,
multi-tenant + basic-auth headers, and the doctor Loki probe (healthy/broken).
"""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import pytest

from observability_aiops.config import AppConfig, TargetConfig
from observability_aiops.ops import log_analysis as la
from observability_aiops.ops import loki as ops


def _loki(payload):
    conn = MagicMock(name="conn")
    conn.target.platform = "loki"
    conn.loki_get.return_value = payload
    return conn


# ── bounding gate ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_query_rejected_without_stream_selector():
    conn = _loki({"status": "success", "data": {"resultType": "streams", "result": []}})
    out = ops.loki_query(conn, '|= "error"')
    assert "error" in out and "selector" in out["error"].lower()
    conn.loki_get.assert_not_called()  # gate refuses before any HTTP call


@pytest.mark.unit
def test_query_rejected_beyond_lookback_cap():
    conn = _loki({"status": "success", "data": {"result": []}})
    out = ops.loki_query(conn, '{app="api"}', hours=ops.MAX_LOOKBACK_HOURS + 100)
    assert "error" in out and "cap" in out["error"].lower()


@pytest.mark.unit
def test_line_limit_clamped_both_ends():
    assert ops._clamp_limit(10**9) == ops.MAX_LINE_LIMIT
    assert ops._clamp_limit(0) == 1
    assert ops._clamp_limit(-5) == 1
    assert ops._clamp_limit(50) == 50


@pytest.mark.unit
def test_empty_query_rejected():
    with pytest.raises(ops.LokiQueryError):
        ops.validate_logql("   ")


# ── hostile label-value escaping ─────────────────────────────────────────────


@pytest.mark.unit
def test_selector_from_pairs_escapes_hostile_value():
    # A value that tries to break out of the LogQL string + inject a filter.
    hostile = 'api"} |= "secret'
    sel = ops.selector_from_pairs([("app", hostile)])
    assert sel.startswith('{app="') and sel.endswith('"}')
    # The embedded quote is backslash-escaped, so it cannot terminate the string.
    assert '\\"' in sel
    assert '"} |= "secret' not in sel.replace('\\"', "")


@pytest.mark.unit
def test_build_selector_from_labels_priority_and_cap():
    labels = {
        "namespace": "prod", "job": "api", "service": "checkout", "app": "web",
        "container": "c1", "pod": "p1", "instance": "i1", "unrelated": "drop-me",
    }
    pairs = ops.build_selector_from_labels(labels, max_matchers=4)
    assert len(pairs) == 4
    keys = [k for k, _ in pairs]
    assert keys == ["namespace", "job", "service", "app"]  # priority order
    assert "unrelated" not in dict(pairs)


@pytest.mark.unit
def test_build_selector_from_labels_empty_when_no_correlatable():
    assert ops.build_selector_from_labels({"severity": "critical"}) == []


@pytest.mark.unit
def test_label_name_percent_encoded_in_path():
    conn = _loki({"status": "success", "data": ["v1"]})
    ops.loki_label_values(conn, "a/b")
    path = conn.loki_get.call_args[0][0]
    assert "%2F" in path and "/label/a%2Fb/values" in path


# ── happy-path reads ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_loki_labels_filters_strings():
    conn = _loki({"status": "success", "data": ["app", "job", 42]})
    out = ops.loki_labels(conn)
    assert out["total"] == 2 and "app" in out["labels"]


@pytest.mark.unit
def test_loki_query_summarizes_streams():
    conn = _loki({"status": "success", "data": {"resultType": "streams", "result": [
        {"stream": {"app": "api", "level": "error"},
         "values": [["1700000000000000000", "boom one"], ["1700000000000000001", "boom two"]]},
    ]}})
    out = ops.loki_query(conn, '{app="api"}')
    assert out["streams"] == 1
    st = out["results"][0]
    assert st["count"] == 2 and st["labels"]["app"] == "api"
    assert st["sampleLines"][0] == "boom one"


@pytest.mark.unit
def test_loki_tail_errors_builds_error_filter():
    conn = _loki({"status": "success", "data": {"resultType": "streams", "result": []}})
    out = ops.loki_tail_errors(conn, '{app="api"}')
    assert "|~" in out["query"] and "error" in out["query"].lower()
    # bare matchers are wrapped in braces
    assert ops.error_query('app="x"').startswith('{app="x"}')


@pytest.mark.unit
def test_loki_query_surfaces_backend_error():
    conn = _loki({"status": "error", "error": "parse error at line 1"})
    out = ops.loki_query(conn, '{app="api"}')
    assert "error" in out and "parse error" in out["error"]


# ── RCA burst classification (pure) ──────────────────────────────────────────


@pytest.mark.unit
def test_error_burst_rca_classifies_three_ways():
    current = [
        {"labels": {"app": "api"}, "count": 10, "sampleLines": ["null deref"]},
        {"labels": {"app": "db", "shard": "1"}, "count": 30},
        {"labels": {"app": "web", "instance": "pod-1"}, "count": 20},
        {"labels": {"app": "web", "instance": "pod-2"}, "count": 0},  # not bursting
    ]
    baseline = [
        {"labels": {"app": "db", "shard": "1"}, "count": 5},
    ]
    out = la.log_error_burst_rca(current, baseline)
    assert out["burstCount"] == 3
    by_app = {b["app"]: b for b in out["bursts"]}
    assert by_app["api"]["classification"] == la.CLASS_NEW_SIGNATURE
    assert by_app["db"]["classification"] == la.CLASS_VOLUME_SPIKE
    assert by_app["web"]["classification"] == la.CLASS_SINGLE_INSTANCE
    assert by_app["api"]["sampleLines"] == ["null deref"]
    # ranked worst-first by current error count
    assert out["bursts"][0]["currentErrors"] == 30


@pytest.mark.unit
def test_error_burst_rca_respects_ratio_and_min():
    # baseline 10, current 15 → below 3x ratio → not a burst
    current = [{"labels": {"app": "api"}, "count": 15}]
    baseline = [{"labels": {"app": "api"}, "count": 10}]
    out = la.log_error_burst_rca(current, baseline, burst_ratio=3.0)
    assert out["burstCount"] == 0


# ── volume / cardinality analysis (pure) ─────────────────────────────────────


@pytest.mark.unit
def test_volume_analysis_flags_high_cardinality():
    streams = [
        {"labels": {"app": "api", "trace_id": f"t{i}"}, "count": i}
        for i in range(5)
    ]
    out = la.log_volume_analysis(streams, high_cardinality_threshold=3)
    labels = {h["label"] for h in out["highCardinalityLabels"]}
    assert "trace_id" in labels and "app" not in labels
    assert out["topStreams"][0]["count"] == 4  # ranked by volume


@pytest.mark.unit
def test_volume_analysis_retention_hint_from_stats():
    streams = [{"labels": {"app": "api"}, "count": 3}]
    out = la.log_volume_analysis(streams, total_stats={"bytes": 5 * 1024 ** 3})
    assert "GiB" in out["retentionHint"]


# ── connection: tenant header + basic auth + platform guard ──────────────────


@pytest.mark.unit
def test_connection_loki_tenant_and_basic_auth(monkeypatch):
    from observability_aiops.connection import ObservabilityConnection

    monkeypatch.setenv("OBSERVABILITY_LOKI1_TOKEN", "user:secret")
    target = TargetConfig(
        name="loki1", platform="loki", host="loki.local",
        auth_type="basic", org_id="team-a",
    )
    conn = ObservabilityConnection(target)
    headers = conn._client.headers
    assert headers["X-Scope-OrgID"] == "team-a"
    assert headers["Authorization"].startswith("Basic ")
    decoded = base64.b64decode(headers["Authorization"].split()[1]).decode()
    assert decoded == "user:secret"
    conn.close()


@pytest.mark.unit
def test_connection_loki_get_and_platform_guard():
    from observability_aiops.connection import ObservabilityApiError, ObservabilityConnection

    target = TargetConfig(name="loki1", platform="loki", host="loki.local")

    class _Resp:
        status_code = 200
        content = b"{}"
        text = "ready"

        def json(self):
            return {"status": "success", "data": []}

    class _Client:
        def request(self, method, path, **k):
            return _Resp()

        def close(self):
            pass

    conn = ObservabilityConnection(target, client=_Client())
    assert conn.loki_get("/ready") == {"status": "success", "data": []}
    with pytest.raises(ObservabilityApiError):
        conn.prom_get("/api/v1/query", {"query": "up"})


# ── loki MCP tools are governed reads ────────────────────────────────────────


@pytest.mark.unit
def test_loki_tools_are_governed_low():
    from mcp_server.tools import loki as tools

    for fn in (tools.loki_labels, tools.loki_label_values, tools.loki_query,
               tools.loki_tail_errors, tools.log_error_burst_rca,
               tools.log_volume_analysis, tools.alert_log_context):
        assert fn._risk_level == "low"
        assert getattr(fn, "_is_governed_tool", False)


# ── doctor Loki probe (healthy / broken) ─────────────────────────────────────


class _FakeConn:
    def __init__(self, ok: bool) -> None:
        self._ok = ok

    def loki_get(self, path, params=None):
        if not self._ok:
            raise RuntimeError("connection refused")
        return {}


class _FakeMgr:
    def __init__(self, ok: bool) -> None:
        self._ok = ok

    def connect(self, name):  # noqa: ANN001
        return _FakeConn(self._ok)


def _patch_doctor(monkeypatch, tmp_path, ok: bool):
    import observability_aiops.connection as connmod
    from observability_aiops import doctor as doc

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("targets: []", "utf-8")
    target = TargetConfig(name="loki1", platform="loki", host="loki.local")
    monkeypatch.setattr(doc, "CONFIG_FILE", cfg_file)
    monkeypatch.setattr(doc, "ENV_FILE", tmp_path / "absent.env")
    monkeypatch.setattr(doc, "load_config", lambda: AppConfig(targets=(target,)))
    monkeypatch.setattr(doc, "has_store", lambda: False)
    monkeypatch.setattr(connmod, "ConnectionManager", lambda config: _FakeMgr(ok))
    return doc


@pytest.mark.unit
def test_doctor_loki_healthy(monkeypatch, tmp_path):
    doc = _patch_doctor(monkeypatch, tmp_path, ok=True)
    assert doc.run_doctor() == 0


@pytest.mark.unit
def test_doctor_loki_broken(monkeypatch, tmp_path):
    doc = _patch_doctor(monkeypatch, tmp_path, ok=False)
    assert doc.run_doctor() == 1


# ── burst counts come from Loki, not from counting capped lines ──────────────


@pytest.mark.unit
def test_error_streams_window_counts_beyond_the_line_limit():
    """Per-stream error counts must be exact at any volume.

    They used to be ``len(values)`` of a ``query_range`` bounded at 100 lines,
    so every busy stream reported exactly 100 and the burst comparison collapsed:
    a service going 25 → 485 errors read as 100 → 100, i.e. **no burst**, and so
    did a service that had been noisy all along. Verified against a live Loki
    3.0.0 — the same seeded 19x spike scores burstCount 0 before this fix and
    volume_spike after.
    """
    labels = {"app": "checkout", "level": "error"}
    counted = {"status": "success",
               "data": {"resultType": "vector",
                        "result": [{"metric": labels, "value": [1, "4821"]}]}}
    lines = {"status": "success",
             "data": {"resultType": "streams",
                      "result": [{"stream": labels,
                                  "values": [[str(i), f"boom {i}"] for i in range(100)]}]}}
    conn = MagicMock(name="conn")
    conn.target.platform = "loki"
    conn.loki_get.side_effect = [counted, lines]

    now = ops._now_ns()
    out = ops.error_streams_window(conn, '{app="checkout"}', now - 3600 * ops._NS_PER_SEC, now)

    assert out[0]["count"] == 4821  # not 100
    assert out[0]["sampleLines"]  # samples still attached from the line query
    counting_query = conn.loki_get.call_args_list[0][0][1]["query"]
    assert counting_query.startswith("count_over_time(")


@pytest.mark.unit
def test_error_streams_window_reports_a_stream_the_line_query_never_reached():
    """A stream crowded out of the bounded line query still gets its real count."""
    busy = {"app": "checkout", "level": "error"}
    quiet = {"app": "catalog", "level": "error"}
    counted = {"status": "success",
               "data": {"resultType": "vector",
                        "result": [{"metric": busy, "value": [1, "9000"]},
                                   {"metric": quiet, "value": [1, "7"]}]}}
    lines = {"status": "success",
             "data": {"resultType": "streams",
                      "result": [{"stream": busy,
                                  "values": [[str(i), "boom"] for i in range(100)]}]}}
    conn = MagicMock(name="conn")
    conn.target.platform = "loki"
    conn.loki_get.side_effect = [counted, lines]

    now = ops._now_ns()
    out = ops.error_streams_window(conn, '{env="prod"}', now - 3600 * ops._NS_PER_SEC, now)

    by_app = {st["labels"]["app"]: st for st in out}
    assert by_app["catalog"]["count"] == 7
    assert by_app["catalog"]["sampleLines"] == []  # honest: counted, never sampled
