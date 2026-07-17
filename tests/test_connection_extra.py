"""Connection-layer tests: teaching errors, absolute Alertmanager URLs, the
platform guards on every helper, response normalization, and the
ConnectionManager session cache.

No real Prometheus/Grafana/Loki is contacted — a recording fake client stands in
for httpx.Client and captures the exact (method, path, kwargs) sent outbound.
"""

from __future__ import annotations

import httpx
import pytest

from observability_aiops.config import AppConfig, TargetConfig
from observability_aiops.connection import (
    ConnectionManager,
    ObservabilityApiError,
    ObservabilityConnection,
)


class _Resp:
    def __init__(self, status=200, payload=None, content=b"{}", text="body"):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.content = content
        self.text = text

    def json(self):
        if self._payload is _RAISE:
            raise ValueError("not json")
        return self._payload


_RAISE = object()


@pytest.fixture(autouse=True)
def _grafana_token(monkeypatch):
    """Grafana requires a token; supply one via the legacy env fallback so a real
    ObservabilityConnection can be constructed for the guard/manager tests."""
    monkeypatch.setenv("OBSERVABILITY_GRAF1_TOKEN", "svc-token")


class _RecordingClient:
    """Captures each outbound request and replays a canned response."""

    def __init__(self, resp=None, raise_exc=None):
        self._resp = resp or _Resp()
        self._raise = raise_exc
        self.calls: list[tuple] = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if self._raise is not None:
            raise self._raise
        return self._resp

    def close(self):
        pass


def _prom(client):
    return ObservabilityConnection(
        TargetConfig(name="prom1", platform="prometheus", host="prom.local"), client=client
    )


def _graf(client):
    return ObservabilityConnection(
        TargetConfig(name="graf1", platform="grafana", host="graf.local"), client=client
    )


# ── teaching messages per status class ───────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "status,needle",
    [
        (401, "Authentication failed"),
        (403, "Authentication failed"),
        (404, "Not found"),
        (400, "Bad request"),
        (422, "Bad request"),
        (500, "server error"),
        (503, "server error"),
        (418, "API error"),
    ],
)
def test_teaching_message_by_status(status, needle):
    client = _RecordingClient(_Resp(status=status, text="details-here"))
    conn = _prom(client)
    with pytest.raises(ObservabilityApiError) as ei:
        conn.prom_get("/api/v1/query", {"query": "up"})
    assert needle in str(ei.value)
    assert ei.value.status_code == status
    assert ei.value.path == "/api/v1/query"
    # the server snippet is carried through for context
    assert "details-here" in str(ei.value)


@pytest.mark.unit
def test_transport_error_wrapped_as_teaching_error():
    client = _RecordingClient(raise_exc=httpx.ConnectError("refused"))
    conn = _prom(client)
    with pytest.raises(ObservabilityApiError) as ei:
        conn.prom_get("/api/v1/status/buildinfo")
    msg = str(ei.value)
    assert "Could not reach prometheus" in msg and "reachability" in msg


@pytest.mark.unit
def test_empty_body_and_non_json_both_return_empty_dict():
    empty = _prom(_RecordingClient(_Resp(content=b"")))
    assert empty.prom_get("/api/v1/query", {"query": "up"}) == {}

    nonjson = _prom(_RecordingClient(_Resp(payload=_RAISE, content=b"<html>")))
    assert nonjson.prom_get("/api/v1/query", {"query": "up"}) == {}


# ── Alertmanager helpers use an absolute base URL, own verbs ──────────────────


@pytest.mark.unit
def test_am_get_post_delete_use_alertmanager_base():
    client = _RecordingClient(_Resp(payload={"ok": True}))
    conn = _prom(client)
    conn.am_get("/api/v2/silences")
    conn.am_post("/api/v2/silences", json={"x": 1})
    conn.am_delete("/api/v2/silence/abc")
    methods = [c[0] for c in client.calls]
    urls = [c[1] for c in client.calls]
    assert methods == ["GET", "POST", "DELETE"]
    # default co-located Alertmanager on :9093
    assert all(u.startswith("http://prom.local:9093/api/v2/") for u in urls)
    assert client.calls[1][2]["json"] == {"x": 1}


@pytest.mark.unit
def test_prom_reload_posts_lifecycle_endpoint():
    client = _RecordingClient(_Resp(content=b""))
    conn = _prom(client)
    conn.prom_reload()
    assert client.calls[0][0] == "POST" and client.calls[0][1] == "/-/reload"


@pytest.mark.unit
def test_grafana_verbs_hit_api_paths():
    client = _RecordingClient(_Resp(payload={"id": 7}))
    conn = _graf(client)
    conn.graf_get("/api/search", {"type": "dash-db"})
    conn.graf_post("/api/dashboards/db", json={"dashboard": {}})
    conn.graf_delete("/api/dashboards/uid/abc")
    assert [c[0] for c in client.calls] == ["GET", "POST", "DELETE"]
    assert client.calls[0][2]["params"] == {"type": "dash-db"}


# ── platform guards: every helper refuses the wrong platform ──────────────────


@pytest.mark.unit
def test_platform_guards_reject_cross_platform_calls():
    prom = _prom(_RecordingClient())
    graf = _graf(_RecordingClient())
    loki = ObservabilityConnection(
        TargetConfig(name="loki1", platform="loki", host="loki.local"),
        client=_RecordingClient(_Resp(payload={"status": "success", "data": []})),
    )
    with pytest.raises(ObservabilityApiError):
        prom.graf_get("/api/health")
    with pytest.raises(ObservabilityApiError):
        prom.loki_get("/ready")
    with pytest.raises(ObservabilityApiError):
        graf.prom_get("/api/v1/query")
    with pytest.raises(ObservabilityApiError):
        graf.am_get("/api/v2/silences")
    with pytest.raises(ObservabilityApiError):
        loki.graf_get("/api/health")
    # loki_get is fine against a loki target
    assert loki.loki_get("/ready") == {"status": "success", "data": []}


@pytest.mark.unit
def test_bearer_header_set_from_secret(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_GRAF1_TOKEN", "svc-token")
    conn = ObservabilityConnection(
        TargetConfig(name="graf1", platform="grafana", host="graf.local")
    )
    assert conn._client.headers["Authorization"] == "Bearer svc-token"
    conn.close()


# ── ConnectionManager: caching + lifecycle ───────────────────────────────────


def _cfg():
    return AppConfig(
        targets=(
            TargetConfig(name="prom1", platform="prometheus", host="a"),
            TargetConfig(name="graf1", platform="grafana", host="b"),
        )
    )


@pytest.mark.unit
def test_manager_connect_caches_and_defaults():
    mgr = ConnectionManager(_cfg())
    first = mgr.connect()  # default = first target
    again = mgr.connect("prom1")
    assert first is again  # same session reused
    assert first.target.name == "prom1"
    graf = mgr.connect("graf1")
    assert graf is not first
    assert set(mgr.list_targets()) == {"prom1", "graf1"}
    assert set(mgr.list_connected()) == {"prom1", "graf1"}


@pytest.mark.unit
def test_manager_disconnect_and_disconnect_all():
    mgr = ConnectionManager(_cfg())
    mgr.connect("prom1")
    mgr.connect("graf1")
    mgr.disconnect("prom1")
    assert mgr.list_connected() == ["graf1"]
    mgr.disconnect("nonexistent")  # no-op, must not raise
    mgr.disconnect_all()
    assert mgr.list_connected() == []


@pytest.mark.unit
def test_manager_from_config_uses_supplied_config():
    mgr = ConnectionManager.from_config(_cfg())
    assert mgr.connect().target.platform == "prometheus"
