"""Configuration management for Observability AIops.

Loads self-hosted observability connection targets from a YAML config file. Each
target names its ``platform`` — ``prometheus`` (Prometheus HTTP API, optionally
fronting an Alertmanager), ``grafana`` (Grafana HTTP API), or ``loki`` (Grafana
Loki log-store HTTP API) — so one config can span a whole observability stack.

The token is NEVER stored in the config file or in plaintext on disk: it lives
in the encrypted store ``~/.observability-aiops/secrets.enc`` (see
:mod:`observability_aiops.secretstore`). For Prometheus and Loki a token is
*optional* (many self-hosted deployments are unauthenticated); for Grafana a
service-account/API token is *required*. A legacy env var
(``OBSERVABILITY_<TARGET>_TOKEN``) is honoured as a fallback.

A Loki target may additionally carry ``auth_type`` (``bearer`` — the default —
or ``basic``, in which case the stored secret is ``user:password``) and
``org_id`` (sent as the multi-tenant ``X-Scope-OrgID`` header).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from observability_aiops.governance.paths import ops_home
from observability_aiops.secretstore import (
    MasterPasswordError,
    SecretStoreError,
    get_secret,
    has_store,
)

CONFIG_DIR = ops_home()
CONFIG_FILE = CONFIG_DIR / "config.yaml"
ENV_FILE = CONFIG_DIR / ".env"

PLATFORM_PROMETHEUS = "prometheus"
PLATFORM_GRAFANA = "grafana"
PLATFORM_LOKI = "loki"
PLATFORMS = (PLATFORM_PROMETHEUS, PLATFORM_GRAFANA, PLATFORM_LOKI)

# Platforms that must carry a token (Grafana rejects unauthenticated API calls;
# self-hosted Prometheus and Loki are frequently unauthenticated, so their
# token is optional).
TOKEN_REQUIRED = (PLATFORM_GRAFANA,)

# Per-target authentication schemes (Loki honours both; a Prometheus/Grafana
# token is always a bearer token).
AUTH_BEARER = "bearer"
AUTH_BASIC = "basic"
AUTH_TYPES = (AUTH_BEARER, AUTH_BASIC)

# Sensible default ports per platform (Prometheus web / Grafana web / Loki HTTP).
DEFAULT_PORTS = {PLATFORM_PROMETHEUS: 9090, PLATFORM_GRAFANA: 3000, PLATFORM_LOKI: 3100}

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
        except MasterPasswordError:
            # A wrong or missing master password is NOT "this target has no
            # secret". Falling through resurfaced it as "No API key for target
            # X", sending the operator to add a credential that is already
            # there. MasterPasswordError subclasses SecretStoreError, so the
            # broad catch below would swallow it — re-raise first.
            raise
        except SecretStoreError:
            pass  # no secret stored for this target — try the legacy env var
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

    ``platform`` is ``prometheus``, ``grafana``, or ``loki``. Non-secret
    connection details (scheme/host/port) live in the config file; the token
    comes from the encrypted store. ``alertmanager_url`` (Prometheus only) points
    the alert tools at a companion Alertmanager when it is not co-located.
    ``auth_type`` (``bearer`` default / ``basic``) and ``org_id`` (multi-tenant
    ``X-Scope-OrgID``) are Loki-oriented but stored uniformly.
    """

    name: str
    platform: str
    host: str
    port: int = 0
    scheme: str = "http"
    verify_ssl: bool = True
    alertmanager_url: str = ""
    auth_type: str = AUTH_BEARER
    org_id: str = ""

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
        if self.auth_type not in AUTH_TYPES:
            raise ValueError(
                f"Target '{self.name}': auth_type must be one of {AUTH_TYPES}, "
                f"got '{self.auth_type}'."
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
            auth_type=t.get("auth_type", AUTH_BEARER),
            org_id=t.get("org_id", ""),
        )
        for t in raw.get("targets", [])
    )

    return AppConfig(targets=targets)
