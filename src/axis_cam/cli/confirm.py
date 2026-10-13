"""Write safety for commands that change a device.

Every command that writes follows one shape, so a user learns it once and
restore (Phase 5) can reuse it:

1. read the current state and build a :class:`WritePlan` in plain words;
2. show it; with ``--dry-run`` stop there (exit 0, nothing contacted for writing);
3. otherwise ask ``Apply this change?`` unless ``--yes`` was given — declining
   exits 1;
4. apply, verify, and print what the device reports afterwards.

Secrets for the device (new passwords) are never taken from argv: they come
from a hidden prompt or, for automation, from standard input.
"""

import sys
from dataclasses import dataclass, field

import typer
from rich.panel import Panel

from axis_cam.cli.app import console


@dataclass(frozen=True)
class WritePlan:
    """What a write command is about to do, in words a human can check.

    Attributes:
        target: Device label (name or host).
        action: One sentence in the imperative: ``Create account 'ops' ...``.
        context: Facts the decision depends on (current accounts, roles).
        warnings: Consequences worth a second look (self-lockout, last admin).
    """

    target: str
    action: str
    context: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


def show_plan(plan: WritePlan) -> None:
    """Render a plan as a panel."""
    lines = [f"[bold]Device:[/bold]  {plan.target}", f"[bold]Change:[/bold]  {plan.action}"]
    lines.extend(f"[dim]Context:[/dim] {line}" for line in plan.context)
    lines.extend(f"[yellow]Warning:[/yellow] {line}" for line in plan.warnings)
    console.print(Panel("\n".join(lines), title="Planned change", border_style="yellow"))


def confirm_write(plan: WritePlan, *, yes: bool, dry_run: bool) -> bool:
    """Show the plan and decide whether to apply it.

    Args:
        plan: The change about to be made.
        yes: Skip the interactive confirmation.
        dry_run: Show the plan only.

    Returns:
        ``True`` to apply, ``False`` for a dry run (the caller exits 0).

    Raises:
        typer.Abort: The user declined; Typer exits with status 1.
    """
    show_plan(plan)
    if dry_run:
        console.print("[yellow]Dry run:[/yellow] no changes made.")
        return False
    if yes:
        return True
    return typer.confirm("Apply this change?", default=False, abort=True)


def read_secret(label: str, *, from_stdin: bool, confirm: bool = True) -> str:
    """Obtain a secret without it ever appearing in argv.

    Args:
        label: Prompt text, e.g. ``"New password"``.
        from_stdin: Read one line from standard input instead of prompting
            (for scripts: ``echo "$PW" | axiscam ... --password-stdin``).
        confirm: Ask twice when prompting interactively.

    Returns:
        The secret, without its trailing newline.

    Raises:
        typer.BadParameter: Standard input was empty.
    """
    if from_stdin:
        secret = sys.stdin.readline().rstrip("\r\n")
        if not secret:
            raise typer.BadParameter(f"{label} expected on standard input (--password-stdin)")
        return secret
    return typer.prompt(label, hide_input=True, confirmation_prompt=confirm)
