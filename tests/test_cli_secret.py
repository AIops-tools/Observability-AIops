"""``observability-aiops secret`` CLI: set/list/rm/migrate/rotate-password.

The encrypted store is redirected to a tmp dir and the master password comes
from the env var so the flows run non-interactively. Secret values are never
printed by these commands — the tests assert that too.
"""

from __future__ import annotations

import getpass

import pytest
from typer.testing import CliRunner

import observability_aiops.secretstore as ss
from observability_aiops.cli import app

runner = CliRunner()


@pytest.fixture
def store_env(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ss, "SECRETS_FILE", tmp_path / "secrets.enc")
    monkeypatch.setattr(ss, "LEGACY_ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(ss, "_cached", None)
    monkeypatch.setenv("OBSERVABILITY_AIOPS_MASTER_PASSWORD", "master-pw")
    return tmp_path


@pytest.mark.unit
def test_secret_set_list_rm_roundtrip(store_env):
    r = runner.invoke(app, ["secret", "set", "prom1", "--value", "s3cr3t-token"])
    assert r.exit_code == 0 and "Stored encrypted token" in r.stdout
    # value must never be echoed back
    assert "s3cr3t-token" not in r.stdout

    listed = runner.invoke(app, ["secret", "list"])
    assert listed.exit_code == 0 and "prom1" in listed.stdout
    assert "s3cr3t-token" not in listed.stdout

    removed = runner.invoke(app, ["secret", "rm", "prom1"])
    assert removed.exit_code == 0 and "Deleted token" in removed.stdout

    empty = runner.invoke(app, ["secret", "list"])
    assert "No secrets stored yet" in empty.stdout


@pytest.mark.unit
def test_secret_set_prompts_when_value_omitted(store_env, monkeypatch):
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "prompted-token")
    r = runner.invoke(app, ["secret", "set", "graf1"])
    assert r.exit_code == 0
    # verify it was actually stored under the right name
    assert ss.SecretStore.unlock("master-pw").get("graf1") == "prompted-token"


@pytest.mark.unit
def test_secret_migrate_imports_legacy_env(store_env):
    (store_env / ".env").write_text(
        "OBSERVABILITY_PROM1_TOKEN=legacy-abc\n# comment\nJUNK\n", "utf-8"
    )
    r = runner.invoke(app, ["secret", "migrate"])
    assert r.exit_code == 0 and "Imported 1 secret" in r.stdout
    assert ss.SecretStore.unlock("master-pw").get("prom1") == "legacy-abc"

    again = runner.invoke(app, ["secret", "migrate"])
    assert "Nothing to migrate" in again.stdout


@pytest.mark.unit
def test_secret_rotate_password(store_env, monkeypatch):
    runner.invoke(app, ["secret", "set", "prom1", "--value", "tok"])
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "new-master-pw")
    r = runner.invoke(app, ["secret", "rotate-password"])
    assert r.exit_code == 0 and "rotated" in r.stdout
    # the store now decrypts only under the new password
    assert ss.SecretStore.unlock("new-master-pw").get("prom1") == "tok"


@pytest.mark.unit
def test_secret_rotate_password_mismatch_aborts(store_env, monkeypatch):
    runner.invoke(app, ["secret", "set", "prom1", "--value", "tok"])
    answers = iter(["one", "two"])
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(answers))
    r = runner.invoke(app, ["secret", "rotate-password"])
    assert r.exit_code == 1 and "did not match" in r.stdout
