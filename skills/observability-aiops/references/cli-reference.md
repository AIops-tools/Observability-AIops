# observability-aiops CLI reference

> Preview / mock-only. Covers Prometheus (HTTP API + PromQL), a companion
> Alertmanager, and Grafana (HTTP API); responses are mocked and need live
> verification. The CLI is a convenience subset — the full 30-tool surface is via
> the MCP server (`observability-aiops mcp`).

## Setup & diagnostics

```bash
observability-aiops init                      # interactive wizard (asks for the platform: prometheus/grafana)
observability-aiops doctor [--skip-auth]      # config + secret store + connectivity
                                           #   Prometheus: /api/v1/status/buildinfo · Grafana: /api/health
observability-aiops mcp                       # start the MCP server (stdio transport)
```

## Secrets (encrypted store ~/.observability-aiops/secrets.enc)

```bash
observability-aiops secret set <target> [--value <token>]   # store bearer token (hidden prompt if no --value)
observability-aiops secret list                             # names only — secrets never shown
observability-aiops secret rm <target>
observability-aiops secret migrate                          # import legacy plaintext env (OBSERVABILITY_<TARGET>_TOKEN)
observability-aiops secret rotate-password                  # re-encrypt under a new master password
```

## Overview

```bash
observability-aiops overview [--target <t>]   # snapshot: firing alerts + targets up/down + rules erroring (Prometheus)
                                           #   or dashboard/datasource/folder counts (Grafana)
```

## Query (Prometheus PromQL)

```bash
observability-aiops query instant 'up'                      # PromQL instant query
observability-aiops query range 'rate(x[5m])' --start ... --end ... [--step 60s]
observability-aiops query labels [__name__]                 # distinct label values (default = all metric names)
```

## Alerts

```bash
observability-aiops alert firing [--target <t>]             # firing Prometheus rule alerts, by severity
observability-aiops alert silences [--target <t>]           # Alertmanager silences
observability-aiops alert rca [--target <t>]                # root-cause firing alerts (join to rule expr → cause+action)
```

## Common options

- `--target, -t <name>` — target name from `config.yaml` (omit to use the
  default/first target); each target declares its own `platform`
- `overview`, `query`, and `alert` are the CLI subset; the remaining metrics,
  targets, rules, Grafana, and governed-write tools (create/expire silence,
  create annotation, update/delete dashboard, reload config) are exposed through
  the MCP server. High-risk MCP writes honour `OBSERVABILITY_AUDIT_APPROVED_BY` /
  `OBSERVABILITY_AUDIT_RATIONALE` and support dry-run.
