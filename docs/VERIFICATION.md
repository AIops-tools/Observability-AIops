# Live verification

`observability-aiops` has been **exercised against a live stack** — Prometheus
**3.x**, **Alertmanager**, and **Grafana 13** — in addition to its mock test
suite. This document records exactly what that run covered, what it did **not**,
and the checklist any further live run should follow. It is deliberately
checklist-shaped so the result is reproducible and auditable — not a subjective
"seems fine".

**Scope of the claim**: the Prometheus, Alertmanager and Grafana surfaces (reads,
the three metric RCAs, the silence and dashboard governed writes, and undo
replay) were run against that stack and behaved as the mock suite predicts. The
**Grafana Loki** surface — bounded LogQL reads and the two log analyses — has
**not** been exercised live and is mock-only so far.

## What the mock suite already guarantees

- Every module imports; the CLI builds; every MCP tool carries the
  `@governed_tool` harness marker (`tests/test_smoke.py`).
- The five flagship analyses are unit-tested against synthetic payloads:
  `firing_alert_rca` (alert joined to its rule expression → cause + action),
  `target_scrape_health_analysis` (`lastError` classified as connection refused /
  timeout / auth / DNS / TLS), `alert_noise_and_flap_analysis` (duplicate and
  high-instance alertnames → group_by / inhibition / longer-`for` advice),
  `log_error_burst_rca` (per-stream counts vs a baseline window), and
  `log_volume_analysis` (top streams + high-cardinality labels).
- Loki reads are **bounded by construction**: a stream selector is required, and
  lookback and line count are hard-capped. There is no Loki write surface.
- Reversible writes record the correct inverse: `create_silence` → expire,
  `update_dashboard` → restore the fetched prior model, `delete_dashboard` →
  recreate from the model captured **before** the delete. Silences are
  time-boxed (a positive duration is required).
- Governance persistence: audited rows land in the SQLite audit DB, and the
  secure-by-default approver gate refuses high-risk writes (`delete_dashboard`)
  with no `rules.yaml` and no `OBSERVABILITY_AUDIT_APPROVED_BY`.

## Prerequisites for a live run

Everything needed is free and open-source, which is what made the recorded run
easy — this is the cheapest tool in the line to verify:

```bash
docker run -d -p 9090:9090 prom/prometheus
docker run -d -p 9093:9093 prom/alertmanager
docker run -d -p 3000:3000 grafana/grafana
docker run -d -p 3100:3100 grafana/loki     # to close the remaining gap
```

- A Grafana **service-account token** (required) and, if Prometheus is secured,
  a bearer token (self-hosted Prometheus is often unauthenticated).
- At least one alerting rule that will actually fire, and a **throwaway
  dashboard** you are willing to edit and delete. Never verify against a
  production Grafana org.

```bash
uv tool install observability-aiops
observability-aiops init       # asks for the platform; encrypted secret store
```

## Verification checklist

Boxes marked ✅ were confirmed against **Prometheus 3.x + Alertmanager +
Grafana 13**. Unticked boxes are open — record them as gaps rather than silently
passing.

### 1. Connectivity (the fastest live gate)
- [x] ✅ `observability-aiops doctor` → green for Prometheus
      (`/api/v1/status/buildinfo`) and Grafana (`/api/health`), with the
      encrypted secret store unlocking correctly.
- [ ] `doctor` green for a Loki target (`/ready` +
      `/loki/api/v1/status/buildinfo`) — **open gap**.

### 2. Reads return real, well-shaped data
- [x] ✅ `observability-aiops overview` → real firing counts, target health, and
      rule health matching the Prometheus UI.
- [x] ✅ `observability-aiops query instant 'up'` and
      `observability-aiops query range 'up' --start <t0> --end <t1> --step 60s`
      → real samples; the range result matches the Prometheus graph.
- [x] ✅ `observability-aiops query labels` → real metric names; `series_metadata`
      returns real series.
- [x] ✅ `list_targets` / `target_scrape_health` / `dropped_targets` → the actual
      scrape targets and their up/down state.
- [x] ✅ `list_rules` / `rule_health` → the real rule groups and evaluation health.
- [x] ✅ `observability-aiops alert firing`, `pending_alerts`,
      `alertmanager_alerts`, `observability-aiops alert silences` → real alerts
      and silences from both Prometheus and Alertmanager.
- [x] ✅ `list_dashboards` / `get_dashboard` / `list_datasources` /
      `datasource_health` / `list_folders` → real Grafana objects.
- [x] ✅ `prometheus_config_status` / `prometheus_tsdb_status` → the config
      Prometheus actually loaded, and real TSDB cardinality figures.
