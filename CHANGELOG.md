# Changelog

## Unreleased

### Fixed
- **The error-burst RCA could not see a large burst.** Per-stream error counts were the row count of a `query_range` bounded at 100 lines, so every busy stream reported exactly 100 and the current-vs-baseline comparison collapsed. A service going from 25 to 485 errors read as 100 → 100 — **no burst** — and so did a service that had been noisy all along, meaning the analysis failed precisely when the incident was big. Counts now come from Loki's own `count_over_time`, evaluated server-side and exact at any volume; the bounded line query is used only for sample lines, and a stream crowded out of it is still reported with its real count and no samples. Verified against a live Loki 3.0.0: the same seeded 19x spike scores `burstCount: 0` before the fix and `volume_spike` after.
- **`undo apply` replays against the target the original write ran on.** It dispatched the inverse against whatever target the *caller* named — in practice the config's first entry — while the write's own target sat unused in the undo record. On a multi-target config the inverse therefore ran against the wrong host; it only looks harmless because the resource usually is not there, but two hosts holding the same name and the inverse **succeeds on the wrong one, silently**. An explicitly named target still wins. Line-wide: all 24 copies had the identical defect. Caught live in container-host-aiops, where a stop recorded against a Podman target replayed against a Portainer one.

## v0.7.0 — 2026-08-02

### Changed (BREAKING)
- **Requires MCP SDK 2.0** (`mcp[cli]>=2.0,<3.0`). `mcp.server.fastmcp` no longer exists in 2.0; the server is now built with `MCPServer` and reports its package version in the stdio handshake.

### Fixed
- **`undo apply` works from the CLI.** Every write tool is imported lazily inside its own CLI command, so a CLI-driven undo ran in a process where the inverse tool was never registered and failed with "inverse tool is not registered" — for every write tool. Only the MCP entry point, which imports the whole server, worked. Found while live-verifying against a real cluster.
- **An undetermined outcome is audited `unknown`, not `ok`.** The harness only classified a result as undetermined when the payload *also* carried an `error` key, so a write that looked successful but had not been confirmed was recorded as a success.


## v0.6.0 — 2026-07-21

### Changed (BREAKING)
- **Removed the authorization layer** — read-only mode, the approver gate, and rules.yaml deny are gone. The skill no longer decides read vs write; that is the agent's judgement or the connecting account's permissions. `<PREFIX>_READ_ONLY` now has no effect (a startup warning is logged); `<PREFIX>_AUDIT_APPROVED_BY`/`_RATIONALE` are optional audit annotations.
- The retained guarantee is **unbypassable audit over MCP and CLI alike** — no unaudited entry point. Harness = audit + runaway safety guard + undo + sanitize; `risk_level` is a descriptive audit label, not a gate.

See RELEASE_NOTES.md for tool-specific changes.


## v0.5.0 — 2026-07-20

### Fixed
- Harness: a write whose response is lost is audited `status=unknown`, not `error` — it may have taken effect. Undo tokens gain `effectVerified` (undo.db migrated in place).
- Harness: a dry-run no longer records an undo token, and no longer requires a named approver. Guards now run on the preview path.
- Truncated strings end in an ellipsis instead of being cut silently; error messages are capped at 800 chars, not 300.

See RELEASE_NOTES.md for the full detail.

## v0.3.0 — 2026-07-17

### Added
- **New:** Grafana Loki log-stack support (queries + log-burst/volume RCA + alert-log context).
- **Undo executor**: `undo list` / `undo apply <id>` (CLI + MCP) — apply a recorded replayable inverse; the dispatched inverse is re-gated by its own risk tier; single-use, dry-run, double-confirm, both wrapper + inverse audited.

## v0.2.1 — 2026-07-16

### Fixed
- **`secrets.enc` now follows `OBSERVABILITY_AIOPS_HOME`** (secretstore hardcoded the real
  home directory; config/audit/undo already relocated — found in live verification).
- **Audit fidelity**: failures sanitized into `{"error": ...}` results by the MCP error
  layer are now audited as `status=error` (they previously read as `ok`, hiding failed
  attempts from exception reports), and no undo is recorded for a call that failed.
- Undo replay fix: `update_dashboard` treats a 404 on the prior-fetch as create-mode, so `delete_dashboard`'s captured-model undo actually recreates the dashboard.

### Tests
- `doctor` and the `init` wizard are now fully covered (previously ~10–20%); plus a
  regression test for the sanitized-failure audit status.

## v0.2.0 — 2026-07-13

