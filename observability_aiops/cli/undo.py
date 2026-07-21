"""``observability-aiops undo`` — list recorded undo tokens and apply them.

Real execution is delegated to the ``@governed_tool``-wrapped functions in
``mcp_server.tools.undo`` so an applied undo is audited on the SAME governance
path as any other write (the inverse tool it dispatches is itself re-gated).
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

from observability_aiops.cli._common import (
    DryRunOption,
    TargetOption,
    cli_errors,
    console,
    double_confirm,
    dry_run_preview,
    warn_if_truncated,
)

undo_app = typer.Typer(
    name="undo",
    help="List recorded undo tokens and apply their inverse operations.",
    no_args_is_help=True,
)

UndoIdArg = Annotated[str, typer.Argument(help="Undo id from 'undo list'")]


@undo_app.command("list")
@cli_errors
def undo_list_cmd(
    limit: Annotated[int, typer.Option("--limit", help="Max tokens to show")] = 50,
    target: TargetOption = None,
) -> None:
    """List recorded, not-yet-applied undo tokens."""
    from mcp_server.tools import undo as gov

    result = gov.undo_list(limit=limit, target=target)
    console.print_json(json.dumps(result))
    warn_if_truncated(result)


@undo_app.command("apply")
@cli_errors
def undo_apply_cmd(
    undo_id: UndoIdArg, target: TargetOption = None, dry_run: DryRunOption = False
) -> None:
    """Apply a recorded undo (dispatches its inverse tool; dry-run + confirm)."""
    from mcp_server.tools import undo as gov

    if dry_run:
        preview = gov.undo_apply(undo_id=undo_id, dry_run=True, target=target)
        would = preview.get("wouldApply", {}) if isinstance(preview, dict) else {}
        params = dict(would.get("params", {}))
        # effectVerified is a real field off the governed preview, not a guess:
        # False means the original write lost its response, so this inverse may
        # have nothing to restore. A CLI preview that hides it invites reporting
        # a restore that never happened.
        if isinstance(preview, dict) and "effectVerified" in preview:
            params["effectVerified"] = preview["effectVerified"]
        dry_run_preview(
            preview,
            operation="undo_apply",
            api_call=f"inverse: {would.get('tool', '?')}",
            parameters=params,
        )
        return
    double_confirm("apply undo", undo_id)
    console.print_json(json.dumps(gov.undo_apply(undo_id=undo_id, target=target)))
