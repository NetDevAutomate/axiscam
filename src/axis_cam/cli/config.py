"""Configuration-file commands: config, init, migrate, devices, version."""

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table
from rich.tree import Tree

from axis_cam.cli.app import (
    app,
    console,
)
from axis_cam.config import (
    create_default_config,
    get_config_dir,
    get_config_file,
    load_config,
)
from axis_cam.files import write_private


@app.command("config")
def show_config():
    """Show current configuration."""
    config = load_config()

    tree = Tree("[bold]Configuration[/bold]")

    # General settings
    settings = tree.add("[cyan]Settings[/cyan]")
    settings.add(f"Default Device: {config.default_device or '(none)'}")
    settings.add(f"Timeout: {config.timeout}s")
    settings.add(f"Config File: {get_config_file()}")

    # Devices
    devices = tree.add("[cyan]Devices[/cyan]")
    if config.devices:
        for name, dev in config.devices.items():
            dev_branch = devices.add(f"[green]{name}[/green]")
            dev_branch.add(f"Host: {dev.host}")
            dev_branch.add(f"Type: {dev.device_type}")
            dev_branch.add(f"Port: {dev.port}")
            if dev.name:
                dev_branch.add(f"Name: {dev.name}")
    else:
        devices.add("[dim](no devices configured)[/dim]")

    console.print(tree)


@app.command("init")
def init_config(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing config"),
    ] = False,
):
    """Initialize configuration file with defaults."""
    config_file = get_config_file()
    config_dir = get_config_dir()

    if config_file.exists() and not force:
        console.print(
            f"[yellow]Config file already exists:[/yellow] {config_file}",
        )
        console.print("Use --force to overwrite")
        raise typer.Exit(1)

    # Create config directory
    config_dir.mkdir(parents=True, exist_ok=True)

    # The config file is where device credentials end up: owner-only from the start.
    write_private(config_file, create_default_config().encode())
    console.print(f"[green]Created config file:[/green] {config_file} (0600)")


@app.command("version")
def show_version():
    """Show version information."""
    from axis_cam import __version__

    console.print(f"axiscam version {__version__}")


def complete_device_names() -> list[str]:
    """Completion for device names from config."""
    try:
        config = load_config()
        return list(config.devices.keys())
    except Exception:  # shell completion must never raise; no names is the right answer
        return []


@app.command("devices")
def list_devices():
    """List all configured devices."""
    config = load_config()

    if not config.devices:
        console.print("[yellow]No devices configured[/yellow]")
        console.print("Run 'axiscam init' to create a configuration file")
        return

    table = Table(title="Configured Devices")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Host", style="white")
    table.add_column("Port", style="dim")
    table.add_column("Friendly Name", style="white")

    for name, dev in config.devices.items():
        default_marker = " *" if name == config.default_device else ""
        table.add_row(
            f"{name}{default_marker}",
            dev.device_type,
            dev.host,
            str(dev.port),
            dev.name or "-",
        )

    console.print(table)
    if config.default_device:
        console.print("\n[dim]* = default device[/dim]")


@app.command("migrate")
def migrate_config():
    """Migrate configuration from legacy path to new path.

    Copies configuration from ~/.config/axis/ to ~/.config/axiscam/
    if the legacy path exists and the new path doesn't.
    """
    import shutil

    from platformdirs import user_config_dir

    legacy_dir = Path(user_config_dir("axis"))
    new_dir = Path(user_config_dir("axiscam"))

    legacy_config = legacy_dir / "config.yaml"
    new_config = new_dir / "config.yaml"

    if not legacy_config.exists():
        console.print(f"[yellow]No legacy config found at:[/yellow] {legacy_config}")
        return

    if new_config.exists():
        console.print(f"[yellow]Config already exists at:[/yellow] {new_config}")
        console.print("Use 'axiscam init --force' to overwrite")
        return

    # Create new directory
    new_dir.mkdir(parents=True, exist_ok=True)

    # Copy config file
    shutil.copy2(legacy_config, new_config)

    # Set secure permissions (owner read/write only)
    new_config.chmod(0o600)

    # Also copy .env if it exists
    legacy_env = legacy_dir / ".env"
    if legacy_env.exists():
        new_env = new_dir / ".env"
        shutil.copy2(legacy_env, new_env)
        new_env.chmod(0o600)
        console.print("[green]Copied .env file[/green]")

    console.print(f"[green]Config migrated to:[/green] {new_config}")
    console.print("\n[dim]Legacy config preserved at original location.[/dim]")
    console.print("[dim]Delete ~/.config/axis/ manually when ready.[/dim]")
