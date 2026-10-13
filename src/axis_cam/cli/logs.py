"""``axiscam logs``: system, access, audit and combined logs, plus search."""

from typing import Annotated

import typer

from axis_cam.auth import AuthMode
from axis_cam.cli.app import (
    console,
    logs_app,
    run_async,
)
from axis_cam.cli.context import resolve_device_config
from axis_cam.cli.options import (
    AuthOption,
    DeviceOption,
    HostOption,
    LinesOption,
    PasswordOption,
    PortOption,
    UsernameOption,
)
from axis_cam.models import LogType


@logs_app.command("system")
def logs_system(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    lines: LinesOption = 20,
):
    """Get system logs from the device."""
    _get_logs(device, host, username, password, port, LogType.SYSTEM, lines, auth)


@logs_app.command("access")
def logs_access(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    lines: LinesOption = 20,
):
    """Get access logs from the device."""
    _get_logs(device, host, username, password, port, LogType.ACCESS, lines, auth)


@logs_app.command("audit")
def logs_audit(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    lines: LinesOption = 20,
):
    """Get audit logs from the device."""
    _get_logs(device, host, username, password, port, LogType.AUDIT, lines, auth)


@logs_app.command("all")
def logs_all(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    lines: LinesOption = 50,
):
    """Get all logs from the device."""
    _get_logs(device, host, username, password, port, LogType.ALL, lines, auth)


@logs_app.command("search")
def logs_search(
    pattern: Annotated[str, typer.Argument(help="Search pattern")],
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    lines: LinesOption = 50,
):
    """Search logs for a pattern."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _search_logs():
        async with target.open() as dev:
            report = await dev.logs.search_logs(pattern, max_entries=lines)

            console.print(
                f"[bold]Search Results for '{pattern}'[/bold]",
                f" ({len(report.entries)} matches)",
            )

            if not report.entries:
                console.print("[yellow]No matching log entries[/yellow]")
                return

            for entry in report.entries:
                _print_log_entry(entry)

    run_async(_search_logs())


def _get_logs(
    device: str | None,
    host: str | None,
    username: str | None,
    password: str | None,
    port: int | None,
    log_type: LogType,
    lines: int | None,
    auth: AuthMode = AuthMode.AUTO,
):
    """Internal function to retrieve and display logs."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _fetch_logs():
        async with target.open() as dev:
            report = await dev.logs.get_logs(log_type, max_entries=lines)

            console.print(
                f"[bold]{log_type.value.title()} Logs[/bold]",
                f" from {target.host} ({len(report.entries)} entries, via {report.source})",
            )

            if not report.entries:
                console.print("[yellow]No log entries found[/yellow]")
                return

            for entry in report.entries:
                _print_log_entry(entry)

    run_async(_fetch_logs())


def _print_log_entry(entry):
    """Print a single log entry with formatting."""
    level_colors = {
        "error": "red",
        "err": "red",
        "warning": "yellow",
        "warn": "yellow",
        "info": "blue",
        "debug": "dim",
        "notice": "green",
    }

    level = str(entry.level.value if hasattr(entry.level, "value") else entry.level).lower()
    color = level_colors.get(level, "white")

    timestamp = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S") if entry.timestamp else "-"
    process = f"[dim]{entry.process}[/dim]" if entry.process else ""

    console.print(
        f"[dim]{timestamp}[/dim] [{color}]{level.upper():7}[/{color}] {process} {entry.message}"
    )
