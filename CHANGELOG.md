# Changelog

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
