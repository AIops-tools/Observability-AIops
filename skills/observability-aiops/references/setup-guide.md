# observability-aiops setup & security guide

> Preview / mock-only — not yet validated against a live stack. **Prometheus and
> Grafana are both free/open-source and trivial to stand up in a lab
> (`docker run prom/prometheus`, `grafana/grafana`), so a live `doctor` check is
> easy.**

## 1. Install

```bash
uv tool install observability-aiops
```

## 2. Get a credential

- **Prometheus** — a bearer token is **optional**; many self-hosted deployments
  are unauthenticated. observability-aiops talks to the HTTP API on port **9090**
  and a companion Alertmanager on **9093** (`/api/v2`).
- **Grafana** — a **service-account token** (Administration → Service accounts →
  Add token) or legacy API key is **required**. Grafana's HTTP API is on port
  **3000**.

## 3. Onboard

```bash
observability-aiops init
```

The wizard asks, per target, for the **platform** (`prometheus` / `grafana`), the
**host**, the **scheme** (`http` / `https`), the **port** (defaults 9090 for
Prometheus, 3000 for Grafana), an optional **Alertmanager URL** (Prometheus
only), and the **token** — required for Grafana, optional for Prometheus.
Non-secret connection details go to `~/.observability-aiops/config.yaml`; the
token is stored **encrypted** into `~/.observability-aiops/secrets.enc`. Example
config (one config can span the whole stack):

```yaml
targets:
  - name: prod-prom
    platform: prometheus
    host: 10.0.0.20
    scheme: http
    port: 9090
    alertmanager_url: http://10.0.0.20:9093   # optional; blank assumes host:9093
  - name: prod-grafana
    platform: grafana
    host: 10.0.0.30
    scheme: https
    port: 3000
    verify_ssl: true
```

## 4. Non-interactive use (MCP server / CI / cron)

Export the master password so the encrypted store can be unlocked without a
prompt:

```bash
export OBSERVABILITY_AIOPS_MASTER_PASSWORD='your-master-password'
```

## Credential security

- The token is **never** written to disk in plaintext. It lives only in
  `~/.observability-aiops/secrets.enc`, encrypted with Fernet (AES-128-CBC +
  HMAC), the key derived from your master password via scrypt. Only a per-store
  random salt and the ciphertext are on disk (chmod 600); the master password
  itself is never stored.
- A legacy plaintext env var `OBSERVABILITY_<TARGET_NAME_UPPER>_TOKEN` is still
  honoured as a fallback with a deprecation warning — migrate with
  `observability-aiops secret migrate` (it imports then renames the old `.env`).
- The token is sent as an `Authorization: Bearer` header at request time and held
  only in memory; it is never logged or echoed. Exception text and tracebacks are
  scrubbed of secret-shaped strings before being written to the audit log.

## Governance harness state

State lives under `~/.observability-aiops/` (relocate with `OBSERVABILITY_AIOPS_HOME`):

- `audit.db` — every tool call (SQLite), with risk tier, approver, rationale
- `rules.yaml` — policy: deny rules, maintenance windows, approval tiers
- `undo.db` — inverse descriptors for reversible writes (create_silence→expire,
  update/delete dashboard→restore/recreate)
- budget / runaway guard — caps cumulative tool calls and wall-time; trips on
  tight poll/retry loops

## Governed writes

- **High-risk** op (`delete_dashboard`) requires an approver — set
  `OBSERVABILITY_AUDIT_APPROVED_BY` and `OBSERVABILITY_AUDIT_RATIONALE` — and
  supports `dry_run`. It captures the full prior dashboard model **before**
  deleting so the recorded undo can recreate it.
- **Reversible** writes capture the real fetched before-state:
  `update_dashboard` (restore prior model), `create_silence` (expire the created
  silence). `reload_prometheus_config` records the pre-reload config hash.
- **Time-boxed** ops require a positive duration: `create_silence` (in minutes).
  This prevents forgotten, indefinite silences.

## Verify

```bash
observability-aiops doctor
```

`doctor` is platform-aware: it checks the config file, the encrypted store and its
permissions, that a token is present where required, and (unless `--skip-auth`)
connectivity — `/api/v1/status/buildinfo` for Prometheus targets, `/api/health`
for Grafana targets.
