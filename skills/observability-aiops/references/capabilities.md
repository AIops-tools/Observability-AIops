# observability-aiops capability matrix

> Preview / mock-only. **30 MCP tools** (24 read, 6 write) across Prometheus
> (HTTP API + PromQL, default port 9090, optional bearer token), a companion
> Alertmanager (`/api/v2`, port 9093), and Grafana (HTTP API, port 3000, required
> bearer token). Responses are mocked and need live verification.

## Metrics — Prometheus (read)

| Tool | API path | Returns |
|------|----------|---------|
| `instant_query` | `/api/v1/query` | PromQL evaluated at one instant (samples: metric + value + timestamp) |
| `range_query` | `/api/v1/query_range` | PromQL over a time range (per-series point arrays) |
| `label_values` | `/api/v1/label/<name>/values` | distinct values of a label (default `__name__` = all metric names) |
| `series_metadata` | `/api/v1/series` | series (label-set) metadata for a selector |

## Targets & status — Prometheus (read)

| Tool | API path | Returns |
|------|----------|---------|
| `list_targets` | `/api/v1/targets` | active scrape targets (job, instance, health, lastError), optional up/down filter |
| `target_scrape_health` | `/api/v1/targets` | up/down summary + the unhealthy targets |
| `dropped_targets` | `/api/v1/targets` | targets discovered but dropped by relabeling |
| `prometheus_config_status` | `/api/v1/status/config` | running-config fingerprint (sha256) + size — never the raw YAML/secrets |
| `prometheus_tsdb_status` | `/api/v1/status/tsdb` | TSDB head cardinality + top metrics by series count |

## Rules — Prometheus (read)

| Tool | API path | Returns |
|------|----------|---------|
| `list_rules` | `/api/v1/rules` | recording + alerting rules (name, type, expr, health), optional type filter |
| `rule_health` | `/api/v1/rules` | rule-evaluation health summary + erroring rules |

## Alerts — Prometheus + Alertmanager (read)

| Tool | API path | Returns |
|------|----------|---------|
| `firing_alerts` | `/api/v1/alerts` | firing Prometheus rule alerts, grouped by severity |
| `pending_alerts` | `/api/v1/alerts` | pending (not-yet-firing) rule alerts |
| `alertmanager_alerts` | AM `/api/v2/alerts` | alerts as Alertmanager sees them (post grouping/silence/inhibit) |
| `list_silences` | AM `/api/v2/silences` | silences (active, pending, expired) with matchers |

## Grafana (read)

| Tool | API path | Returns |
|------|----------|---------|
| `list_dashboards` | `/api/search?type=dash-db` | dashboards (uid, title, folder, tags), optional title query |
| `get_dashboard` | `/api/dashboards/uid/{uid}` | one dashboard's summary (title, version, panel + tag counts) |
| `list_datasources` | `/api/datasources` | datasources (id, uid, name, type, default flag) |
| `datasource_health` | `/api/datasources/{id}/health` | one datasource's health (status, message) |
| `list_folders` | `/api/folders` | Grafana folders |

## Overview & flagship analyses (read)

| Tool | Inputs | Returns |
|------|--------|---------|
| `observability_overview` | platform-aware | Prometheus: firing count + targets up/down + rules erroring; Grafana: dashboard/datasource/folder counts |
| `firing_alert_rca` | firing alerts + alerting rules | each firing alert joined to its rule expr, ranked by severity, mapped to a likely **cause + action** |
| `target_scrape_health_analysis` | active targets | down/erroring scrapes ranked, each `lastError` classified (refused/timeout/auth/DNS/TLS) with a fix |
| `alert_noise_and_flap_analysis` | alert instances | alertnames with many instances / exact duplicates flagged with a group_by / inhibition / longer-`for` recommendation |

## Writes (governed)

| Tool | Risk | API path | Notes |
|------|------|----------|-------|
| `create_silence` | **med** | AM `POST /api/v2/silences` | **time-boxed** (requires minutes > 0); returns silenceId; undo → `expire_silence` |
| `expire_silence` | **med** | AM `DELETE /api/v2/silence/{id}` | inverse of create_silence |
| `create_annotation` | **low** | `POST /api/annotations` | Grafana event marker |
| `update_dashboard` | **med** | `POST /api/dashboards/db` | GETs the prior model first → captures it for a restore undo |
| `delete_dashboard` | **HIGH** | `DELETE /api/dashboards/uid/{uid}` | `dry_run` + approver; captures prior model **BEFORE** delete; undo → recreate |
| `reload_prometheus_config` | **med** | `POST /-/reload` | records the pre-reload config hash; no undo (re-apply the prior config file) |

## Out of scope (by design)

- **Hosted/SaaS monitoring** — Datadog, New Relic, and enterprise NMS (only
  self-hosted Prometheus + Grafana here)
- **Creating/editing Prometheus rules or scrape config**, and provisioning
  Grafana datasources/dashboards from scratch (beyond update/delete of an existing
  dashboard)
- **Long-term-storage query fan-out** (Thanos/Cortex/Mimir) — the single
  Prometheus HTTP API only