- [ ] `observability-aiops logs labels` / `logs query '<logql>'` /
      `logs errors '<selector>'` against a real Loki — **open gap**.

### 3. The flagship analyses hold up against real telemetry
- [x] ✅ `observability-aiops alert rca` → with alerts deliberately made to fire,
      the RCA joined each to its rule expression and named a defensible cause and
      action; the cited numbers matched the alert's own expression evaluated by
      hand via `query instant`.
- [x] ✅ `target_scrape_health_analysis` → with a scrape target deliberately
      broken, the `lastError` was classified correctly and the suggested fix was
      the right one.
- [x] ✅ `alert_noise_and_flap_analysis` → duplicate/high-instance alertnames were
      identified with sensible group_by / `for` recommendations.
- [ ] `log_error_burst_rca` and `log_volume_analysis` against real Loki streams
      — **open gap** (both are mock-tested only).
- [ ] `alert_log_context <alertname>` mapping a real firing alert's labels onto a
      real Loki stream selector — **open gap**.

### 4. A reversible write + its undo (governance closes the loop)
- [x] ✅ `create_silence` with `dry_run=True` → previewed only; for real → the
      silence appeared in Alertmanager, the result carried an `_undo_id`, and a
      row landed in `~/.observability-aiops/audit.db`.
- [x] ✅ `observability-aiops undo apply <id>` → the recorded inverse
      (`expire_silence`) ran and the silence was expired. **An undo-replay bug
      was found by this very run**, fixed, and is now covered by a regression
      test.
- [x] ✅ `update_dashboard` for real → Grafana showed the new model; `undo apply`
      restored the **captured** prior model, not a reconstruction.
- [x] ✅ `create_annotation` → the annotation appeared on the Grafana timeline.
- [x] ✅ `expire_silence` directly → the silence ended immediately.

### 5. The destructive write is gated and recoverable
- [x] ✅ `delete_dashboard <uid>` with `dry_run=True` → previewed only.
- [x] ✅ `delete_dashboard` for real → refused until
      `OBSERVABILITY_AUDIT_APPROVED_BY` named an approver (secure-by-default);
      once approved, the dashboard was deleted, the audit row was tagged `high`
      with the approver and `OBSERVABILITY_AUDIT_RATIONALE`, and `undo apply`
      recreated the dashboard from the model captured **before** the delete.
- [ ] `reload_prometheus_config` against a live Prometheus with a deliberately
      changed scrape config — **open gap** (the reload endpoint was not
      exercised live).

### 6. Governance actually gates
- [x] ✅ Secure-by-default: with no `~/.observability-aiops/rules.yaml`, the
      high-risk write was denied without a named approver.
- [x] ✅ Relocation: with `OBSERVABILITY_AIOPS_HOME` set, `audit.db`, the undo
      store, and `secrets.enc` all land under that directory.
- [ ] A tight poll loop trips the runaway budget guard rather than hammering the
      Prometheus API (verified in the mock suite; not re-run live).

### 7. Cleanup
- [x] ✅ Test silences expired, the test dashboard restored/removed, and every
      step above present in the audit DB.

## Criteria to consider it live-verified

1. Every checklist box is ticked against a real stack, and the component
   versions are recorded. **Current status: satisfied for Prometheus 3.x +
   Alertmanager + Grafana 13 across sections 1-7, except the Loki boxes and
   `reload_prometheus_config`.**
2. Any field-shape mismatch found during a run is fixed and covered by a
   regression test. **Current status: satisfied — the undo-replay bug found in
   the live run was fixed and has a regression test.**
3. The run is written up with the date and package version, matching how the
   product line records its other live-verified tools. **Current status:
   satisfied.**

The remaining open boxes are the honest edge of the claim: the **entire Loki
surface** (bounded reads, `log_error_burst_rca`, `log_volume_analysis`,
`alert_log_context`) and `reload_prometheus_config` have **not** been exercised
against a live server.

## Notes for maintainers

- `observability-aiops doctor` is the single fastest live entry point; start there.
- To close the Loki gap: run `grafana/loki` with a log producer (promtail or a
  container writing to stdout), add a `platform: loki` target, then work through
  the section 2 and 3 Loki boxes. Confirm the stream-selector gate and the
  lookback/line caps actually refuse an unbounded query — a rejected query is
  the guard working, and that behaviour is part of what needs verifying.
- To close the reload gap: change a scrape config on disk, call
  `reload_prometheus_config`, and confirm via `prometheus_config_status` that
  Prometheus loaded the new file — and that a **broken** config is rejected,
  leaving the previous config running.
- Because this stack is trivial to run locally, prefer re-running the whole
  checklist on a version bump rather than trusting the previous result.
