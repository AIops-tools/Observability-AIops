"""``observability-aiops init`` — a friendly, interactive onboarding wizard.

Walks a new user through connecting their first observability target: collects
the non-secret connection details into ``config.yaml`` and the bearer token into
the *encrypted* store (never plaintext on disk). Designed to be run on a
terminal; everything it needs is prompted with sensible defaults.
"""

from __future__ import annotations

import getpass

import typer
import yaml

from observability_aiops.cli._common import cli_errors, console
from observability_aiops.config import (
    AUTH_BASIC,
    AUTH_BEARER,
    CONFIG_DIR,
    CONFIG_FILE,
    DEFAULT_PORTS,
    PLATFORM_GRAFANA,
    PLATFORM_LOKI,
    PLATFORM_PROMETHEUS,
)
from observability_aiops.governance.paths import ops_path
from observability_aiops.secretstore import SecretStore, resolve_master_password

# Starter policy: keeps the secure-by-default gate (high/critical writes need a
# named approver) explicit and editable, and shows the other rule kinds.
DEFAULT_RULES_YAML = """\
# observability-aiops policy rules — hot-reloaded on change (no restart needed).
# Kinds: deny rules, maintenance_window, risk_tiers (graduated autonomy).

risk_tiers:
  - name: high-risk-requires-approver
    tier: dual
    min_risk_level: high
    reason: >-
      High/critical writes need a named human approver — set
      OBSERVABILITY_AUDIT_APPROVED_BY (and OBSERVABILITY_AUDIT_RATIONALE)
      before the call.

# deny:
#   - name: no-prod-dashboard-deletes
#     operations: ["delete_*"]
#     environments: ["production"]
#     reason: "Dashboard deletes in production go through change management."

# maintenance_window:
#   start: "22:00"
#   end: "06:00"
"""


def _write_default_rules() -> None:
    """Seed a starter rules.yaml (only when none exists) so the policy layer
    is explicit from day one; never overwrites an operator-authored file."""
    rules_path = ops_path("rules.yaml")
    if rules_path.exists():
        return
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(DEFAULT_RULES_YAML, "utf-8")
    console.print(f"[green]✓ Wrote default policy rules:[/] {rules_path}")


def _load_existing_targets() -> list[dict]:
    if not CONFIG_FILE.exists():
        return []
    raw = yaml.safe_load(CONFIG_FILE.read_text("utf-8")) or {}
    return list(raw.get("targets", []))


def _write_targets(targets: list[dict]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        CONFIG_DIR.chmod(0o700)
    except OSError:
        pass
    CONFIG_FILE.write_text(yaml.safe_dump({"targets": targets}, sort_keys=False), "utf-8")


@cli_errors
def init_cmd() -> None:
    """Interactively set up your first Prometheus, Grafana, or Loki connection."""
    console.print("[bold cyan]Observability AIops — setup wizard[/]")
    console.print(
        "This collects Prometheus, Grafana, or Loki connection details (saved to "
        "config.yaml) and the token — optional for a self-hosted Prometheus/Loki, "
        "required for Grafana — (saved [bold]encrypted[/] to secrets.enc).\n"
    )

    console.print("[bold]Step 1 — master password[/]")
    console.print(
        "[dim]Encrypts secrets.enc. You'll set it via the "
        "OBSERVABILITY_AIOPS_MASTER_PASSWORD env var for non-interactive/MCP use.[/]"
    )
    password = resolve_master_password(confirm_if_new=True)
    store = SecretStore.unlock(password)

    targets = _load_existing_targets()
    existing_names = {t.get("name") for t in targets}

    while True:
        console.print("\n[bold]Step 2 — add a target[/]")
        name = typer.prompt("Target name (e.g. prod-prom)").strip()
        if name in existing_names:
            if not typer.confirm(f"'{name}' already exists — overwrite?", default=False):
                continue
            targets = [t for t in targets if t.get("name") != name]

        platform = typer.prompt(
            f"Platform ({PLATFORM_PROMETHEUS} / {PLATFORM_GRAFANA} / {PLATFORM_LOKI})",
            default=PLATFORM_PROMETHEUS,
        ).strip().lower()
        if platform not in (PLATFORM_PROMETHEUS, PLATFORM_GRAFANA, PLATFORM_LOKI):
            console.print("[red]Platform must be 'prometheus', 'grafana', or 'loki'.[/]")
            continue

        host = typer.prompt("Host (IP or FQDN)").strip()
        scheme = typer.prompt("Scheme (http / https)", default="http").strip().lower()
        port = typer.prompt("Port", default=DEFAULT_PORTS[platform], type=int)
        verify_ssl = True
        if scheme == "https":
            verify_ssl = typer.confirm(
                "Verify TLS certificate? (No for self-signed lab certs)", default=True
            )

        entry = {
            "name": name,
            "platform": platform,
            "host": host,
            "scheme": scheme,
            "port": port,
            "verify_ssl": verify_ssl,
        }
        if platform == PLATFORM_PROMETHEUS:
            am_url = typer.prompt(
                "Alertmanager URL (optional; blank assumes host:9093)", default=""
            ).strip()
            if am_url:
                entry["alertmanager_url"] = am_url

        auth_type = AUTH_BEARER
        if platform == PLATFORM_LOKI:
            auth_type = typer.prompt(
                f"Auth type ({AUTH_BEARER} / {AUTH_BASIC})", default=AUTH_BEARER
            ).strip().lower()
            if auth_type not in (AUTH_BEARER, AUTH_BASIC):
                console.print("[red]Auth type must be 'bearer' or 'basic'.[/]")
                continue
            entry["auth_type"] = auth_type
            org_id = typer.prompt(
                "Multi-tenant org id (X-Scope-OrgID; blank for single-tenant)", default=""
            ).strip()
            if org_id:
                entry["org_id"] = org_id

        required = platform == PLATFORM_GRAFANA
        if platform == PLATFORM_GRAFANA:
            prompt = "Grafana API/service-account token"
        elif platform == PLATFORM_LOKI and auth_type == AUTH_BASIC:
            prompt = "Loki basic-auth credential 'user:password' (optional)"
        elif platform == PLATFORM_LOKI:
            prompt = "Loki bearer token (optional — blank if unauthenticated)"
        else:
            prompt = "Prometheus bearer token (optional — blank if unauthenticated)"
        token = getpass.getpass(f"{prompt} for '{name}' (hidden): ")
        if token:
            store = store.set(name, token)
        elif required:
            console.print("[red]Grafana requires a token. Aborting this target.[/]")
            continue

        targets.append(entry)
        existing_names.add(name)
        _write_targets(targets)
        console.print(
            f"[green]✓ Saved target '{name}' ({platform}"
            f"{', token encrypted' if token else ', no token'}).[/]"
        )

        if not typer.confirm("\nAdd another target?", default=False):
            break

    _write_default_rules()
    console.print(f"\n[green]✓ Setup complete.[/] Config: {CONFIG_FILE}")
    console.print(
        "[dim]Tip: export OBSERVABILITY_AIOPS_MASTER_PASSWORD=... in your shell profile "
        "so the MCP server and CLI can unlock secrets non-interactively.[/]"
    )
    if typer.confirm("Run a connectivity check now (observability-aiops doctor)?", default=True):
        from observability_aiops.doctor import run_doctor

        raise typer.Exit(run_doctor())
