# Observability AIops v0.1.0 — preview

Governed AI-ops for a **self-hosted observability stack** — **Prometheus** (HTTP
API + PromQL), **Alertmanager** (alerts + silences), and **Grafana** (dashboards,
datasources, folders) — for AI agents, with a built-in governance harness (audit,
policy, token/runaway budget, undo-token recording, graduated risk tiers) and an
encrypted credential store. Standalone — no external skill-family dependency. One
config can span your whole stack.

Positioned as the **self-hosted-observability** complement to enterprise
monitoring suites: it speaks the open Prometheus/Grafana APIs directly.

> **Preview / mock-only.** All behaviour is validated against mocked
> Prometheus/Grafana/Alertmanager responses; it has not been run against a live
> stack. Both platforms are free and open-source and trivial to stand up in a lab
> (`docker run prom/prometheus`, `grafana/grafana`). The fastest live check is
> `observability-aiops doctor`.

## Highlights

- **30 MCP tools** (24 read, 6 write), every one wrapped with `@governed_tool`.
  - **Metrics (Prometheus)** — `instant_query`, `range_query`, `label_values`,
    `series_metadata`.
  - **Targets & status** — `list_targets`, `target_scrape_health`,
    `dropped_targets`, `prometheus_config_status`, `prometheus_tsdb_status`.
  - **Rules** — `list_rules`, `rule_health`.
  - **Alerts** — `firing_alerts`, `pending_alerts`, `alertmanager_alerts`,
    `list_silences`.
  - **Grafana** — `list_dashboards`, `get_dashboard`, `list_datasources`,
    `datasource_health`, `list_folders`.
  - **Overview** — `observability_overview` (platform-aware snapshot).
  - **Writes** — `create_silence`/`expire_silence` (med, time-boxed),
    `create_annotation` (low), `update_dashboard` (med),
    `delete_dashboard` (**high**), `reload_prometheus_config` (med).
- **Three flagship analyses** — transparent heuristics that show their numbers:
  `firing_alert_rca` (firing alert → rule expr → cause + action),
  `target_scrape_health_analysis` (down/erroring scrapes ranked + classified),
  and `alert_noise_and_flap_analysis` (noisy/duplicate alerts → dedup/rollup).
- **Encrypted secret store** (`~/.observability-aiops/secrets.enc`, Fernet +
  scrypt) — Prometheus/Grafana bearer tokens, never plaintext on disk; legacy
  `OBSERVABILITY_<TARGET>_TOKEN` env fallback.
- **Guarded writes** — the destructive op (`delete_dashboard`) requires dry-run +
  an approver; reversible writes capture the **real fetched before-state** and
  record an undo; silences are time-boxed (require a positive duration).
- **CLI** with an `init` platform-picking wizard, `secret` management, PromQL
  `query`, `alert` (firing/silences/rca), and a platform-aware `doctor`.

## Install

```bash
uv tool install observability-aiops
observability-aiops init       # pick platform (prometheus/grafana) + store the token
observability-aiops doctor
```

## Caveats

- Preview / mock-only: the Prometheus and Grafana HTTP API responses are mocked
  and need live verification.
- Hosted/SaaS monitoring suites (Datadog, New Relic, enterprise NMS) are out of
  scope by design.
