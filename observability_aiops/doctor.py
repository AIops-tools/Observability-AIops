"""Environment and connectivity diagnostics for Observability AIops."""

from __future__ import annotations

from rich.console import Console

from observability_aiops.config import (
    CONFIG_FILE,
    ENV_FILE,
    PLATFORM_GRAFANA,
    PLATFORM_LOKI,
    PLATFORM_PROMETHEUS,
    TOKEN_REQUIRED,
    load_config,
)
from observability_aiops.secretstore import SECRETS_FILE, check_permissions, has_store

_console = Console()


def run_doctor(skip_auth: bool = False) -> int:
    """Check config, secrets, and (optionally) connectivity.

    Returns a process exit code: 0 healthy, 1 problems found. Connectivity
    failures are reported as status, never raised as tracebacks (a doctor must
    survive the thing it diagnoses being unhealthy).
    """
    problems = 0

    if not CONFIG_FILE.exists():
        _console.print(f"[red]✗ Config file missing: {CONFIG_FILE}[/]")
        _console.print("[yellow]  Run 'observability-aiops init' to set up your first target.[/]")
        return 1
    _console.print(f"[green]✓ Config file present: {CONFIG_FILE}[/]")

    try:
        config = load_config()
    except Exception as exc:  # noqa: BLE001 — report, do not crash
        _console.print(f"[red]✗ Config load failed: {exc}[/]")
        return 1

    if not config.targets:
        _console.print("[red]✗ No targets configured[/]")
        return 1
    _console.print(f"[green]✓ {len(config.targets)} target(s) configured[/]")

    if has_store():
        _console.print(f"[green]✓ Encrypted secret store present: {SECRETS_FILE}[/]")
        perm_warning = check_permissions()
        if perm_warning:
            _console.print(f"[yellow]! {perm_warning}[/]")
    elif ENV_FILE.exists():
        _console.print(
            f"[yellow]! Using legacy plaintext .env ({ENV_FILE}). Migrate with "
            f"'observability-aiops secret migrate'.[/]"
        )
    else:
        _console.print(
            "[yellow]! No secret store yet. Run 'observability-aiops init' to set up "
            "credentials (stored encrypted).[/]"
        )

    for target in config.targets:
        try:
            token = target.secret
        except OSError as exc:
            _console.print(f"[red]✗ {exc}[/]")
            problems += 1
            continue
        if token:
            _console.print(f"[green]✓ Token present for '{target.name}' ({target.platform})[/]")
        elif target.platform in TOKEN_REQUIRED:
            _console.print(f"[red]✗ Missing required token for '{target.name}'[/]")
            problems += 1
        else:
            _console.print(
                f"[dim]· No token for '{target.name}' ({target.platform}) — "
                f"assuming unauthenticated.[/]"
            )

    if skip_auth:
        _console.print("[dim]Skipping connectivity check (--skip-auth).[/]")
        return 1 if problems else 0

    from observability_aiops.connection import ConnectionManager

    mgr = ConnectionManager(config)
    for target in config.targets:
        try:
            conn = mgr.connect(target.name)
            if target.platform == PLATFORM_PROMETHEUS:
                conn.prom_get("/api/v1/status/buildinfo")
                detail = "Prometheus HTTP API OK"
            elif target.platform == PLATFORM_LOKI:
                conn.loki_get("/ready")
                conn.loki_get("/loki/api/v1/status/buildinfo")
                detail = "Loki HTTP API OK"
            elif target.platform == PLATFORM_GRAFANA:
                conn.graf_get("/api/health")
                detail = "Grafana HTTP API OK"
            else:  # pragma: no cover — config validation prevents this
                detail = "OK"
            _console.print(
                f"[green]✓ Connected to '{target.name}' ({target.platform} "
                f"{target.host}) — {detail}[/]"
            )
        except Exception as exc:  # noqa: BLE001 — connectivity is a status, not a crash
            _console.print(f"[red]✗ Connect to '{target.name}' failed: {exc}[/]")
            problems += 1

    return 1 if problems else 0
