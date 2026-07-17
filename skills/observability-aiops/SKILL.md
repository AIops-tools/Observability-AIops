---
name: observability-aiops
description: >
  Use this skill whenever the user needs to operate a self-hosted observability stack on Prometheus (HTTP API + PromQL), Alertmanager, Grafana, or Grafana Loki (logs) — a one-shot overview, PromQL instant/range queries, label + series metadata, scrape-target health (up/down + why) and dropped targets, recording/alerting rule health, firing/pending alerts, Alertmanager alerts + silences, Grafana dashboards/datasources/folders, bounded Loki LogQL log reads (labels, query, error-tail), five flagship analyses (firing-alert RCA, target-scrape-health, alert-noise/flap, log-error-burst RCA, log-volume/cardinality) plus an alert->log cross-signal, and guarded writes (create/expire silence, create annotation, update/delete dashboard, reload Prometheus config).
  Always use this skill for "Prometheus", "PromQL", "Alertmanager", "Grafana", "Loki", "LogQL", "logs", "which targets are down", "scrape failing", "why is this alert firing", "root cause this alert", "firing alerts", "silence this alert", "noisy alerts", "alert flapping", "recording rule", "alerting rule", "dashboard", "datasource health", "reload prometheus config", "TSDB cardinality", "error burst", "log volume", "log cardinality", "tail errors" when the context is a self-hosted metrics/logs/observability stack.
  Do NOT use when the target is something other than a Prometheus/Grafana observability stack (a hypervisor, storage appliance, backup product, container-orchestrator control plane, network device config, or OT/industrial equipment) — route those to the appropriate other AIops-tools skill. Hosted/SaaS monitoring suites (Datadog, New Relic, enterprise NMS) are out of scope.
  Preview — governed observability operations with a built-in governance harness (audit, policy, token budget, undo, risk-tiers). Mock-validated only; Prometheus and Grafana are free/open-source and trivial to run locally for a live check.
installer:
  kind: uv
  package: observability-aiops
argument-hint: "[a PromQL query, an alert/dashboard uid, or describe your observability task]"
allowed-tools:
  - Bash
metadata: {"openclaw":{"requires":{"env":["OBSERVABILITY_AIOPS_CONFIG"],"bins":["observability-aiops"],"config":["~/.observability-aiops/config.yaml","~/.observability-aiops/secrets.enc"]},"optional":{"env":["OBSERVABILITY_AIOPS_MASTER_PASSWORD"]},"primaryEnv":"OBSERVABILITY_AIOPS_CONFIG","homepage":"https://github.com/AIops-tools/Observability-AIops","emoji":"📈","os":["macos","linux"]}}
compatibility: >
  Standalone, self-governed observability operations across Prometheus (HTTP API + PromQL, default port 9090, optional bearer token), a companion Alertmanager (/api/v2, default port 9093), Grafana (HTTP API, default port 3000, required bearer token), and Grafana Loki (HTTP API, default port 3100, optional bearer or basic auth, optional multi-tenant X-Scope-OrgID) — preview. Loki is READ-ONLY: bounded LogQL reads only (labels, label values, query_range with a hard lookback + line cap and a stream-selector gate, a canned error-tail), with no write surface. Each target in the config names its own platform, so one config can span the whole stack. The governance harness (audit, policy, token/runaway budget, undo, risk-tiers) is bundled in the package — no external skill-family dependency.
  All write operations are audited to a local SQLite DB under ~/.observability-aiops/ (relocatable via OBSERVABILITY_AIOPS_HOME).
  Credentials: the Grafana service-account/API token (required) or the Prometheus bearer token (optional; self-hosted Prometheus is often unauthenticated) is stored ENCRYPTED in ~/.observability-aiops/secrets.enc (Fernet/AES-128 + scrypt-derived key) — never plaintext on disk. Run 'observability-aiops init' to onboard (it asks for the platform), or 'observability-aiops secret set <target>' to add one. The store is unlocked by a master password from OBSERVABILITY_AIOPS_MASTER_PASSWORD (non-interactive/MCP/CI) or an interactive prompt (CLI on a TTY). A legacy plaintext env var OBSERVABILITY_<TARGET_NAME_UPPER>_TOKEN is still honoured as a fallback with a deprecation warning (migrate with 'observability-aiops secret migrate'). The token is sent as an Authorization: Bearer header and held only in memory; secrets are never logged or echoed.
  PromQL is used only through read endpoints (/api/v1/query, /query_range) — there is no write query path. State-changing operations pass through the @governed_tool decorator (pre-check + budget guard + audit + risk-tier gate). The destructive write (delete_dashboard) is high-risk with dry_run + an approver and captures the full prior dashboard model BEFORE deleting; reversible writes (update_dashboard, create_silence) capture the real fetched before-state and record an inverse undo descriptor. Silences are TIME-BOXED (create_silence requires a positive duration).
  Webhooks: none — no outbound network calls beyond the configured Prometheus / Alertmanager / Grafana endpoints.
  SSL: verify_ssl defaults to true; disable for self-signed lab certs.
  Transitive dependencies: httpx (HTTP client) and the MCP SDK. No post-install scripts or background services.
  PREVIEW: mock-validated only. Prometheus and Grafana are free/open-source (docker run prom/prometheus, grafana/grafana) so a live 'doctor' check is easy.
