<!-- mcp-name: io.github.AIops-tools/observability-aiops -->

# Observability AIops (preview)

> **Disclaimer**: Community-maintained open-source project. **Not affiliated with, endorsed by, or sponsored by the Prometheus or Grafana projects, Grafana Labs, or the Cloud Native Computing Foundation.** Prometheus, Alertmanager and Grafana are trademarks of their respective owners. MIT licensed.

Governed AI-ops for a **self-hosted observability stack** in one server —
**Prometheus** (HTTP API, PromQL, targets, rules, alerts), **Alertmanager**
(alerts + silences), **Grafana** (dashboards, datasources, folders), and
**Grafana Loki** (bounded LogQL log reads + log RCA) — with a **built-in
governance harness**: unified audit log, policy engine, token/runaway budget
guard, undo-token recording, and graduated-autonomy risk tiers. One config can
span your whole stack; each target names its own `platform`.
**Preview — mock-validated only, not yet verified against a live stack.**

This is the **self-hosted-observability** complement to enterprise monitoring
suites: it speaks the open Prometheus/Grafana APIs an SRE actually runs, not a
vendor NMS.

## What it does

Answers the questions an SRE actually repeats over a Prometheus/Grafana stack,
and guards the writes that follow:

- **PromQL + metadata** — instant and range queries, label-value enumeration, and
  series metadata, all read-only and result-capped.
- **Scrape-target & rule health** — which targets are up/down (and *why*, from
  `lastError`), which were dropped by relabeling, and which recording/alerting
  rules are erroring.
- **Alerts & silences** — firing/pending Prometheus rule alerts, Alertmanager's
  post-routing view, and its silences.
- **Grafana** — dashboards, datasources (+ health), and folders.
- **Loki logs** — bounded LogQL reads (label + label-value enumeration, a
  validation-gated `query_range`, and a canned error-tail), all read-only with a
  hard lookback + line cap, optional multi-tenant `X-Scope-OrgID`, and basic/bearer
  auth per target.
- **Flagship analyses** — transparent heuristics that show their numbers:
  `firing_alert_rca` (join each firing alert to its rule expr → cause + action),
  `target_scrape_health_analysis` (rank down/erroring scrapes → likely cause),
  `alert_noise_and_flap_analysis` (frequently-repeated / duplicate alerts →
  dedup/rollup recommendation), plus two **log** analyses — `log_error_burst_rca`
  (per-stream error burst vs baseline → new-signature / volume-spike /
  single-instance) and `log_volume_analysis` (top streams + high-cardinality label
  warnings + retention hint) — and `alert_log_context`, which correlates a firing
  Prometheus alert to its Loki streams.
- **Governed writes** — create/expire Alertmanager silences (time-boxed), create
  Grafana annotations, update/delete dashboards, and hot-reload the Prometheus
  config — each audited, risk-tiered, `dry_run`-able, and the reversible ones
  capture the **real fetched before-state** for undo.

## Capability matrix (37 MCP tools)

| Group | Platform | Tools | Count | R/W |
|-------|----------|-------|:-----:|:---:|
| **Metrics** | Prometheus | `instant_query`, `range_query`, `label_values`, `series_metadata` | 4 | read |
| **Targets** | Prometheus | `list_targets`, `target_scrape_health`, `dropped_targets` | 3 | read |
| **Status** | Prometheus | `prometheus_config_status`, `prometheus_tsdb_status` | 2 | read |
| **Rules** | Prometheus | `list_rules`, `rule_health` | 2 | read |
| **Alerts** | Prometheus/Alertmanager | `firing_alerts`, `pending_alerts`, `alertmanager_alerts`, `list_silences` | 4 | read |
| **Grafana** | Grafana | `list_dashboards`, `get_dashboard`, `list_datasources`, `datasource_health`, `list_folders` | 5 | read |
| **Loki** | Loki | `loki_labels`, `loki_label_values`, `loki_query`, `loki_tail_errors` | 4 | read |
| **Overview** | all | `observability_overview` | 1 | read |
| **Analyses** | Prometheus | `firing_alert_rca`, `target_scrape_health_analysis`, `alert_noise_and_flap_analysis` | 3 | read |
| **Log analyses** | Loki | `log_error_burst_rca`, `log_volume_analysis` | 2 | read |
| **Cross-signal** | Prometheus + Loki | `alert_log_context` | 1 | read |
| **Writes** | Alertmanager | `create_silence`, `expire_silence` | 2 | write (med) |
| | Grafana | `create_annotation` | 1 | write (low) |
| | Grafana | `update_dashboard` | 1 | write (med) |
| | Grafana | `delete_dashboard` | 1 | write (**high**) |
| | Prometheus | `reload_prometheus_config` | 1 | write (med) |

**Loki is read-only** — Loki exposes no safe operational write surface (no
silence/annotation analogue), so this tool deliberately ships no Loki writes.

The CLI exposes a convenience subset (`query`, `logs`, `alert`, `overview`, …);
the full 37-tool surface is via the MCP server.

## Quick start

```bash
uv tool install observability-aiops          # or: pipx install observability-aiops
observability-aiops init                     # wizard: pick platform (prometheus/grafana) + store the token (encrypted)
observability-aiops doctor                   # verify config, secrets, connectivity
observability-aiops overview                 # snapshot: firing alerts + targets up/down + rules erroring
observability-aiops query instant 'up'       # run a PromQL instant query
observability-aiops logs errors '{app="api"}' # tail error-level Loki logs (bounded)
observability-aiops alert rca                # root-cause the firing alerts
```

Run as an MCP server (stdio):

```bash
export OBSERVABILITY_AIOPS_MASTER_PASSWORD=...   # unlock secrets non-interactively
observability-aiops mcp
```

## Governance

Every MCP tool passes through the bundled `@governed_tool` harness:

- **Audit** — every call (params, result, status, duration, risk tier, approver,
  rationale) is logged to `~/.observability-aiops/audit.db` (relocatable via
  `OBSERVABILITY_AIOPS_HOME`).
- **Budget / runaway guard** — token and call budgets trip a circuit breaker on
  tight poll/retry loops.
- **Risk tiers** — graduated autonomy; high-risk ops (`delete_dashboard`) can
  require a named approver (`OBSERVABILITY_AUDIT_APPROVED_BY` /
  `OBSERVABILITY_AUDIT_RATIONALE`).
- **Undo recording** — reversible writes capture the real before-state and record
  an inverse descriptor (`create_silence`→expire, `update_dashboard`/
  `delete_dashboard`→restore the captured prior model).

## Supported scope & limitations

- **Platforms**: Prometheus HTTP API (+ a companion Alertmanager), Grafana HTTP
  API, and Grafana Loki HTTP API (read-only). Hosted/SaaS monitoring suites
  (Datadog, New Relic, enterprise NMS) are deliberately **out of scope** for this
  tool.
- **Preview / mock-only.** All behaviour is validated against mocked
  Prometheus/Grafana/Alertmanager/Loki responses. All are free and open-source and
  trivial to stand up in a lab (`docker run prom/prometheus`, `grafana/grafana`,
  `grafana/loki`), so `observability-aiops doctor` is the fastest live check
  (Prometheus `/api/v1/status/buildinfo`, Grafana `/api/health`, Loki `/ready` +
  `/loki/api/v1/status/buildinfo`).

## Missing a capability?

Want another read, an analysis tuned, or a platform capability that isn't here?
**Open an issue or a PR — feedback and contributions are welcome.**
