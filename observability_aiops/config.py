"""Configuration management for Observability AIops.

Loads self-hosted observability connection targets from a YAML config file. Each
target names its ``platform`` — ``prometheus`` (Prometheus HTTP API, optionally
fronting an Alertmanager) or ``grafana`` (Grafana HTTP API) — so one config can
span a whole observability stack.

The token is NEVER stored in the config file or in plaintext on disk: it lives
in the encrypted store ``~/.observability-aiops/secrets.enc`` (see
:mod:`observability_aiops.secretstore`). For Prometheus a bearer token is
*optional* (many self-hosted deployments are unauthenticated); for Grafana a
service-account/API token is *required*. A legacy env var
(``OBSERVABILITY_<TARGET>_TOKEN``) is honoured as a fallback.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from observability_aiops.governance.paths import ops_home
from observability_aiops.secretstore import SecretStoreError, get_secret, has_store

CONFIG_DIR = ops_home()
CONFIG_FILE = CONFIG_DIR / "config.yaml"
ENV_FILE = CONFIG_DIR / ".env"

PLATFORM_PROMETHEUS = "prometheus"
PLATFORM_GRAFANA = "grafana"
PLATFORMS = (PLATFORM_PROMETHEUS, PLATFORM_GRAFANA)

# Platforms that must carry a token (Grafana rejects unauthenticated API calls;
# self-hosted Prometheus is frequently unauthenticated, so its token is optional).
TOKEN_REQUIRED = (PLATFORM_GRAFANA,)

# Sensible default ports per platform (Prometheus web / Grafana web).
DEFAULT_PORTS = {PLATFORM_PROMETHEUS: 9090, PLATFORM_GRAFANA: 3000}

SECRET_ENV_PREFIX = "OBSERVABILITY_"  # nosec B105 — env-var name, not a secret
SECRET_ENV_SUFFIX = "_TOKEN"  # nosec B105 — env-var name, not a secret

_log = logging.getLogger("observability-aiops.config")


def _secret_env_key(name: str) -> str:
    """Legacy per-target token env var name, e.g. OBSERVABILITY_PROM1_TOKEN."""
    return f"{SECRET_ENV_PREFIX}{name.upper().replace('-', '_')}{SECRET_ENV_SUFFIX}"


def _resolve_secret(name: str, *, required: bool) -> str:
    """Return a target's token: encrypted store first, then legacy env var.

    When ``required`` is False (unauthenticated Prometheus) a missing token
    resolves to the empty string rather than raising.
    """
    if has_store():
        try:
            return get_secret(name)
        except SecretStoreError:
            pass  # fall through to legacy env var
    legacy = os.environ.get(_secret_env_key(name))
    if legacy:
        _log.warning(
            "Using plaintext env var %s. Migrate to the encrypted store with "
            "'observability-aiops secret migrate'.",
            _secret_env_key(name),
        )
        return legacy
    if not required:
        return ""
    raise OSError(
        f"No token for target '{name}'. Add one with "
        f"'observability-aiops secret set {name}' (stored encrypted), or run "
        f"'observability-aiops init'."
    )


@dataclass(frozen=True)
class TargetConfig:
    """A connection target for one observability platform instance.

    ``platform`` is ``prometheus`` or ``grafana``. Non-secret connection details
    (scheme/host/port) live in the config file; the bearer token comes from the
    encrypted store. ``alertmanager_url`` (Prometheus only) points the alert
    tools at a companion Alertmanager when it is not co-located.
    """

    name: str
    platform: str
    host: str
    port: int = 0
    scheme: str = "http"
    verify_ssl: bool = True
    alertmanager_url: str = ""

    def __post_init__(self) -> None:
        if self.platform not in PLATFORMS:
            raise ValueError(
                f"Target '{self.name}': platform must be one of {PLATFORMS}, "
                f"got '{self.platform}'."
            )
        if self.scheme not in ("http", "https"):
            raise ValueError(
                f"Target '{self.name}': scheme must be 'http' or 'https', "
                f"got '{self.scheme}'."
            )
        if not self.port:
            object.__setattr__(self, "port", DEFAULT_PORTS[self.platform])

    @property
    def secret(self) -> str:
        return _resolve_secret(self.name, required=self.platform in TOKEN_REQUIRED)

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def alertmanager_base(self) -> str:
        """Base URL for this target's Alertmanager (Prometheus targets only).

        Uses the explicit ``alertmanager_url`` when set, else assumes a
        co-located Alertmanager on the conventional port 9093.
        """
        if self.alertmanager_url:
            return self.alertmanager_url.rstrip("/")
        return f"{self.scheme}://{self.host}:9093"


@dataclass(frozen=True)
class AppConfig:
    """Top-level application config."""

    targets: tuple[TargetConfig, ...] = ()

    def get_target(self, name: str) -> TargetConfig:
        for t in self.targets:
            if t.name == name:
                return t
        available = ", ".join(t.name for t in self.targets) or "(none)"
        raise KeyError(f"Target '{name}' not found. Available: {available}")

    @property
    def default_target(self) -> TargetConfig:
        if not self.targets:
            raise ValueError("No targets configured. Check config.yaml")
        return self.targets[0]


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load config from YAML; the token comes from the encrypted store."""
    path = config_path or CONFIG_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            f"Run 'observability-aiops init' to set up a Prometheus or Grafana "
            f"target, or create {CONFIG_FILE} with a 'targets' list."
        )

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    targets = tuple(
        TargetConfig(
            name=t["name"],
            platform=t["platform"],
            host=t["host"],
            port=t.get("port", 0),
            scheme=t.get("scheme", "http"),
            verify_ssl=t.get("verify_ssl", True),
            alertmanager_url=t.get("alertmanager_url", ""),
        )
        for t in raw.get("targets", [])
    )

    return AppConfig(targets=targets)
