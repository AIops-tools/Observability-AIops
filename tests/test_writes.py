"""Unit tests for the governed writes (silences, annotations, dashboards, reload).

Proves: writes capture the REAL before-state; update/delete dashboard stash the
prior model for undo; create_silence returns an id + inverts to expire; reload
records the prior config hash; risk tiers are correct; the high-risk delete has a
non-mutating dry_run; and the harness actually RECORDS an undo token for
update_dashboard (an end-to-end undo-recording test).
"""

from unittest.mock import MagicMock

import pytest

from observability_aiops.connection import ObservabilityApiError
from observability_aiops.ops import writes as ops


def _graf_conn(prior_dashboard):
    conn = MagicMock(name="conn")
    conn.target.platform = "grafana"
    conn.graf_get.return_value = {"dashboard": prior_dashboard, "meta": {}}
    conn.graf_post.return_value = {"status": "success"}
    conn.graf_delete.return_value = {"message": "deleted"}
    return conn


# ── silences ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_create_silence_builds_matchers_and_returns_id():
    conn = MagicMock(name="conn")
    conn.target.platform = "prometheus"
    conn.am_post.return_value = {"silenceID": "sil-1"}
    out = ops.create_silence(conn, [{"name": "alertname", "value": "TargetDown"}], minutes=30)
    assert out["action"] == "create_silence" and out["silenceId"] == "sil-1"
    body = conn.am_post.call_args.kwargs["json"]
    assert body["matchers"][0]["name"] == "alertname"
    assert body["startsAt"].endswith("Z") and body["endsAt"].endswith("Z")


@pytest.mark.unit
def test_create_silence_requires_matchers_and_positive_minutes():
    conn = MagicMock(name="conn")
    conn.target.platform = "prometheus"
    with pytest.raises(ValueError):
        ops.create_silence(conn, [], minutes=30)
    with pytest.raises(ValueError):
        ops.create_silence(conn, [{"name": "a", "value": "b"}], minutes=0)
    conn.am_post.assert_not_called()


# ── dashboards: prior-state capture ──────────────────────────────────────────


@pytest.mark.unit
def test_update_dashboard_captures_prior_json():
    prior = {"uid": "abc", "title": "Old", "version": 4}
    conn = _graf_conn(prior)
    out = ops.update_dashboard(conn, {"uid": "abc", "title": "New"})
    # prior model fetched BEFORE the write and stashed for undo
    conn.graf_get.assert_called_once_with("/api/dashboards/uid/abc")
    assert out["priorState"]["dashboard"] == prior
    conn.graf_post.assert_called_once()


@pytest.mark.unit
def test_update_dashboard_requires_uid():
    conn = _graf_conn({"uid": "x"})
    with pytest.raises(ValueError):
        ops.update_dashboard(conn, {"title": "no uid"})


@pytest.mark.unit
def test_delete_dashboard_captures_prior_before_delete():
    prior = {"uid": "abc", "title": "Doomed"}
    conn = _graf_conn(prior)
    out = ops.delete_dashboard(conn, "abc")
    conn.graf_get.assert_called_once()  # captured before delete
    conn.graf_delete.assert_called_once_with("/api/dashboards/uid/abc")
    assert out["priorState"]["dashboard"] == prior and out["title"] == "Doomed"


# ── dashboards: undo replay (update on a missing uid = re-create) ────────────


def _missing_dashboard_conn(status_code: int = 404):
    """A Grafana conn whose dashboard GET fails (the uid was just deleted)."""
    conn = MagicMock(name="conn")
    conn.target.platform = "grafana"
    conn.graf_get.side_effect = ObservabilityApiError(
        f"error ({status_code}) on /api/dashboards/uid/gone",
        status_code=status_code,
        path="/api/dashboards/uid/gone",
    )
    conn.graf_post.return_value = {"status": "success"}
    return conn


@pytest.mark.unit
def test_update_dashboard_on_missing_uid_proceeds_as_create():
    """Replaying a delete_dashboard undo hits update_dashboard with a uid that no
    longer exists — the prior-fetch 404 must not abort the re-create."""
    conn = _missing_dashboard_conn(404)
    model = {"uid": "gone", "title": "Recreated"}
    out = ops.update_dashboard(conn, model)
    assert out["action"] == "update_dashboard" and out["uid"] == "gone"
    assert out["priorState"]["dashboard"] is None  # create mode: nothing to restore
    # The POST actually re-creates the dashboard from the supplied model.
    path = conn.graf_post.call_args.args[0]
    body = conn.graf_post.call_args.kwargs["json"]
    assert path == "/api/dashboards/db"
    assert body == {"dashboard": model, "overwrite": True}


@pytest.mark.unit
def test_update_dashboard_non_404_fetch_error_still_raises():
    """Only not-found is tolerated on the prior-fetch — auth/server errors must
    still abort the write (no blind POST against a broken target)."""
    conn = _missing_dashboard_conn(500)
    with pytest.raises(ObservabilityApiError):
        ops.update_dashboard(conn, {"uid": "abc", "title": "X"})
    conn.graf_post.assert_not_called()


