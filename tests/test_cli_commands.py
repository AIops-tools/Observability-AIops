"""CLI leaf-command bodies driven through the Typer runner.

``get_connection`` is patched per sub-module to hand back a canned MagicMock
connection, so each command's real body runs (build args, call the op, print
JSON) without any config file or network. Also covers the shared ``cli_errors``
translation of known exceptions into a one-line error + exit code 1.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from observability_aiops.cli import app

runner = CliRunner()


def _prom_conn():
    """A MagicMock whose prom_get answers every Prometheus read path plausibly."""
    conn = MagicMock(name="conn")
    conn.target.platform = "prometheus"
    conn.target.name = "prom1"

    def _get(path, params=None):
        if path == "/api/v1/alerts":
            return {"status": "success", "data": {"alerts": [
                {"labels": {"alertname": "A", "severity": "critical"}, "state": "firing"},
            ]}}
        if path == "/api/v1/rules":
            return {"status": "success", "data": {"groups": []}}
        return {"status": "success", "data": {"result": []}}

    conn.prom_get.side_effect = _get
    conn.am_get.return_value = []
    return conn


def _patch_conn(monkeypatch, module, conn):
    monkeypatch.setattr(f"observability_aiops.cli.{module}.get_connection",
                        lambda target=None: (conn, MagicMock()))


@pytest.mark.unit
def test_query_instant_prints_json(monkeypatch):
    _patch_conn(monkeypatch, "query", _prom_conn())
    result = runner.invoke(app, ["query", "instant", "up"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["query"] == "up"


@pytest.mark.unit
def test_query_range_and_labels(monkeypatch):
    _patch_conn(monkeypatch, "query", _prom_conn())
    r1 = runner.invoke(app, ["query", "range", "up", "--start", "s", "--end", "e"])
    r2 = runner.invoke(app, ["query", "labels", "job"])
    assert r1.exit_code == 0 and r2.exit_code == 0
    assert json.loads(r2.stdout)["label"] == "job"


@pytest.mark.unit
def test_logs_labels_query_errors(monkeypatch):
    conn = MagicMock(name="loki")
    conn.target.platform = "loki"
    conn.loki_get.return_value = {"status": "success", "data": {"result": []}}
    _patch_conn(monkeypatch, "logs", conn)
    assert runner.invoke(app, ["logs", "labels"]).exit_code == 0
    assert runner.invoke(app, ["logs", "query", '{app="api"}']).exit_code == 0
    assert runner.invoke(app, ["logs", "errors", '{app="api"}']).exit_code == 0


@pytest.mark.unit
def test_logs_query_without_selector_is_rejected(monkeypatch):
    conn = MagicMock(name="loki")
    conn.target.platform = "loki"
    _patch_conn(monkeypatch, "logs", conn)
    result = runner.invoke(app, ["logs", "query", '|= "error"'])
    # bounding gate refuses before any HTTP call; body still exits 0 (prints error json)
    assert result.exit_code == 0
    assert "selector" in json.loads(result.stdout)["error"].lower()
    conn.loki_get.assert_not_called()


@pytest.mark.unit
def test_alert_firing_silences_rca(monkeypatch):
    _patch_conn(monkeypatch, "alert", _prom_conn())
    assert runner.invoke(app, ["alert", "firing"]).exit_code == 0
    assert runner.invoke(app, ["alert", "silences"]).exit_code == 0
    rca = runner.invoke(app, ["alert", "rca"])
    assert rca.exit_code == 0


@pytest.mark.unit
def test_overview_command(monkeypatch):
    monkeypatch.setattr("observability_aiops.cli.overview.get_connection",
                        lambda target=None: (_prom_conn(), MagicMock()))
    result = runner.invoke(app, ["overview"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["platform"] == "prometheus"


@pytest.mark.unit
def test_doctor_command_delegates_and_uses_exit_code(monkeypatch):
    monkeypatch.setattr("observability_aiops.doctor.run_doctor", lambda skip_auth=False: 0)
    ok = runner.invoke(app, ["doctor", "--skip-auth"])
    assert ok.exit_code == 0
    monkeypatch.setattr("observability_aiops.doctor.run_doctor", lambda skip_auth=False: 1)
    bad = runner.invoke(app, ["doctor"])
    assert bad.exit_code == 1


@pytest.mark.unit
def test_cli_errors_translates_api_error_to_red_line(monkeypatch):
    from observability_aiops.connection import ObservabilityApiError

    def _boom(target=None):
        raise ObservabilityApiError("prometheus unreachable")

    monkeypatch.setattr("observability_aiops.cli.query.get_connection", _boom)
    result = runner.invoke(app, ["query", "instant", "up"])
    assert result.exit_code == 1
    assert "Error:" in result.stdout and "unreachable" in result.stdout


@pytest.mark.unit
def test_cli_errors_annotates_keyerror(monkeypatch):
    def _boom(target=None):
        raise KeyError("no-such-target")

    monkeypatch.setattr("observability_aiops.cli.query.get_connection", _boom)
    result = runner.invoke(app, ["query", "instant", "up"])
    assert result.exit_code == 1
    assert "Missing required key" in result.stdout