Security-hardening release from a line-wide code review.

### Changed (behavior)
- **Secure by default**: with no `rules.yaml`, high/critical operations now require a
  named approver (`OBSERVABILITY_AUDIT_APPROVED_BY`). A fresh install no longer allows
  destructive writes unattended; `init` seeds a starter `rules.yaml` you can edit,
  and an operator-authored rules file is honoured as-is.
- `__version__` is now single-sourced from package metadata (the previous release
  self-reported a stale version string).
- Sanitize docs no longer overstate scope: it strips control/format characters and
  truncates; semantic prompt-injection resistance must come from the consuming agent.

### Fixed
- Silence ids / dashboard UIDs / label paths are percent-encoded in REST URL paths (path-traversal hardening).

### Tests
- Governance persistence is now tested against REAL `audit.db`/`undo.db` files
  (write → audit row + inverse undo row with captured prior state).
- The CLI confirmed-write path (dry-run / double-confirm / governed execution) is
  covered end-to-end.
- `pytest-cov` added to the dev dependencies.

## v0.1.1

- Fix: `OBSERVABILITY_AIOPS_HOME` now also relocates `config.yaml` (was hardcoded to `~/.observability-aiops`).
- Fix: **CLI writes are now audited + undo-recorded** via the governance path — previously only the MCP tools recorded audit/undo; CLI `manage`/`remediate`/etc. writes now go through the same `@governed_tool` layer (they keep their dry-run + double-confirm). CLI write output is now the governed JSON result. No API/tool changes.


All notable changes to observability-aiops are documented here. This project adheres
to [Semantic Versioning](https://semver.org/).

## [0.1.0] — preview

Initial preview release: governed AI-ops for a **self-hosted observability
stack** — **Prometheus** (HTTP API + PromQL), **Alertmanager** (alerts +
silences), and **Grafana** (dashboards, datasources, folders) — with a bundled
governance harness. One config can span your whole stack.
**Mock-validated only — not yet verified against a live stack.**

### Added

- **30 MCP tools** (24 read, 6 write), every one wrapped with the bundled
  `@governed_tool` harness (audit, policy, token/runaway budget, undo,
  risk-tiers):
  - **Metrics (Prometheus, read)** — `instant_query`, `range_query`,
    `label_values`, `series_metadata`.
  - **Targets & status (read)** — `list_targets` (up/down filter),
    `target_scrape_health`, `dropped_targets`, `prometheus_config_status`,
    `prometheus_tsdb_status`.
  - **Rules (read)** — `list_rules` (recording + alerting), `rule_health`.
  - **Alerts (read)** — `firing_alerts`, `pending_alerts`, `alertmanager_alerts`,
    `list_silences`.
  - **Grafana (read)** — `list_dashboards`, `get_dashboard`, `list_datasources`,
    `datasource_health`, `list_folders`.
  - **Overview (read)** — `observability_overview` (platform-aware snapshot).
  - **Writes** — `create_silence` (med, time-boxed, undo→expire),
    `expire_silence` (med), `create_annotation` (low), `update_dashboard`
    (med, captures prior model, undo→restore), `delete_dashboard` (**high**,
    dry-run, captures prior model before delete, undo→recreate),
    `reload_prometheus_config` (med, records prior config hash).
- **Three flagship analyses** (read) — `firing_alert_rca` (join each firing alert
  to its rule expression → likely cause + action), `target_scrape_health_analysis`
  (rank down/erroring scrape targets and classify each `lastError`), and
  `alert_noise_and_flap_analysis` (frequently-repeated / duplicate alerts →
  dedup/rollup recommendation). Transparent heuristics that report their numbers.
- **Encrypted secret store** — Prometheus/Grafana bearer tokens stored encrypted
  in `~/.observability-aiops/secrets.enc` (Fernet + scrypt); never plaintext on
  disk. Legacy `OBSERVABILITY_<TARGET>_TOKEN` env var honoured as a fallback.
- **CLI** (`observability-aiops`) — `init` platform-picking wizard, `overview`,
  `query instant/range/labels`, `alert firing/silences/rca`, `secret`
  management, and a platform-aware `doctor` (Prometheus `/api/v1/status/buildinfo`,
  Grafana `/api/health`).

### Known limitations

- Preview / mock-only: the Prometheus and Grafana HTTP API responses are mocked
  and need live verification against a real stack. Both are free/open-source and
  trivial to run locally for a `doctor` check.
- Hosted/SaaS monitoring suites (Datadog, New Relic, enterprise NMS) are out of
  scope by design.
