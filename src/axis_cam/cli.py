"""Command-line interface for AXIS Camera Manager.

This module provides the main CLI using Typer, with commands for:
- Device information and status
- Log retrieval
- Configuration management

Usage:
    axiscam --help
    axiscam info --device camera1
    axiscam logs system --device camera1 --lines 50
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from axis_cam import AxisCamera, AxisIntercom, AxisRecorder, AxisSpeaker
from axis_cam.config import (
    AppConfig,
    DeviceConfig,
    create_default_config,
    get_config_dir,
    get_config_file,
    get_device_config,
    load_config,
)
from axis_cam.devices.base import AxisDevice
from axis_cam.models import DeviceType, LogType

# Console for rich output
console = Console()

# Main Typer app
app = typer.Typer(
    name="axiscam",
    help="CLI tool for managing AXIS cameras and devices via VAPIX API.",
    no_args_is_help=True,
)

# Logs subcommand group
logs_app = typer.Typer(
    name="logs",
    help="Retrieve logs from AXIS devices.",
    no_args_is_help=True,
)
app.add_typer(logs_app, name="logs")


# Type aliases for common options
DeviceOption = Annotated[
    str | None,
    typer.Option(
        "--device", "-d",
        help="Device name from config or host address.",
    ),
]

HostOption = Annotated[
    str | None,
    typer.Option(
        "--host", "-H",
        help="Device IP address or hostname (overrides --device).",
    ),
]

UsernameOption = Annotated[
    str | None,
    typer.Option(
        "--username", "-u",
        help="Authentication username.",
        envvar="AXIS_ADMIN_USERNAME",
    ),
]

PasswordOption = Annotated[
    str | None,
    typer.Option(
        "--password", "-p",
        help="Authentication password.",
        envvar="AXIS_ADMIN_PASSWORD",
    ),
]

PortOption = Annotated[
    int,
    typer.Option(
        "--port", "-P",
        help="HTTPS port number.",
    ),
]

LinesOption = Annotated[
    int | None,
    typer.Option(
        "--lines", "-n",
        help="Number of log entries to show.",
    ),
]

DigestOption = Annotated[
    bool,
    typer.Option(
        "--digest",
        help="Use Digest authentication instead of Basic.",
    ),
]


def get_device_class(device_type: str) -> type[AxisDevice]:
    """Get the appropriate device class for a device type.

    Args:
        device_type: Device type string.

    Returns:
        Device class for the type.
    """
    type_map: dict[str, type[AxisDevice]] = {
        "camera": AxisCamera,
        "recorder": AxisRecorder,
        "intercom": AxisIntercom,
        "speaker": AxisSpeaker,
    }
    return type_map.get(device_type.lower(), AxisCamera)


def resolve_device_config(
    device: str | None,
    host: str | None,
    username: str | None,
    password: str | None,
    port: int = 443,
) -> tuple[str, str, str, int, str]:
    """Resolve device connection parameters from options or config.

    Args:
        device: Device name from config.
        host: Direct host address.
        username: Username override.
        password: Password override.
        port: Port override.

    Returns:
        Tuple of (host, username, password, port, device_type).

    Raises:
        typer.Exit: If required parameters are missing.
    """
    device_type = "camera"

    # If host is provided directly, use it
    if host:
        if not username or not password:
            console.print(
                "[red]Error:[/red] Username and password required with --host",
                style="bold",
            )
            raise typer.Exit(1)
        return host, username, password, port, device_type

    # Try to load from config
    config = get_device_config(device)
    if config:
        return (
            config.host,
            username or config.username,
            password or config.password.get_secret_value(),
            port if port != 443 else config.port,
            config.device_type,
        )

    # Check if device name looks like a host
    if device and ("." in device or device.replace(".", "").isdigit()):
        if not username or not password:
            console.print(
                "[red]Error:[/red] Username and password required",
                style="bold",
            )
            raise typer.Exit(1)
        return device, username, password, port, device_type

    console.print(
        "[red]Error:[/red] No device specified. Use --device or --host",
        style="bold",
    )
    raise typer.Exit(1)


def run_async(coro):
    """Run an async coroutine synchronously.

    Args:
        coro: Coroutine to run.

    Returns:
        Result of the coroutine.
    """
    return asyncio.run(coro)


@app.command("info")
def device_info(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = False,
):
    """Get device information.

    Displays basic device info including model, serial number,
    firmware version, and available capabilities.
    """
    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )

    device_class = get_device_class(device_type)

    async def _get_info():
        async with device_class(host_addr, user, passwd, port_num, use_digest_auth=digest) as dev:
            info = await dev.get_info()
            capabilities = await dev.get_capabilities()

            # Time API may not be available on all devices (e.g., speakers)
            try:
                time_info = await dev.get_time_info()
            except Exception:
                time_info = None

            # Create info table
            table = Table(title=f"Device Info: {host_addr}", show_header=False)
            table.add_column("Property", style="cyan")
            table.add_column("Value", style="white")

            table.add_row("Brand", info.brand)
            table.add_row("Model", info.product_number)
            table.add_row("Product Name", info.product_full_name or "-")
            table.add_row("Serial Number", info.serial_number)
            table.add_row("Hardware ID", info.hardware_id or "-")
            table.add_row("Firmware", info.firmware_version)
            table.add_row("Architecture", info.architecture or "-")
            table.add_row("SoC", info.soc or "-")
            table.add_row("Device Type", device_type.capitalize())
            table.add_row("UTC Time", str(time_info.utc_time) if time_info else "-")
            table.add_row("Timezone", time_info.timezone if time_info else "-")

            console.print(table)

            # Show capabilities
            cap_table = Table(title="Capabilities", show_header=False)
            cap_table.add_column("Feature", style="cyan")
            cap_table.add_column("Status", style="white")

            cap_table.add_row(
                "PTZ Support",
                "[green]Yes[/green]" if capabilities.has_ptz else "[red]No[/red]",
            )
            cap_table.add_row(
                "Audio Support",
                "[green]Yes[/green]" if capabilities.has_audio else "[red]No[/red]",
            )
            cap_table.add_row(
                "I/O Support",
                "[green]Yes[/green]" if capabilities.has_io_ports else "[red]No[/red]",
            )
            cap_table.add_row(
                "Analytics",
                "[green]Yes[/green]" if capabilities.has_analytics else "[red]No[/red]",
            )
            cap_table.add_row(
                "APIs Available",
                str(len(capabilities.supported_apis)),
            )

            console.print(cap_table)

    run_async(_get_info())


@app.command("status")
def device_status(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = False,
):
    """Check device status and connectivity."""
    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )

    device_class = get_device_class(device_type)

    async def _check_status():
        async with device_class(host_addr, user, passwd, port_num, use_digest_auth=digest) as dev:
            status = await dev.get_status()

            panel = Panel(
                f"[green]Reachable[/green]" if status.reachable else "[red]Unreachable[/red]",
                title=f"Status: {host_addr}",
                subtitle=f"{status.model or 'Unknown Model'} ({status.device_type.value})",
            )
            console.print(panel)

            if status.reachable:
                table = Table(show_header=False)
                table.add_column("Property", style="cyan")
                table.add_column("Value", style="white")

                table.add_row("Serial", status.serial_number or "-")
                table.add_row("Firmware", status.firmware_version or "-")
                table.add_row("Device Time", str(status.current_time) if status.current_time else "-")

                console.print(table)

    run_async(_check_status())


@app.command("apis")
def list_apis(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = False,
):
    """List available APIs on the device."""
    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )

    device_class = get_device_class(device_type)

    async def _list_apis():
        async with device_class(host_addr, user, passwd, port_num, use_digest_auth=digest) as dev:
            capabilities = await dev.get_capabilities()

            tree = Tree(f"[bold]APIs on {host_addr}[/bold]")

            for api_name, api_info in sorted(capabilities.available_apis.items()):
                if isinstance(api_info, dict):
                    for version, details in api_info.items():
                        state = details.get("state", "unknown") if isinstance(details, dict) else "unknown"
                        state_color = "green" if state == "released" else "yellow" if state == "beta" else "red"
                        tree.add(f"{api_name} v{version} [{state_color}]{state}[/{state_color}]")
                else:
                    tree.add(f"{api_name}")

            console.print(tree)

    run_async(_list_apis())


@app.command("lldp")
def show_lldp(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = False,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
):
    """Show LLDP neighbor information.

    Displays discovered network neighbors via LLDP (Link Layer Discovery Protocol).
    Shows the switch/device the camera is connected to, including port information.
    """
    import json

    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )

    device_class = get_device_class(device_type)

    async def _show_lldp():
        async with device_class(host_addr, user, passwd, port_num, use_digest_auth=digest) as dev:
            lldp_info = await dev.get_lldp_info()

            if json_output:
                # Output as JSON
                data = {
                    "activated": lldp_info.activated,
                    "neighbors": [
                        {
                            "sys_name": n.sys_name,
                            "sys_descr": n.sys_descr,
                            "chassis_id": n.chassis_id.value,
                            "port_id": n.port_id.value,
                            "port_descr": n.port_descr,
                            "if_name": n.if_name,
                            "mgmt_ip": n.mgmt_ip,
                            "ttl": n.ttl,
                            "protocol": n.protocol,
                        }
                        for n in lldp_info.neighbors
                    ],
                }
                console.print(json.dumps(data, indent=2))
                return

            # Status panel
            status = "[green]Enabled[/green]" if lldp_info.activated else "[red]Disabled[/red]"
            console.print(Panel(f"LLDP Status: {status}", title=f"LLDP Info: {host_addr}"))

            if not lldp_info.neighbors:
                console.print("[yellow]No LLDP neighbors discovered[/yellow]")
                return

            # Neighbor table
            table = Table(title=f"LLDP Neighbors ({len(lldp_info.neighbors)} found)")
            table.add_column("System Name", style="cyan")
            table.add_column("Model", style="white")
            table.add_column("Chassis ID", style="dim")
            table.add_column("Port", style="green")
            table.add_column("Interface", style="white")

            for neighbor in lldp_info.neighbors:
                table.add_row(
                    neighbor.sys_name or "-",
                    neighbor.sys_descr or "-",
                    neighbor.chassis_id.value,
                    f"{neighbor.port_id.value} ({neighbor.port_descr})" if neighbor.port_descr else neighbor.port_id.value,
                    neighbor.if_name or "-",
                )

            console.print(table)

    run_async(_show_lldp())


@app.command("params")
def list_params(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = False,
    group: Annotated[str | None, typer.Option("--group", "-g", help="Parameter group to list")] = None,
    search: Annotated[str | None, typer.Option("--search", "-s", help="Search pattern")] = None,
    export: Annotated[bool, typer.Option("--export", "-e", help="Export all parameters as JSON")] = False,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output file for export")] = None,
):
    """List device parameters."""
    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )

    device_class = get_device_class(device_type)

    async def _list_params():
        async with device_class(host_addr, user, passwd, port_num, use_digest_auth=digest) as dev:
            if export:
                # Export all parameters as JSON
                import json
                data = await dev.params.export()
                json_output = json.dumps(data, indent=2, sort_keys=True)

                if output:
                    output.write_text(json_output)
                    console.print(f"[green]Exported parameters to:[/green] {output}")
                else:
                    console.print(json_output)
                return

            if search:
                # Search for parameters
                params = await dev.params.search(search)
                if not params:
                    console.print(f"[yellow]No parameters matching '{search}'[/yellow]")
                    return

                table = Table(title=f"Parameters matching '{search}'")
                table.add_column("Name", style="cyan")
                table.add_column("Value", style="white")

                for param in params[:50]:  # Limit to 50 results
                    table.add_row(param.name, param.value or "-")

                console.print(table)

            elif group:
                # Get specific group
                param_group = await dev.params.get_group(group)
                if not param_group.parameters:
                    console.print(f"[yellow]No parameters in group '{group}'[/yellow]")
                    return

                table = Table(title=f"Parameters: {param_group.name}")
                table.add_column("Name", style="cyan")
                table.add_column("Value", style="white")

                for param in param_group.parameters[:100]:
                    table.add_row(param.name, param.value or "-")

                console.print(table)

            else:
                # List all groups
                groups = await dev.params.get_all()
                tree = Tree("[bold]Parameter Groups[/bold]")

                for grp in groups:
                    branch = tree.add(f"[cyan]{grp.name}[/cyan] ({len(grp.parameters)} params)")

                console.print(tree)
                console.print("\n[dim]Use --group <name> to see parameters in a group[/dim]")

    run_async(_list_params())


# --- Log Commands ---

@logs_app.command("system")
def logs_system(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = False,
    lines: LinesOption = 20,
):
    """Get system logs from the device."""
    _get_logs(device, host, username, password, port, LogType.SYSTEM, lines, digest)


@logs_app.command("access")
def logs_access(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = False,
    lines: LinesOption = 20,
):
    """Get access logs from the device."""
    _get_logs(device, host, username, password, port, LogType.ACCESS, lines, digest)


@logs_app.command("audit")
def logs_audit(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = False,
    lines: LinesOption = 20,
):
    """Get audit logs from the device."""
    _get_logs(device, host, username, password, port, LogType.AUDIT, lines, digest)


@logs_app.command("all")
def logs_all(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = False,
    lines: LinesOption = 50,
):
    """Get all logs from the device."""
    _get_logs(device, host, username, password, port, LogType.ALL, lines, digest)


@logs_app.command("search")
def logs_search(
    pattern: Annotated[str, typer.Argument(help="Search pattern")],
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = False,
    lines: LinesOption = 50,
):
    """Search logs for a pattern."""
    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )

    device_class = get_device_class(device_type)

    async def _search_logs():
        async with device_class(host_addr, user, passwd, port_num, use_digest_auth=digest) as dev:
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
    port: int,
    log_type: LogType,
    lines: int | None,
    digest: bool = False,
):
    """Internal function to retrieve and display logs."""
    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )

    device_class = get_device_class(device_type)

    async def _fetch_logs():
        async with device_class(host_addr, user, passwd, port_num, use_digest_auth=digest) as dev:
            report = await dev.logs.get_logs(log_type, max_entries=lines)

            console.print(
                f"[bold]{log_type.value.title()} Logs[/bold]",
                f" from {host_addr} ({len(report.entries)} entries)",
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


# --- Config Commands ---

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

    # Write default config
    config_file.write_text(create_default_config())
    console.print(f"[green]Created config file:[/green] {config_file}")


@app.command("version")
def show_version():
    """Show version information."""
    from axis_cam import __version__

    console.print(f"axiscam version {__version__}")


# --- Completions ---

def complete_device_names() -> list[str]:
    """Completion for device names from config."""
    try:
        config = load_config()
        return list(config.devices.keys())
    except Exception:
        return []


def main():
    """Main entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
