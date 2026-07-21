# Security Policy

## Disclaimer

Community-maintained open-source project. **Not affiliated with, endorsed by, or
sponsored by the Prometheus or Grafana projects, Grafana Labs, or the CNCF.**
Prometheus, Alertmanager and Grafana are trademarks of their respective owners.
Source is auditable under the MIT license.

## Reporting Vulnerabilities

Report privately via a GitHub Security Advisory on
[github.com/AIops-tools/Observability-AIops](https://github.com/AIops-tools/Observability-AIops/security/advisories)
or email zhouwei008@gmail.com. Please do not open public issues for security
reports.

## Security Design

### Credential Management
- Per-target bearer tokens — the Grafana service-account/API token (required) or
  the Prometheus bearer token (optional; many self-hosted deployments are
  unauthenticated) — live **encrypted** in `~/.observability-aiops/secrets.enc`
  (Fernet/AES-128 + scrypt-derived key; chmod 600), never in `config.yaml` and
  never in source. The master password is never stored — only a per-store random
  salt and the ciphertext are on disk.
- A legacy plaintext env var `OBSERVABILITY_<TARGET_NAME_UPPER>_TOKEN` is still
  honoured as a fallback with a deprecation warning (migrate with
  `observability-aiops secret migrate`).
- The token is held only in memory, sent as an `Authorization: Bearer` header,
  and never logged or echoed. The config file holds only platform, scheme, host,
  port, TLS setting, and an optional Alertmanager URL. PromQL is used only through
  read endpoints (`/api/v1/query`, `/query_range`) — there is no write query path.

### Governed Operations
Every MCP tool runs through the bundled `@governed_tool` harness
(`observability_aiops.governance`):
- **Audit** — every call logged to a local SQLite DB under `~/.observability-aiops/`
  (relocatable via `OBSERVABILITY_AIOPS_HOME`), agent-attributed, secret-redacted.
- **Token/runaway budget** — hard ceilings (`OBSERVABILITY_MAX_TOOL_CALLS` /
  `OBSERVABILITY_MAX_TOOL_SECONDS`) plus an on-by-default guard that trips a tight
  poll/retry loop, preventing unbounded API consumption.
- **Risk tier** — a descriptive label carried into the audit row from each
  tool's declared `risk_level`; it does not gate the call. Whether a write is
  permitted is the connecting account's permissions or the agent's judgement.
- **Undo-token recording** — reversible writes capture the real fetched BEFORE
  state and record an inverse descriptor (e.g. `create_silence`→`expire_silence`,
  `update_dashboard`/`delete_dashboard`→restore the captured prior model) so the
  change can be rolled back.

### State-Changing Operations
The destructive write — `delete_dashboard` — is `risk_level=high`, accepts a
`dry_run` preview, and captures the full prior dashboard model **before**
deleting. `OBSERVABILITY_AUDIT_APPROVED_BY` + `OBSERVABILITY_AUDIT_RATIONALE`
optionally annotate the audit row — the write runs whether or not they are
set. Medium-risk
writes (`create_silence`/`expire_silence`, `update_dashboard`,
`reload_prometheus_config`) are audited and `dry_run`-able; silences are
**time-boxed** (require a positive duration, no open-ended silencing).
`create_annotation` is `risk_level=low`. Reversible writes capture before-state
and record an undo token.

### SSL/TLS Verification
`verify_ssl` defaults to true; disable only for self-signed lab certificates.

### Prompt-Injection Protection
All server-returned text (metric labels, alert messages, rule expressions,
dashboard titles, scrape errors) is passed through a `sanitize()` truncate +
control-character strip before reaching the agent.

### Network Scope
No webhooks, no telemetry, no outbound calls beyond the configured Prometheus,
Alertmanager, and Grafana API endpoints. No post-install scripts or background
services.

## Static Analysis

```bash
uvx bandit -r observability_aiops/ mcp_server/
uv run ruff check .
```

## Supported Versions

The latest released version receives security fixes. This is a preview (0.x);
pin a version in production.
