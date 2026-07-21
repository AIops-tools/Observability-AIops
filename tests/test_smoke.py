"""Smoke tests for observability-aiops.

Proves: every module imports, the CLI builds and --help works, the MCP server
exposes the expected tools and EVERY tool carries the harness marker
``_is_governed_tool``, config platform validation works, and the
platform-dispatching connection (Prometheus vs Grafana) guards correctly. No real
Prometheus/Grafana is needed — the connection uses a fake client.
"""

import asyncio
import importlib

import pytest
from typer.testing import CliRunner

# Kept in sync with mcp_server/server.py (the full registered tool surface).
EXPECTED_TOOLS = {
    # metrics
    "instant_query", "range_query", "label_values", "series_metadata",
    # targets
    "list_targets", "target_scrape_health", "dropped_targets",
    # prometheus status
    "prometheus_config_status", "prometheus_tsdb_status",
    # rules
    "list_rules", "rule_health",
    # alerts
    "firing_alerts", "pending_alerts", "alertmanager_alerts", "list_silences",
    # grafana
    "list_dashboards", "get_dashboard", "list_datasources", "datasource_health",
    "list_folders",
    # overview
    "observability_overview",
    # analysis
    "firing_alert_rca", "target_scrape_health_analysis", "alert_noise_and_flap_analysis",
    # loki (reads + log analyses + cross-signal)
    "loki_labels", "loki_label_values", "loki_query", "loki_tail_errors",
    "log_error_burst_rca", "log_volume_analysis", "alert_log_context",
    # writes
    "create_silence", "expire_silence", "create_annotation", "update_dashboard",
    "delete_dashboard", "reload_prometheus_config",
}


@pytest.mark.unit
def test_all_modules_import():
    for name in (
        "observability_aiops", "observability_aiops.config",
        "observability_aiops.connection", "observability_aiops.doctor",
        "observability_aiops.secretstore",
        "observability_aiops.ops.metrics", "observability_aiops.ops.targets",
        "observability_aiops.ops.rules", "observability_aiops.ops.alerts",
        "observability_aiops.ops.grafana", "observability_aiops.ops.analysis",
        "observability_aiops.ops.writes", "observability_aiops.ops.overview",
        "observability_aiops.ops.prom_status", "observability_aiops.ops.loki",
        "observability_aiops.ops.log_analysis",
        "observability_aiops.cli", "observability_aiops.cli._root",
        "observability_aiops.cli._common", "observability_aiops.cli.init",
        "observability_aiops.cli.secret", "observability_aiops.cli.query",
        "observability_aiops.cli.logs",
        "observability_aiops.cli.alert", "observability_aiops.cli.overview",
        "observability_aiops.cli.doctor",
        "mcp_server.server", "mcp_server._shared",
        "mcp_server.tools.metrics", "mcp_server.tools.writes",
        "mcp_server.tools.analysis", "mcp_server.tools.loki",
    ):
        importlib.import_module(name)


@pytest.mark.unit
def test_version_matches_pyproject():
    """__version__ is single-sourced from package metadata; it must track
    pyproject.toml so a release bump can never ship a stale self-report."""
    import tomllib
    from pathlib import Path

    import observability_aiops

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text("utf-8"))["project"]["version"]
    assert observability_aiops.__version__ == expected


@pytest.mark.unit
def test_cli_app_builds_and_help_works():
    from observability_aiops.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for sub in ("query", "logs", "alert", "secret", "init", "overview", "doctor", "mcp"):
        assert sub in result.output


@pytest.mark.unit
def test_cli_leaf_help_triggers_lazy_imports():
    from observability_aiops.cli import app

    runner = CliRunner()
    for cmd in (
        ["query", "--help"], ["alert", "--help"], ["secret", "--help"],
        ["doctor", "--help"], ["overview", "--help"], ["init", "--help"],
        ["query", "instant", "--help"], ["query", "range", "--help"],
        ["query", "labels", "--help"],
        ["logs", "--help"], ["logs", "labels", "--help"], ["logs", "query", "--help"],
        ["logs", "errors", "--help"],
        ["alert", "firing", "--help"], ["alert", "silences", "--help"],
        ["alert", "rca", "--help"],
        ["secret", "list", "--help"], ["secret", "set", "--help"],
    ):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0, f"{cmd} failed: {result.output}"


