"""``observability-aiops init`` onboarding wizard, driven non-interactively.

All on-disk state (config.yaml, secrets.enc) is redirected to a tmp dir; the
master password comes from the env var and token entry (getpass) is patched.
Prompts are fed through the Typer runner's stdin. Covers the Prometheus
(no-token), Grafana (required token), and Loki (basic-auth + multi-tenant)
branches, plus the invalid-platform re-prompt.
"""

from __future__ import annotations

import getpass

import pytest
import yaml
from typer.testing import CliRunner

import observability_aiops.cli.init as init_mod
import observability_aiops.secretstore as ss
from observability_aiops.cli import app

runner = CliRunner()


@pytest.fixture
def wizard_env(tmp_path, monkeypatch):
    cfg_dir = tmp_path
    monkeypatch.setattr(init_mod, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(init_mod, "CONFIG_FILE", cfg_dir / "config.yaml")
    monkeypatch.setattr(ss, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(ss, "SECRETS_FILE", cfg_dir / "secrets.enc")
    monkeypatch.setattr(ss, "LEGACY_ENV_FILE", cfg_dir / ".env")
    monkeypatch.setattr(ss, "_cached", None)
    monkeypatch.setenv("OBSERVABILITY_AIOPS_MASTER_PASSWORD", "master-pw")
    monkeypatch.setenv("OBSERVABILITY_AIOPS_HOME", str(cfg_dir))
    return cfg_dir


def _targets(cfg_dir):
    return yaml.safe_load((cfg_dir / "config.yaml").read_text("utf-8"))["targets"]


@pytest.mark.unit
def test_init_prometheus_no_token(wizard_env, monkeypatch):
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "")  # unauthenticated
    stdin = "prod-prom\n\nprom.local\n\n\n\nn\nn\n"
    result = runner.invoke(app, ["init"], input=stdin)
    assert result.exit_code == 0, result.output
    targets = _targets(wizard_env)
    assert len(targets) == 1
    assert targets[0]["name"] == "prod-prom"
    assert targets[0]["platform"] == "prometheus"
    assert targets[0]["port"] == 9090


@pytest.mark.unit
def test_init_grafana_requires_and_stores_token(wizard_env, monkeypatch):
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "graf-token")
    stdin = "graf-prod\ngrafana\ngraf.local\n\n\nn\nn\n"
    result = runner.invoke(app, ["init"], input=stdin)
    assert result.exit_code == 0, result.output
    targets = _targets(wizard_env)
    assert targets[0]["platform"] == "grafana" and targets[0]["port"] == 3000
    # token was written to the encrypted store, never to config.yaml
    assert ss.SecretStore.unlock("master-pw").get("graf-prod") == "graf-token"
    assert "graf-token" not in (wizard_env / "config.yaml").read_text("utf-8")


@pytest.mark.unit
def test_init_loki_basic_auth_and_tenant(wizard_env, monkeypatch):
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "user:pass")
    stdin = "loki-prod\nloki\nloki.local\n\n\nbasic\nteam-a\nn\nn\n"
    result = runner.invoke(app, ["init"], input=stdin)
    assert result.exit_code == 0, result.output
    entry = _targets(wizard_env)[0]
    assert entry["platform"] == "loki"
    assert entry["auth_type"] == "basic"
    assert entry["org_id"] == "team-a"
    assert ss.SecretStore.unlock("master-pw").get("loki-prod") == "user:pass"


@pytest.mark.unit
def test_init_reprompts_on_invalid_platform(wizard_env, monkeypatch):
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "")
    # first platform is bogus -> re-prompt; then a valid prometheus target
    stdin = "p1\ndatadog\np1\nprometheus\nprom.local\n\n\n\nn\nn\n"
    result = runner.invoke(app, ["init"], input=stdin)
    assert result.exit_code == 0, result.output
    assert "must be 'prometheus', 'grafana', or 'loki'" in result.output
    assert _targets(wizard_env)[0]["platform"] == "prometheus"
