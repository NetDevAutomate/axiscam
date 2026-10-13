"""Typer application objects shared by every command module.

Command modules import ``app`` (or their group's Typer) from here and register
their commands with decorators; :mod:`axis_cam.cli` imports the command modules,
which is what populates the application.
"""

import asyncio
import json
from collections.abc import Coroutine
from typing import Any

import typer
from rich.console import Console

from axis_cam.exceptions import AxisError

# Console for rich output
console = Console()

# Main Typer app
app = typer.Typer(
    name="axiscam",
    help="CLI tool for managing AXIS cameras and devices via VAPIX API.",
    no_args_is_help=True,
    # Local variables in a traceback would include the device password.
    pretty_exceptions_show_locals=False,
)

logs_app = typer.Typer(
    name="logs",
    help="Retrieve logs from AXIS devices.",
    no_args_is_help=True,
)
app.add_typer(logs_app, name="logs")

network_app = typer.Typer(
    name="network",
    help="Network configuration commands.",
    no_args_is_help=True,
)
app.add_typer(network_app, name="network")

security_app = typer.Typer(
    name="security",
    help="Security configuration commands (firewall, SSH, certificates).",
    no_args_is_help=True,
)
app.add_typer(security_app, name="security")

services_app = typer.Typer(
    name="services",
    help="Service configuration commands (SNMP, NTP).",
    no_args_is_help=True,
)
app.add_typer(services_app, name="services")

download_app = typer.Typer(
    name="download",
    help="Download the server report and the crash report (0600 files).",
    no_args_is_help=True,
)
app.add_typer(download_app, name="download")

automation_app = typer.Typer(
    name="automation",
    help="Automation configuration commands (action rules, MQTT).",
    no_args_is_help=True,
)
app.add_typer(automation_app, name="automation")

media_app = typer.Typer(
    name="media",
    help="Media configuration commands (recording, storage).",
    no_args_is_help=True,
)
app.add_typer(media_app, name="media")

stream_app = typer.Typer(
    name="stream",
    help="Stream diagnostics commands (RTSP, RTP, profiles).",
    no_args_is_help=True,
)
app.add_typer(stream_app, name="stream")

accounts_app = typer.Typer(
    name="accounts",
    help="User accounts: list, add, set-password, set-role, remove.",
    no_args_is_help=True,
)
app.add_typer(accounts_app, name="accounts")

backup_app = typer.Typer(
    name="backup",
    help="Configuration backups: create, show, verify.",
    no_args_is_help=True,
)
app.add_typer(backup_app, name="backup")


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine synchronously, reporting AXIS errors cleanly.

    API modules let authentication and connection errors propagate rather
    than masking them as empty or default-valued results. This is the single
    place they become a one-line message and exit status 1 for every command.

    Args:
        coro: Coroutine to run.

    Returns:
        Result of the coroutine.

    Raises:
        typer.Exit: With status 1 when the device raised an AxisError.
    """
    try:
        return asyncio.run(coro)
    except AxisError as e:
        console.print(f"[red]Error:[/red] {e}", style="bold")
        raise typer.Exit(1) from None


def emit_json(data: Any) -> None:
    """Print ``data`` as indented JSON for machines.

    Deliberately not ``console.print``: Rich soft-wraps at the console width
    and interprets ``[...]`` as markup, both of which corrupt piped JSON.
    """
    typer.echo(json.dumps(data, indent=2))


def main() -> None:
    """Entry point for the CLI.

    ``run_async`` reports device errors raised inside commands; this is the
    backstop for ones raised outside it (e.g. config loading). ``SystemExit``
    rather than ``typer.Exit`` because Typer's handler is no longer on the
    stack here.
    """
    try:
        app()
    except AxisError as e:
        console.print(f"[red]Error:[/red] {e}", style="bold")
        raise SystemExit(1) from None