@pytest.mark.unit
def test_mcp_list_tools_exposes_expected_tools():
    from mcp_server.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS <= names, f"missing: {EXPECTED_TOOLS - names}"


@pytest.mark.unit
def test_every_mcp_tool_is_governed_by_harness():
    from mcp_server import _shared

    tool_objs = _shared.mcp._tool_manager._tools
    assert EXPECTED_TOOLS <= set(tool_objs), "tool registry incomplete"
    assert len(tool_objs) == 39, (
        "tool count changed — update README/SKILL/server.json too"
    )
    for name, tool in tool_objs.items():
        fn = getattr(tool, "fn", None)
        assert fn is not None, f"{name} has no fn"
        assert getattr(fn, "_is_governed_tool", False), f"{name} missing @governed_tool"


# ── config platform validation ──────────────────────────────────────────


@pytest.mark.unit
def test_config_rejects_bad_platform_and_defaults_port():
    from observability_aiops.config import TargetConfig

    with pytest.raises(ValueError):
        TargetConfig(name="x", platform="datadog", host="h")
    prom = TargetConfig(name="p", platform="prometheus", host="h")
    assert prom.port == 9090
    graf = TargetConfig(name="g", platform="grafana", host="h")
    assert graf.port == 3000


@pytest.mark.unit
def test_config_alertmanager_base_default_and_override():
    from observability_aiops.config import TargetConfig

    prom = TargetConfig(name="p", platform="prometheus", host="prom.local")
    assert prom.alertmanager_base == "http://prom.local:9093"
    with_am = TargetConfig(
        name="p2", platform="prometheus", host="prom.local",
        alertmanager_url="http://am.local:9093/",
    )
    assert with_am.alertmanager_base == "http://am.local:9093"


# ── connection: platform dispatch guard ─────────────────────────────────


class _Resp:
    def __init__(self, status, payload=None, content=b"{}"):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.content = content
        self.text = "body"

    def json(self):
        return self._payload


@pytest.mark.unit
def test_connection_prom_get_and_platform_guard():
    from observability_aiops.config import TargetConfig
    from observability_aiops.connection import ObservabilityApiError, ObservabilityConnection

    target = TargetConfig(name="prom1", platform="prometheus", host="prom.local")

    class _Client:
        def request(self, method, path, **k):
            return _Resp(200, {"status": "success", "data": {"result": []}})

        def close(self):
            pass

    conn = ObservabilityConnection(target, client=_Client())
    assert conn.prom_get("/api/v1/query", {"query": "up"})["status"] == "success"
    # Grafana-only method against a Prometheus target must raise
    with pytest.raises(ObservabilityApiError):
        conn.graf_get("/api/health")


@pytest.mark.unit
def test_risk_level_agrees_with_read_write_docstring_tag():
    """The two write-markers must never drift apart.

    A tool's ``risk_level`` decides its audit tier and whether it gets dry-run /
    undo handling; its ``[READ]``/``[WRITE]`` docstring tag is what the docs and
    capability tables are built from. If a ``[WRITE]`` were left ``risk_level=low``
    it would be audited as a read and skip the write machinery — this test caught
    16 such mislabels line-wide once, so it is kept even though read-only mode
    (its original motivation) is gone.
    """
    from mcp_server import server

    untagged, mismatched = [], []
    for name, tool in server.mcp._tool_manager._tools.items():
        doc = (tool.fn.__doc__ or "").lstrip()
        if doc.startswith("[READ]"):
            tagged_as_read = True
        elif doc.startswith("[WRITE]"):
            tagged_as_read = False
        else:
            untagged.append(name)
            continue
        if tagged_as_read != (getattr(tool.fn, "_risk_level", "low") == "low"):
            mismatched.append(name)

    assert not untagged, f"tools missing a [READ]/[WRITE] docstring tag: {untagged}"
    assert not mismatched, f"risk_level disagrees with the docstring tag: {mismatched}"
