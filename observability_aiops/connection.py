"""Connection management for Prometheus, Grafana, and Alertmanager.

One :class:`ObservabilityConnection` speaks the protocol of its target's
platform:

  * **Prometheus** — the HTTP API. ``prom_get`` hits ``/api/v1/...`` read
    endpoints (query, targets, rules, alerts, status); ``prom_reload`` issues the
    ``POST /-/reload`` lifecycle call. Its ``am_*`` helpers reach the companion
    Alertmanager (``/api/v2/...``) for alert + silence reads/writes.
  * **Grafana** — the HTTP API. ``graf_get`` / ``graf_post`` / ``graf_put`` /
    ``graf_delete`` hit ``/api/...`` for dashboards, datasources, folders,
    annotations, and health.

Both platforms authenticate with a bearer token when one is configured (required
for Grafana, optional for a self-hosted Prometheus). Platform-specific methods
guard on ``platform`` and raise a clear ``ObservabilityApiError`` if called
against the wrong platform, so a Grafana-only tool can't silently misfire at a
Prometheus target.

The httpx client is injectable for tests (``client=``); mock responses expose
``status_code``, ``content``, ``text``, and ``json()``.
"""

from __future__ import annotations

from typing import Any

import httpx

from observability_aiops.config import (
    PLATFORM_GRAFANA,
    PLATFORM_PROMETHEUS,
    AppConfig,
    TargetConfig,
    load_config,
)

_TIMEOUT = 60.0


class ObservabilityApiError(Exception):
    """A Prometheus/Grafana/Alertmanager call failed; carries a teaching message."""

    def __init__(self, message: str, *, status_code: int | None = None, path: str = "") -> None:
        self.status_code = status_code
        self.path = path
        super().__init__(message)


def _teaching_message(status: int, path: str, body: str, platform: str) -> str:
    snippet = body[:200].strip()
    if status in (401, 403):
        return (
            f"Authentication failed ({status}) on {platform} {path}. Check the "
            f"bearer token (Grafana service-account token / Prometheus auth) and "
            f"the token's role/scope. {snippet}"
        )
    if status == 404:
        return f"Not found (404) on {platform} {path}. Check the id/uid/name. {snippet}"
    if status in (400, 422):
        return (
            f"Bad request ({status}) on {platform} {path}. For Prometheus this is "
            f"often a PromQL syntax error; check the query. {snippet}"
        )
    if status in (500, 502, 503, 504):
        return (
            f"{platform} server error ({status}) on {path}. The service may be busy; "
            f"retry shortly. {snippet}"
        )
    return f"{platform} API error ({status}) on {path}. {snippet}"


class ObservabilityConnection:
    """A session against one Prometheus or Grafana target."""

    def __init__(self, target: TargetConfig, client: Any | None = None) -> None:
        self._target = target
        headers = {"Accept": "application/json"}
        if target.secret:
            headers["Authorization"] = f"Bearer {target.secret}"
        self._client = client or httpx.Client(
            base_url=target.base_url,
            verify=target.verify_ssl,
            timeout=_TIMEOUT,
            headers=headers,
        )

    @property
    def target(self) -> TargetConfig:
        return self._target

    def _require(self, platform: str, tool: str) -> None:
        if self._target.platform != platform:
            raise ObservabilityApiError(
                f"'{tool}' requires a {platform} target, but '{self._target.name}' "
                f"is a {self._target.platform} target.",
            )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ObservabilityApiError(
                f"Could not reach {self._target.platform} at {self._target.base_url} "
                f"({method} {path}): {exc}. Check host/port/scheme and reachability.",
                path=path,
            ) from exc
        if not (200 <= resp.status_code < 300):
            raise ObservabilityApiError(
                _teaching_message(resp.status_code, path, resp.text, self._target.platform),
                status_code=resp.status_code,
                path=path,
            )
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {}

    # ── Prometheus HTTP API ──────────────────────────────────────────────
    def prom_get(self, path: str, params: dict | None = None) -> Any:
        """GET a Prometheus ``/api/v1`` (or ``/status``) read endpoint."""
        self._require(PLATFORM_PROMETHEUS, "prom_get")
        return self._request("GET", path, params=params or None)

    def prom_reload(self) -> Any:
        """POST ``/-/reload`` to hot-reload the Prometheus config (governed write)."""
        self._require(PLATFORM_PROMETHEUS, "prom_reload")
        return self._request("POST", "/-/reload")

    # ── Alertmanager (reached via the Prometheus target) ─────────────────
    def am_get(self, path: str, params: dict | None = None) -> Any:
        """GET an Alertmanager ``/api/v2`` endpoint (absolute URL, own base)."""
        self._require(PLATFORM_PROMETHEUS, "am_get")
        url = f"{self._target.alertmanager_base}{path}"
        return self._request("GET", url, params=params or None)

    def am_post(self, path: str, json: Any = None) -> Any:
        """POST to an Alertmanager ``/api/v2`` endpoint (e.g. create a silence)."""
        self._require(PLATFORM_PROMETHEUS, "am_post")
        url = f"{self._target.alertmanager_base}{path}"
        return self._request("POST", url, json=json)

    def am_delete(self, path: str) -> Any:
        """DELETE an Alertmanager ``/api/v2`` resource (e.g. expire a silence)."""
        self._require(PLATFORM_PROMETHEUS, "am_delete")
        url = f"{self._target.alertmanager_base}{path}"
        return self._request("DELETE", url)

    # ── Grafana HTTP API ─────────────────────────────────────────────────
    def graf_get(self, path: str, params: dict | None = None) -> Any:
        """GET a Grafana ``/api`` endpoint."""
        self._require(PLATFORM_GRAFANA, "graf_get")
        return self._request("GET", path, params=params or None)

    def graf_post(self, path: str, json: Any = None) -> Any:
        """POST to a Grafana ``/api`` endpoint (governed writes)."""
        self._require(PLATFORM_GRAFANA, "graf_post")
        return self._request("POST", path, json=json)

    def graf_delete(self, path: str) -> Any:
        """DELETE a Grafana ``/api`` resource (governed writes)."""
        self._require(PLATFORM_GRAFANA, "graf_delete")
        return self._request("DELETE", path)

    def close(self) -> None:
        self._client.close()


class ConnectionManager:
    """Manages connections to multiple observability targets with session reuse."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._connections: dict[str, ObservabilityConnection] = {}

    @classmethod
    def from_config(cls, config: AppConfig | None = None) -> ConnectionManager:
        cfg = config or load_config()
        return cls(cfg)

    def connect(self, target_name: str | None = None) -> ObservabilityConnection:
        target = (
            self._config.get_target(target_name)
            if target_name
            else self._config.default_target
        )
        cached = self._connections.get(target.name)
        if cached is not None:
            return cached
        conn = ObservabilityConnection(target)
        self._connections[target.name] = conn
        return conn

    def disconnect(self, target_name: str) -> None:
        conn = self._connections.pop(target_name, None)
        if conn is not None:
            conn.close()

    def disconnect_all(self) -> None:
        for name in list(self._connections):
            self.disconnect(name)

    def list_targets(self) -> list[str]:
        return [t.name for t in self._config.targets]

    def list_connected(self) -> list[str]:
        return list(self._connections.keys())