@pytest.mark.unit
def test_delete_dashboard_undo_cycle_replays_as_recreate(monkeypatch, tmp_path):
    """Full cycle: delete_dashboard records an update_dashboard undo descriptor
    carrying the captured model; replaying that descriptor after the delete
    (uid now 404s) succeeds and re-POSTs the exact captured model."""
    import json

    from mcp_server.tools import writes as t
    from observability_aiops.governance import undo as undo_mod

    store = undo_mod.UndoStore(tmp_path / "undo.db")
    monkeypatch.setattr(undo_mod, "_store", store)

    prior = {"uid": "abc", "title": "Doomed", "version": 7, "panels": []}
    conn = _graf_conn(prior)
    monkeypatch.setattr(t, "_get_connection", lambda target=None: conn)

    # 1. Delete: the harness records an undo descriptor from the captured model.
    result = t.delete_dashboard(uid="abc")
    undo_id = result["_undo_id"]
    assert undo_id, "expected the harness to record an undo token for the delete"
    record = store.get(undo_id)
    assert record["undo_tool"] == "update_dashboard"
    captured = json.loads(record["undo_params"])["dashboard"]
    assert captured == prior

    # 2. Replay: the dashboard is gone, so the prior-fetch 404s — the recreate
    #    must proceed anyway from the captured model.
    replay_conn = _missing_dashboard_conn(404)
    monkeypatch.setattr(t, "_get_connection", lambda target=None: replay_conn)
    replayed = t.update_dashboard(dashboard=captured)
    assert replayed["action"] == "update_dashboard"
    assert replayed["priorState"]["dashboard"] is None
    body = replay_conn.graf_post.call_args.kwargs["json"]
    assert body["dashboard"] == captured  # delete fully reversed


# ── reload ───────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_reload_records_prior_config_hash():
    conn = MagicMock(name="conn")
    conn.target.platform = "prometheus"
    conn.prom_get.return_value = {"status": "success", "data": {"yaml": "global: {}\n"}}
    out = ops.reload_prometheus_config(conn)
    assert out["action"] == "reload_prometheus_config"
    assert len(out["priorConfigHash"]) == 64  # sha256 hex
    conn.prom_reload.assert_called_once()


# ── MCP-layer risk tiers, dry_run, undo descriptors ──────────────────────────


@pytest.mark.unit
def test_write_risk_tiers():
    from mcp_server.tools import writes as t

    assert t.create_silence._risk_level == "medium"
    assert t.expire_silence._risk_level == "medium"
    assert t.create_annotation._risk_level == "medium"
    assert t.update_dashboard._risk_level == "medium"
    assert t.delete_dashboard._risk_level == "high"
    assert t.reload_prometheus_config._risk_level == "medium"


@pytest.mark.unit
def test_delete_dashboard_dry_run_does_not_mutate(monkeypatch):
    from mcp_server.tools import writes as t

    conn = _graf_conn({"uid": "abc", "title": "Keep"})
    monkeypatch.setattr(t, "_get_connection", lambda target=None: conn)
    result = t.delete_dashboard(uid="abc", dry_run=True)
    assert result["dryRun"] is True and result["wouldDelete"]["title"] == "Keep"
    conn.graf_delete.assert_not_called()


@pytest.mark.unit
def test_silence_undo_descriptor_inverts_to_expire():
    from mcp_server.tools import writes as t

    descriptor = t._silence_undo({}, {"silenceId": "sil-9"})
    assert descriptor["tool"] == "expire_silence"
    assert descriptor["params"]["silence_id"] == "sil-9"


@pytest.mark.unit
def test_update_dashboard_undo_descriptor_restores_prior():
    from mcp_server.tools import writes as t

    prior = {"uid": "abc", "title": "Old"}
    descriptor = t._update_dashboard_undo({}, {"priorState": {"dashboard": prior}})
    assert descriptor["tool"] == "update_dashboard"
    assert descriptor["params"]["dashboard"] == prior


# ── end-to-end: the harness RECORDS an undo token for update_dashboard ───────


@pytest.mark.unit
def test_governed_update_dashboard_records_undo(monkeypatch, tmp_path):
    from mcp_server.tools import writes as t
    from observability_aiops.governance import undo as undo_mod

    # Isolate the undo store to a throwaway db.
    store = undo_mod.UndoStore(tmp_path / "undo.db")
    monkeypatch.setattr(undo_mod, "_store", store)

    conn = _graf_conn({"uid": "abc", "title": "Old", "version": 2})
    monkeypatch.setattr(t, "_get_connection", lambda target=None: conn)

    result = t.update_dashboard(dashboard={"uid": "abc", "title": "New"})
    # The governed harness attached an undo id → an inverse was recorded.
    assert result["_undo_id"], "expected the harness to record an undo token"
    assert result["priorState"]["dashboard"]["title"] == "Old"


# ── URL-encoding of agent-supplied path segments ─────────────────────────────


@pytest.mark.unit
def test_path_traversal_ids_are_url_encoded():
    """An id carrying ``../`` must not reach the HTTP client as a raw path
    traversal — the segment is URL-encoded before interpolation."""
    conn = MagicMock(name="conn")
    conn.target.platform = "prometheus"
    ops.expire_silence(conn, "../v1/admin")
    path = conn.am_delete.call_args.args[0]
    assert "../" not in path and path.startswith("/api/v2/silence/")

    graf = _graf_conn({"uid": "x", "title": "t"})
    ops.delete_dashboard(graf, "../../api/admin")
    path = graf.graf_delete.call_args.args[0]
    assert "../" not in path and path.startswith("/api/dashboards/uid/")