---

# Observability AIops (preview)

> **Disclaimer**: Community-maintained open-source project, **not affiliated with, endorsed by, or sponsored by the Prometheus or Grafana projects, Grafana Labs, or the CNCF.** Prometheus, Alertmanager and Grafana are trademarks of their respective owners. Source at [github.com/AIops-tools/Observability-AIops](https://github.com/AIops-tools/Observability-AIops) under the MIT license.

Governed self-hosted observability operations — **37 MCP tools** across
**Prometheus** (HTTP API + PromQL), **Alertmanager** (alerts + silences),
**Grafana** (dashboards, datasources, folders), and **Grafana Loki** (bounded
LogQL log reads + log RCA, read-only), every one wrapped with the bundled
`@governed_tool` harness: a local unified audit log under
`~/.observability-aiops/`, policy engine, token/runaway budget guard, undo-token
recording, and graduated-autonomy risk tiers. One config can span the whole
stack. Bearer tokens are stored **encrypted** (`~/.observability-aiops/secrets.enc`,
Fernet + scrypt) — never plaintext on disk.

This is the **self-hosted-observability** complement to enterprise monitoring
suites: it speaks the open Prometheus/Grafana APIs an SRE actually runs.

> **Standalone**: the governance harness is bundled in the package
> (`observability_aiops.governance`) — no external skill-family dependency.
> **Preview / mock-only**: Prometheus and Grafana are free/open-source and
> trivial to run in a lab, so a live `doctor` check is easy.

## What This Skill Does

| Group | Platform | Tools | Count | R/W |
|-------|----------|-------|:-----:|:---:|
| **Metrics** | Prometheus | instant_query, range_query, label_values, series_metadata | 4 | read |
| **Targets & status** | Prometheus | list_targets, target_scrape_health, dropped_targets, prometheus_config_status, prometheus_tsdb_status | 5 | read |
| **Rules** | Prometheus | list_rules, rule_health | 2 | read |
| **Alerts** | Prometheus/Alertmanager | firing_alerts, pending_alerts, alertmanager_alerts, list_silences | 4 | read |
| **Grafana** | Grafana | list_dashboards, get_dashboard, list_datasources, datasource_health, list_folders | 5 | read |
| **Loki** | Loki | loki_labels, loki_label_values, loki_query, loki_tail_errors | 4 | read |
| **Overview + analyses** | all | observability_overview + firing_alert_rca, target_scrape_health_analysis, alert_noise_and_flap_analysis | 4 | read |
| **Log analyses + cross-signal** | Loki (+ Prometheus) | log_error_burst_rca, log_volume_analysis, alert_log_context | 3 | read |
| **Writes** | Alertmanager/Grafana/Prometheus | create_silence, expire_silence (med) · create_annotation (low) · update_dashboard (med) · delete_dashboard (**high**) · reload_prometheus_config (med) | 6 | write |

The three metric flagship analyses are transparent heuristics that report their
numbers: `firing_alert_rca` joins each firing alert to its rule expression and
maps it to a cause + action; `target_scrape_health_analysis` ranks down/erroring
scrape targets and classifies each `lastError`; `alert_noise_and_flap_analysis`
finds noisy/duplicate alerts and recommends a dedup/rollup. The two **log**
analyses mirror this: `log_error_burst_rca` compares per-stream error counts
against a baseline window and classifies each burst (new signature / volume spike
/ single-instance); `log_volume_analysis` ranks the highest-volume streams and
warns on high-cardinality (high-churn) labels. `alert_log_context` bridges the two
signals — it maps a firing Prometheus alert's labels to a Loki stream selector and
pulls the correlated logs. **Loki is read-only** (no safe write surface).

## Quick Install

```bash
uv tool install observability-aiops
observability-aiops init       # wizard: pick platform (prometheus/grafana) + encrypted token
observability-aiops doctor
```

## When to Use This Skill

- Get a snapshot (`overview` / `observability_overview`): firing-alert count,
  scrape targets up/down, rules erroring (Prometheus) or dashboard/datasource
  counts (Grafana)
- Run PromQL (`instant_query` / `range_query`), enumerate `label_values` or
  `series_metadata`
- Check scrape health (`target_scrape_health`, `dropped_targets`) and rule health
  (`rule_health`, `list_rules`)
- Triage alerts: `firing_alerts` / `pending_alerts`, the Alertmanager view
  (`alertmanager_alerts`, `list_silences`), then `firing_alert_rca` to root-cause
- Reduce alert noise (`alert_noise_and_flap_analysis`) → group_by / inhibition /
  longer `for`
- Grafana: `list_dashboards`, `get_dashboard`, `list_datasources`,
  `datasource_health`, `list_folders`
- Loki logs: enumerate `loki_labels` / `loki_label_values`, run a bounded
  `loki_query` (LogQL, stream selector required), `loki_tail_errors` for a
  selector; then `log_error_burst_rca` to root-cause an error burst and
  `log_volume_analysis` for volume/cardinality; `alert_log_context` to pull the
  logs behind a firing alert
- Governed writes: silence an alert (`create_silence`, time-boxed), annotate an
  event (`create_annotation`), update/delete a dashboard (dry_run + approver for
  delete), or hot-reload Prometheus (`reload_prometheus_config`)

**Do NOT use when** the target is not a Prometheus/Grafana observability stack —
route hypervisor, storage, backup, container-orchestrator, network-device-config,
or OT/industrial work to the appropriate other AIops-tools skill. Hosted/SaaS
monitoring suites (Datadog, New Relic, enterprise NMS) are out of scope.

## Related Skills — Skill Routing

| If the user wants… | Use |
|--------------------|-----|
| Prometheus / Alertmanager / Grafana observability ops | **observability-aiops** (this skill) |
| A different platform (hypervisor, storage, backup, orchestrator, network config, OT edge) | the appropriate **other AIops-tools** skill |
| Hosted/SaaS monitoring (Datadog, New Relic, enterprise NMS) | out of scope for this tool |

## Common Workflows

### Root-cause the firing alerts

1. `firing_alerts` → what is firing now, grouped by severity
2. `firing_alert_rca` → each firing alert joined to its rule expr with a likely
   cause + recommended action (advisory heuristic — verify against logs)
3. Silence the noise while you fix it: `create_silence` (time-boxed) on a matcher

### Investigate a scrape gap

1. `target_scrape_health` → up/down counts + the unhealthy targets
2. `target_scrape_health_analysis` → down targets ranked, each `lastError`
   classified (connection refused / timeout / auth / DNS / TLS) with a fix
3. `dropped_targets` if a target is missing entirely (relabeled away)

### Tame a noisy alert

1. `alert_noise_and_flap_analysis` → alertnames with many instances / exact
   duplicates, each with a group_by / inhibition / longer-`for` recommendation
2. `list_silences` / `create_silence` to quiet it now

### Root-cause a log error burst (Loki)

1. `alert_log_context <alertname>` → the firing alert's labels mapped to a Loki
   stream selector + the correlated error logs (or start from a selector directly)
2. `log_error_burst_rca <selector>` → per-stream error counts vs a baseline
   window, each burst classified (new signature / volume spike / single-instance)
3. `log_volume_analysis <selector>` → the highest-volume streams and any
   high-cardinality labels driving a stream/index explosion

### Safely change a Grafana dashboard (reversible)

1. `get_dashboard <uid>` → confirm the target dashboard
2. `update_dashboard <model>` — it fetches + stashes the prior model and records a
   restore undo, or `delete_dashboard <uid> --dry-run` → preview
3. Re-run without `--dry-run` (set `OBSERVABILITY_AUDIT_APPROVED_BY` +
- **Secure by default (v0.2.0+)**: with no `~/.observability-aiops/rules.yaml`, high/critical operations are denied unless `OBSERVABILITY_AUDIT_APPROVED_BY` names an approver (set `OBSERVABILITY_AUDIT_RATIONALE` too). `observability-aiops init` seeds a starter rules.yaml; an operator-authored rules file is honoured as-is.
   `OBSERVABILITY_AUDIT_RATIONALE` for the high-risk delete) — the prior model is
   captured before delete so the recorded undo can recreate it

## Governance & Safety

- Every tool is audited to `~/.observability-aiops/audit.db` (relocatable via
  `OBSERVABILITY_AIOPS_HOME`).
- The high-risk op (`delete_dashboard`) can require a named approver: set
  `OBSERVABILITY_AUDIT_APPROVED_BY` and `OBSERVABILITY_AUDIT_RATIONALE`.
- Every write supports `dry_run`; the destructive one adds an approver gate.
- Silences are **time-boxed** (require a positive duration). Reversible writes
  capture the real fetched before-state and record an inverse descriptor
  (create_silence→expire, update/delete dashboard→restore/recreate).

## References

- `references/capabilities.md` — full tool + platform + API-path reference
- `references/cli-reference.md` — CLI command reference
- `references/setup-guide.md` — onboarding, credentials, and connectivity
