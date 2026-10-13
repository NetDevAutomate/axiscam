"""``axiscam backup``: create, inspect and verify configuration backups.

A backup is a directory with a manifest (see :mod:`axis_cam.backup`). ``create``
reads the device and never writes to it; ``show`` and ``verify`` work on the
directory alone and need no device.
"""

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from axis_cam.backup import BackupManifest, create_backup, load_manifest, verify_backup
from axis_cam.cli.app import backup_app, console, emit_json, run_async
from axis_cam.cli.context import resolve_device_config
from axis_cam.cli.options import (
    DeviceOption,
    DigestOption,
    HostOption,
    JsonOption,
    PasswordOption,
    PortOption,
    UsernameOption,
)

BackupDirArgument = Annotated[
    Path,
    typer.Argument(help="Backup directory (the one containing manifest.json).", exists=True),
]


def _size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def _print_manifest(manifest: BackupManifest, backup_dir: Path) -> None:
    identity = Table(title=f"Backup: {backup_dir}", show_header=False)
    identity.add_column("Field", style="cyan")
    identity.add_column("Value", style="white")
    identity.add_row("Created", manifest.created_at)
    identity.add_row(
        "Tool", f"{manifest.tool.get('name', '?')} {manifest.tool.get('version', '?')}"
    )
    for key, value in manifest.device.items():
        identity.add_row(key.replace("_", " ").title(), value)
    identity.add_row("Restore", manifest.restore)
    console.print(identity)

    files = Table(title=f"Files ({len(manifest.files)})")
    files.add_column("Section", style="cyan")
    files.add_column("File", style="white")
    files.add_column("Size", style="white", justify="right")
    files.add_column("Source", style="dim")
    for entry in manifest.files:
        files.add_row(entry.section, entry.file, _size(entry.size), entry.source)
    console.print(files)

    if manifest.errors:
        console.print(f"[yellow]Failed to read ({len(manifest.errors)}):[/yellow]")
        for section, message in manifest.errors.items():
            console.print(f"  {section}: {message}")
    if manifest.skipped:
        console.print(f"[dim]Not advertised by the device: {', '.join(manifest.skipped)}[/dim]")

    console.print("[bold]Not included — VAPIX offers no way to read these:[/bold]")
    for line in manifest.not_included.get("by_design", []):
        console.print(f"  • {line}")
    console.print("[bold]Not included — not read by this version:[/bold]")
    for line in manifest.not_included.get("not_implemented", []):
        console.print(f"  • {line}")


@backup_app.command("create")
def backup_create(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    digest: DigestOption = True,
    output: Annotated[
        Path,
        typer.Option(
            "--output", "-o", help="Parent directory; the backup directory is created inside it."
        ),
    ] = Path(),
    with_server_report: Annotated[
        bool,
        typer.Option(
            "--with-server-report", help="Also download the server report (zip with image)."
        ),
    ] = False,
):
    """Back up everything the device lets us read into a new directory.

    Reads only; nothing on the device changes. The manifest lists what was
    read and - as importantly - what a VAPIX backup cannot contain.
    """
    target = resolve_device_config(device, host, username, password, port, digest=digest)

    async def _create():
        async with target.open() as dev:
            with console.status(f"[bold blue]Backing up {target.host}...[/bold blue]"):
                return await create_backup(
                    dev,
                    output,
                    name=device or target.host,
                    include_server_report=with_server_report,
                )

    backup_dir, manifest = run_async(_create())
    console.print(
        f"[green]Backup written:[/green] {backup_dir} ({len(manifest.files)} files, 0600)"
    )
    if manifest.errors:
        console.print(f"[yellow]{len(manifest.errors)} module(s) failed to read:[/yellow]")
        for section, message in manifest.errors.items():
            console.print(f"  {section}: {message}")
    if manifest.skipped:
        console.print(f"[dim]Not advertised by the device: {', '.join(manifest.skipped)}[/dim]")
    console.print(
        "[dim]Not included by design: passwords, private keys, ACAP binaries, recordings "
        "— see manifest.json for the full list.[/dim]"
    )


@backup_app.command("show")
def backup_show(backup_dir: BackupDirArgument, json_output: JsonOption = False):
    """Show a backup's manifest: what it holds and what it does not."""
    try:
        manifest = load_manifest(backup_dir)
    except FileNotFoundError:
        console.print(f"[red]Error:[/red] no manifest.json in {backup_dir}", style="bold")
        raise typer.Exit(1) from None
    except (ValueError, KeyError) as exc:
        console.print(f"[red]Error:[/red] manifest.json is unreadable: {exc}", style="bold")
        raise typer.Exit(1) from None
    if json_output:
        emit_json(manifest.to_dict())
    else:
        _print_manifest(manifest, backup_dir)


@backup_app.command("verify")
def backup_verify(backup_dir: BackupDirArgument):
    """Re-hash every file in a backup against its manifest."""
    problems = verify_backup(backup_dir)
    if problems:
        console.print(f"[red]Backup is not intact:[/red] {len(problems)} problem(s)", style="bold")
        for problem in problems:
            console.print(f"  {problem}")
        raise typer.Exit(1)
    manifest = load_manifest(backup_dir)
    console.print(f"[green]Backup intact:[/green] {len(manifest.files)} files match the manifest")
