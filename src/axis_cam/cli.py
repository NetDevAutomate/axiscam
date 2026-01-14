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
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from axis_cam import AxisCamera, AxisIntercom, AxisRecorder, AxisSpeaker
from axis_cam.config import (
    create_default_config,
    get_config_dir,
    get_config_file,
    get_device_config,
    get_device_config_by_host,
    load_config,
)
from axis_cam.devices.base import AxisDevice
from axis_cam.models import LogType, ServerReportFormat

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

# Network subcommand group
network_app = typer.Typer(
    name="network",
    help="Network configuration commands.",
    no_args_is_help=True,
)
app.add_typer(network_app, name="network")

# Security subcommand group (firewall, ssh, cert)
security_app = typer.Typer(
    name="security",
    help="Security configuration commands (firewall, SSH, certificates).",
    no_args_is_help=True,
)
app.add_typer(security_app, name="security")

# Services subcommand group (snmp, ntp)
services_app = typer.Typer(
    name="services",
    help="Service configuration commands (SNMP, NTP).",
    no_args_is_help=True,
)
app.add_typer(services_app, name="services")

# Download subcommand group (server reports, debug archives)
download_app = typer.Typer(
    name="download",
    help="Download device reports and debug archives.",
    no_args_is_help=True,
)
app.add_typer(download_app, name="download")


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
        help="Authentication username (override for config device).",
    ),
]

PasswordOption = Annotated[
    str | None,
    typer.Option(
        "--password", "-p",
        help="Authentication password (override for config device).",
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
        "--digest/--no-digest",
        help="Use Digest authentication (default) or Basic auth.",
    ),
]

JsonOption = Annotated[
    bool,
    typer.Option(
        "--json",
        "-j",
        help="Output in JSON format.",
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

    # Try to load from config by name
    config = get_device_config(device)
    if config:
        return (
            config.host,
            username or config.username,
            password or config.password.get_secret_value(),
            port if port != 443 else config.port,
            config.device_type,
        )

    # Check if device looks like a host/IP and try to find it in config
    if device and ("." in device or device.replace(".", "").isdigit()):
        # Try to find device by IP address in config
        config = get_device_config_by_host(device)
        if config:
            return (
                config.host,
                username or config.username,
                password or config.password.get_secret_value(),
                port if port != 443 else config.port,
                config.device_type,
            )
        # Not found in config - require explicit credentials
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
    digest: DigestOption = True,
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
    digest: DigestOption = True,
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
                "[green]Reachable[/green]" if status.reachable else "[red]Unreachable[/red]",
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
                time_str = str(status.current_time) if status.current_time else "-"
                table.add_row("Device Time", time_str)

                console.print(table)

    run_async(_check_status())


@app.command("apis")
def list_apis(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = True,
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
                        if isinstance(details, dict):
                            state = details.get("state", "unknown")
                        else:
                            state = "unknown"
                        if state == "released":
                            state_color = "green"
                        elif state == "beta":
                            state_color = "yellow"
                        else:
                            state_color = "red"
                        tree.add(
                            f"{api_name} v{version} [{state_color}]{state}[/{state_color}]"
                        )
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
    digest: DigestOption = True,
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
                if neighbor.port_descr:
                    port_info = f"{neighbor.port_id.value} ({neighbor.port_descr})"
                else:
                    port_info = neighbor.port_id.value
                table.add_row(
                    neighbor.sys_name or "-",
                    neighbor.sys_descr or "-",
                    neighbor.chassis_id.value,
                    port_info,
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
    digest: DigestOption = True,
    group: Annotated[
        str | None, typer.Option("--group", "-g", help="Parameter group to list")
    ] = None,
    search: Annotated[
        str | None, typer.Option("--search", "-s", help="Search pattern")
    ] = None,
    export: Annotated[
        bool, typer.Option("--export", "-e", help="Export as JSON")
    ] = False,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Output file")
    ] = None,
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
                    tree.add(f"[cyan]{grp.name}[/cyan] ({len(grp.parameters)} params)")

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
    digest: DigestOption = True,
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
    digest: DigestOption = True,
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
    digest: DigestOption = True,
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
    digest: DigestOption = True,
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
    digest: DigestOption = True,
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


# --- Network Commands ---

@network_app.command("show")
def network_show(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = True,
    json_output: Annotated[
        bool, typer.Option("--json", "-j", help="Output as JSON")
    ] = False,
):
    """Show network configuration."""
    import json

    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )
    device_class = get_device_class(device_type)

    async def _show_network():
        async with device_class(
            host_addr, user, passwd, port_num, use_digest_auth=digest
        ) as dev:
            config = await dev.get_network_config()

            if json_output:
                data = {
                    "hostname": config.hostname,
                    "bonjour_enabled": config.bonjour_enabled,
                    "upnp_enabled": config.upnp_enabled,
                    "interfaces": [
                        {
                            "name": iface.name,
                            "ip_address": iface.ip_address,
                            "mac_address": iface.mac_address,
                            "subnet_mask": iface.subnet_mask,
                            "gateway": iface.gateway,
                            "dhcp_enabled": iface.dhcp_enabled,
                            "link_status": iface.link_status,
                        }
                        for iface in config.interfaces
                    ],
                    "dns": {
                        "primary": config.dns.primary,
                        "secondary": config.dns.secondary,
                        "domain": config.dns.domain,
                    },
                }
                console.print(json.dumps(data, indent=2))
                return

            # Main info panel
            console.print(
                Panel(
                    f"Hostname: [cyan]{config.hostname}[/cyan]",
                    title=f"Network Config: {host_addr}",
                )
            )

            # Interfaces table
            if config.interfaces:
                table = Table(title="Network Interfaces")
                table.add_column("Name", style="cyan")
                table.add_column("IP Address", style="green")
                table.add_column("MAC Address", style="dim")
                table.add_column("Subnet", style="white")
                table.add_column("Gateway", style="white")
                table.add_column("DHCP", style="yellow")
                table.add_column("Status", style="white")

                for iface in config.interfaces:
                    dhcp = (
                        "[green]Yes[/green]"
                        if iface.dhcp_enabled
                        else "[red]No[/red]"
                    )
                    table.add_row(
                        iface.name,
                        iface.ip_address,
                        iface.mac_address,
                        iface.subnet_mask,
                        iface.gateway,
                        dhcp,
                        iface.link_status,
                    )
                console.print(table)

            # DNS info
            dns_table = Table(title="DNS Configuration", show_header=False)
            dns_table.add_column("Setting", style="cyan")
            dns_table.add_column("Value", style="white")
            dns_table.add_row("Primary DNS", config.dns.primary or "-")
            dns_table.add_row("Secondary DNS", config.dns.secondary or "-")
            dns_table.add_row("Domain", config.dns.domain or "-")
            console.print(dns_table)

            # Services
            svc_table = Table(title="Network Services", show_header=False)
            svc_table.add_column("Service", style="cyan")
            svc_table.add_column("Status", style="white")
            svc_table.add_row(
                "Bonjour",
                "[green]Enabled[/green]"
                if config.bonjour_enabled
                else "[red]Disabled[/red]",
            )
            svc_table.add_row(
                "UPnP",
                "[green]Enabled[/green]"
                if config.upnp_enabled
                else "[red]Disabled[/red]",
            )
            console.print(svc_table)

    run_async(_show_network())


@network_app.command("dns")
def network_dns(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = True,
):
    """Show DNS configuration."""
    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )
    device_class = get_device_class(device_type)

    async def _show_dns():
        async with device_class(
            host_addr, user, passwd, port_num, use_digest_auth=digest
        ) as dev:
            dns = await dev.network.get_dns()

            table = Table(title=f"DNS Configuration: {host_addr}", show_header=False)
            table.add_column("Setting", style="cyan")
            table.add_column("Value", style="white")
            table.add_row("Primary DNS", dns.primary or "[dim](not set)[/dim]")
            table.add_row("Secondary DNS", dns.secondary or "[dim](not set)[/dim]")
            table.add_row("Domain", dns.domain or "[dim](not set)[/dim]")
            console.print(table)

    run_async(_show_dns())


# --- Security Commands ---

@security_app.command("firewall")
def security_firewall(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = True,
    json_output: Annotated[
        bool, typer.Option("--json", "-j", help="Output as JSON")
    ] = False,
):
    """Show firewall configuration."""
    import json

    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )
    device_class = get_device_class(device_type)

    async def _show_firewall():
        async with device_class(
            host_addr, user, passwd, port_num, use_digest_auth=digest
        ) as dev:
            config = await dev.get_firewall_config()

            if json_output:
                data = {
                    "enabled": config.enabled,
                    "default_policy": config.default_policy.value,
                    "rules": [
                        {
                            "name": r.name,
                            "enabled": r.enabled,
                            "action": r.action.value,
                            "source_address": r.source_address,
                            "destination_port": r.destination_port,
                            "protocol": r.protocol.value,
                            "priority": r.priority,
                        }
                        for r in config.rules
                    ],
                }
                console.print(json.dumps(data, indent=2))
                return

            # Status panel
            status = (
                "[green]Enabled[/green]" if config.enabled else "[red]Disabled[/red]"
            )
            policy_color = "green" if config.default_policy.value == "allow" else "red"
            policy_val = config.default_policy.value.upper()
            panel_content = (
                f"Status: {status}\n"
                f"Default Policy: [{policy_color}]{policy_val}[/{policy_color}]"
            )
            console.print(Panel(panel_content, title=f"Firewall: {host_addr}"))

            # Rules table
            if config.rules:
                table = Table(title=f"Firewall Rules ({len(config.rules)})")
                table.add_column("Name", style="cyan")
                table.add_column("Enabled", style="white")
                table.add_column("Action", style="white")
                table.add_column("Source", style="white")
                table.add_column("Port", style="white")
                table.add_column("Protocol", style="white")
                table.add_column("Priority", style="dim")

                for rule in config.rules:
                    enabled = (
                        "[green]Yes[/green]"
                        if rule.enabled
                        else "[red]No[/red]"
                    )
                    action_color = "green" if rule.action.value == "allow" else "red"
                    table.add_row(
                        rule.name,
                        enabled,
                        f"[{action_color}]{rule.action.value}[/{action_color}]",
                        rule.source_address or "*",
                        str(rule.destination_port) if rule.destination_port else "*",
                        rule.protocol.value,
                        str(rule.priority),
                    )
                console.print(table)
            else:
                console.print("[yellow]No firewall rules configured[/yellow]")

    run_async(_show_firewall())


@security_app.command("ssh")
def security_ssh(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = True,
    json_output: Annotated[
        bool, typer.Option("--json", "-j", help="Output as JSON")
    ] = False,
):
    """Show SSH configuration."""
    import json

    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )
    device_class = get_device_class(device_type)

    async def _show_ssh():
        async with device_class(
            host_addr, user, passwd, port_num, use_digest_auth=digest
        ) as dev:
            config = await dev.get_ssh_config()

            if json_output:
                data = {
                    "enabled": config.enabled,
                    "port": config.port,
                    "root_login_enabled": config.root_login_enabled,
                    "password_auth_enabled": config.password_auth_enabled,
                    "authorized_keys": [
                        {
                            "name": k.name,
                            "key_type": k.key_type,
                            "fingerprint": k.fingerprint,
                            "comment": k.comment,
                        }
                        for k in config.authorized_keys
                    ],
                }
                console.print(json.dumps(data, indent=2))
                return

            # Status panel
            status = "[green]Enabled[/green]" if config.enabled else "[red]Disabled[/red]"
            console.print(
                Panel(
                    f"Status: {status}\nPort: {config.port}",
                    title=f"SSH Configuration: {host_addr}",
                )
            )

            # Settings table
            table = Table(title="SSH Settings", show_header=False)
            table.add_column("Setting", style="cyan")
            table.add_column("Value", style="white")
            table.add_row(
                "Root Login",
                "[green]Enabled[/green]"
                if config.root_login_enabled
                else "[red]Disabled[/red]",
            )
            table.add_row(
                "Password Auth",
                "[green]Enabled[/green]"
                if config.password_auth_enabled
                else "[red]Disabled[/red]",
            )
            console.print(table)

            # Authorized keys
            if config.authorized_keys:
                keys_table = Table(
                    title=f"Authorized Keys ({len(config.authorized_keys)})"
                )
                keys_table.add_column("Name", style="cyan")
                keys_table.add_column("Type", style="white")
                keys_table.add_column("Fingerprint", style="dim")
                keys_table.add_column("Comment", style="white")

                for key in config.authorized_keys:
                    keys_table.add_row(
                        key.name,
                        key.key_type,
                        key.fingerprint[:20] + "..." if key.fingerprint else "-",
                        key.comment or "-",
                    )
                console.print(keys_table)

    run_async(_show_ssh())


@security_app.command("certs")
def security_certs(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = True,
    json_output: Annotated[
        bool, typer.Option("--json", "-j", help="Output as JSON")
    ] = False,
):
    """Show certificate configuration."""
    import json

    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )
    device_class = get_device_class(device_type)

    async def _show_certs():
        async with device_class(
            host_addr, user, passwd, port_num, use_digest_auth=digest
        ) as dev:
            config = await dev.get_cert_config()

            if json_output:
                data = {
                    "https_cert_id": config.https_cert_id,
                    "client_cert_enabled": config.client_cert_enabled,
                    "certificates": [
                        {
                            "id": c.id,
                            "subject": c.subject,
                            "issuer": c.issuer,
                            "cert_type": c.cert_type.value,
                            "valid_from": c.valid_from.isoformat() if c.valid_from else None,
                            "valid_to": c.valid_to.isoformat() if c.valid_to else None,
                            "is_valid": c.is_valid,
                        }
                        for c in config.certificates
                    ],
                }
                console.print(json.dumps(data, indent=2))
                return

            # Status panel
            cert_id = config.https_cert_id or "(default)"
            client_auth = (
                "[green]Enabled[/green]"
                if config.client_cert_enabled
                else "[red]Disabled[/red]"
            )
            panel_content = (
                f"HTTPS Certificate ID: [cyan]{cert_id}[/cyan]\n"
                f"Client Cert Auth: {client_auth}"
            )
            console.print(
                Panel(panel_content, title=f"Certificate Configuration: {host_addr}")
            )

            # Certificates table
            if config.certificates:
                table = Table(title=f"Certificates ({len(config.certificates)})")
                table.add_column("ID", style="cyan")
                table.add_column("Subject", style="white")
                table.add_column("Issuer", style="white")
                table.add_column("Type", style="white")
                table.add_column("Valid To", style="white")
                table.add_column("Status", style="white")

                for cert in config.certificates:
                    valid_to = (
                        cert.valid_to.strftime("%Y-%m-%d") if cert.valid_to else "-"
                    )
                    status = (
                        "[green]Valid[/green]"
                        if cert.is_valid
                        else "[red]Invalid/Expired[/red]"
                    )
                    table.add_row(
                        cert.id,
                        cert.subject[:30] + "..." if len(cert.subject) > 30 else cert.subject,
                        cert.issuer[:30] + "..." if len(cert.issuer) > 30 else cert.issuer,
                        cert.cert_type.value,
                        valid_to,
                        status,
                    )
                console.print(table)
            else:
                console.print("[yellow]No certificates found[/yellow]")

    run_async(_show_certs())


# --- Services Commands ---

@services_app.command("snmp")
def services_snmp(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = True,
    json_output: Annotated[
        bool, typer.Option("--json", "-j", help="Output as JSON")
    ] = False,
):
    """Show SNMP configuration."""
    import json

    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )
    device_class = get_device_class(device_type)

    async def _show_snmp():
        async with device_class(
            host_addr, user, passwd, port_num, use_digest_auth=digest
        ) as dev:
            config = await dev.get_snmp_config()

            if json_output:
                data = {
                    "enabled": config.enabled,
                    "version": config.version.value,
                    "read_community": config.read_community,
                    "write_community": config.write_community,
                    "location": config.location,
                    "contact": config.contact,
                    "trap_receivers": [
                        {
                            "address": t.address,
                            "port": t.port,
                            "community": t.community,
                            "version": t.version.value,
                        }
                        for t in config.trap_receivers
                    ],
                }
                console.print(json.dumps(data, indent=2))
                return

            # Status panel
            status = "[green]Enabled[/green]" if config.enabled else "[red]Disabled[/red]"
            console.print(
                Panel(
                    f"Status: {status}\nVersion: {config.version.value}",
                    title=f"SNMP Configuration: {host_addr}",
                )
            )

            # Settings table
            table = Table(title="SNMP Settings", show_header=False)
            table.add_column("Setting", style="cyan")
            table.add_column("Value", style="white")
            table.add_row("Read Community", config.read_community or "[dim](not set)[/dim]")
            table.add_row(
                "Write Community",
                "[dim]****[/dim]" if config.write_community else "[dim](not set)[/dim]",
            )
            table.add_row("Location", config.location or "[dim](not set)[/dim]")
            table.add_row("Contact", config.contact or "[dim](not set)[/dim]")
            console.print(table)

            # Trap receivers
            if config.trap_receivers:
                trap_table = Table(
                    title=f"Trap Receivers ({len(config.trap_receivers)})"
                )
                trap_table.add_column("Address", style="cyan")
                trap_table.add_column("Port", style="white")
                trap_table.add_column("Community", style="white")
                trap_table.add_column("Version", style="white")

                for trap in config.trap_receivers:
                    trap_table.add_row(
                        trap.address,
                        str(trap.port),
                        trap.community or "-",
                        trap.version.value,
                    )
                console.print(trap_table)

    run_async(_show_snmp())


@services_app.command("ntp")
def services_ntp(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = True,
    json_output: Annotated[
        bool, typer.Option("--json", "-j", help="Output as JSON")
    ] = False,
):
    """Show NTP configuration."""
    import json

    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )
    device_class = get_device_class(device_type)

    async def _show_ntp():
        async with device_class(
            host_addr, user, passwd, port_num, use_digest_auth=digest
        ) as dev:
            config = await dev.get_ntp_config()

            if json_output:
                data = {
                    "enabled": config.enabled,
                    "use_dhcp_servers": config.use_dhcp_servers,
                    "servers": [
                        {
                            "address": s.address,
                            "prefer": s.prefer,
                            "iburst": s.iburst,
                        }
                        for s in config.servers
                    ],
                }
                if config.sync_status:
                    data["sync_status"] = {
                        "synchronized": config.sync_status.synchronized,
                        "stratum": config.sync_status.stratum,
                        "offset_ms": config.sync_status.offset_ms,
                        "delay_ms": config.sync_status.delay_ms,
                        "current_server": config.sync_status.current_server,
                    }
                console.print(json.dumps(data, indent=2))
                return

            # Status panel
            status = "[green]Enabled[/green]" if config.enabled else "[red]Disabled[/red]"
            dhcp = (
                "[green]Yes[/green]"
                if config.use_dhcp_servers
                else "[red]No[/red]"
            )
            console.print(
                Panel(
                    f"Status: {status}\nUse DHCP Servers: {dhcp}",
                    title=f"NTP Configuration: {host_addr}",
                )
            )

            # Servers table
            if config.servers:
                table = Table(title=f"NTP Servers ({len(config.servers)})")
                table.add_column("Address", style="cyan")
                table.add_column("Preferred", style="white")
                table.add_column("IBurst", style="white")

                for server in config.servers:
                    prefer = "[green]Yes[/green]" if server.prefer else "-"
                    iburst = "[green]Yes[/green]" if server.iburst else "-"
                    table.add_row(server.address, prefer, iburst)
                console.print(table)

            # Sync status
            if config.sync_status:
                sync = config.sync_status
                sync_status = (
                    "[green]Synchronized[/green]"
                    if sync.synchronized
                    else "[yellow]Not Synchronized[/yellow]"
                )
                sync_table = Table(title="Synchronization Status", show_header=False)
                sync_table.add_column("Metric", style="cyan")
                sync_table.add_column("Value", style="white")
                sync_table.add_row("Status", sync_status)
                sync_table.add_row("Current Server", sync.current_server or "-")
                sync_table.add_row("Stratum", str(sync.stratum) if sync.stratum else "-")
                sync_table.add_row(
                    "Offset",
                    f"{sync.offset_ms:.3f} ms" if sync.offset_ms is not None else "-",
                )
                sync_table.add_row(
                    "Delay",
                    f"{sync.delay_ms:.3f} ms" if sync.delay_ms is not None else "-",
                )
                console.print(sync_table)

    run_async(_show_ntp())


# =============================================================================
# Automation Commands (Action Rules, MQTT)
# =============================================================================


automation_app = typer.Typer(
    name="automation",
    help="Automation configuration commands (action rules, MQTT).",
    no_args_is_help=True,
)
app.add_typer(automation_app, name="automation")


@automation_app.command("actions")
def show_actions(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    digest: DigestOption = True,
    json_output: JsonOption = False,
):
    """Show action rules configuration."""
    import json as json_mod

    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )
    device_class = get_device_class(device_type)

    async def _show_actions():
        async with device_class(
            host_addr, user, passwd, port_num, use_digest_auth=digest
        ) as dev:
            config = await dev.get_action_config()

            if json_output:
                data = {
                    "rules": [
                        {
                            "id": r.id,
                            "name": r.name,
                            "enabled": r.enabled,
                            "primary_condition": r.primary_condition,
                            "conditions": r.conditions,
                            "actions": r.actions,
                        }
                        for r in config.rules
                    ],
                    "templates": [
                        {
                            "id": t.id,
                            "name": t.name,
                            "type": t.template_type,
                        }
                        for t in config.templates
                    ],
                }
                console.print(json_mod.dumps(data, indent=2))
                return

            # Rules table
            if config.rules:
                table = Table(title=f"Action Rules ({len(config.rules)})")
                table.add_column("ID", style="cyan")
                table.add_column("Name", style="white")
                table.add_column("Enabled", style="white")
                table.add_column("Condition", style="white")

                for rule in config.rules:
                    enabled = "[green]Yes[/green]" if rule.enabled else "[red]No[/red]"
                    table.add_row(
                        rule.id, rule.name, enabled, rule.primary_condition or "-"
                    )
                console.print(table)
            else:
                console.print("[yellow]No action rules configured[/yellow]")

            # Templates table
            if config.templates:
                tmpl_table = Table(title=f"Action Templates ({len(config.templates)})")
                tmpl_table.add_column("ID", style="cyan")
                tmpl_table.add_column("Name", style="white")
                tmpl_table.add_column("Type", style="white")

                for tmpl in config.templates:
                    tmpl_table.add_row(tmpl.id, tmpl.name, tmpl.template_type or "-")
                console.print(tmpl_table)

    run_async(_show_actions())


@automation_app.command("mqtt")
def show_mqtt(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    digest: DigestOption = True,
    json_output: JsonOption = False,
):
    """Show MQTT event bridge configuration."""
    import json as json_mod

    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )
    device_class = get_device_class(device_type)

    async def _show_mqtt():
        async with device_class(
            host_addr, user, passwd, port_num, use_digest_auth=digest
        ) as dev:
            config = await dev.get_mqtt_config()

            if json_output:
                data = {
                    "enabled": config.enabled,
                    "connected": config.connected,
                    "clients": [
                        {
                            "id": c.id,
                            "host": c.host,
                            "port": c.port,
                            "protocol": c.protocol,
                            "use_tls": c.use_tls,
                        }
                        for c in config.clients
                    ],
                    "event_filters": [
                        {
                            "id": f.id,
                            "name": f.name,
                            "topic": f.topic,
                            "enabled": f.enabled,
                            "qos": f.qos,
                        }
                        for f in config.event_filters
                    ],
                }
                console.print(json_mod.dumps(data, indent=2))
                return

            # Status panel
            status = "[green]Enabled[/green]" if config.enabled else "[red]Disabled[/red]"
            conn = (
                "[green]Connected[/green]" if config.connected else "[yellow]Disconnected[/yellow]"
            )
            console.print(
                Panel(
                    f"Status: {status}\nConnection: {conn}",
                    title=f"MQTT Bridge: {host_addr}",
                )
            )

            # Clients table
            if config.clients:
                table = Table(title=f"MQTT Clients ({len(config.clients)})")
                table.add_column("ID", style="cyan")
                table.add_column("Host", style="white")
                table.add_column("Port", style="white")
                table.add_column("Protocol", style="white")
                table.add_column("TLS", style="white")

                for client in config.clients:
                    tls = "[green]Yes[/green]" if client.use_tls else "-"
                    table.add_row(
                        client.id,
                        client.host,
                        str(client.port),
                        client.protocol,
                        tls,
                    )
                console.print(table)

            # Event filters table
            if config.event_filters:
                filter_table = Table(title=f"Event Filters ({len(config.event_filters)})")
                filter_table.add_column("Name", style="cyan")
                filter_table.add_column("Topic", style="white")
                filter_table.add_column("Enabled", style="white")
                filter_table.add_column("QoS", style="white")

                for f in config.event_filters:
                    enabled = "[green]Yes[/green]" if f.enabled else "[red]No[/red]"
                    filter_table.add_row(f.name, f.topic, enabled, str(f.qos))
                console.print(filter_table)

    run_async(_show_mqtt())


# =============================================================================
# Media Commands (Recording, Storage)
# =============================================================================


media_app = typer.Typer(
    name="media",
    help="Media configuration commands (recording, storage).",
    no_args_is_help=True,
)
app.add_typer(media_app, name="media")


@media_app.command("recording")
def show_recording(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    digest: DigestOption = True,
    json_output: JsonOption = False,
):
    """Show recording configuration."""
    import json as json_mod

    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )
    device_class = get_device_class(device_type)

    async def _show_recording():
        async with device_class(
            host_addr, user, passwd, port_num, use_digest_auth=digest
        ) as dev:
            config = await dev.get_recording_config()

            if json_output:
                data = {
                    "groups": [
                        {
                            "id": g.id,
                            "name": g.name,
                            "storage_id": g.storage_id,
                            "retention_days": g.retention_days,
                            "max_size_mb": g.max_size_mb,
                        }
                        for g in config.groups
                    ],
                    "profiles": [
                        {
                            "id": p.id,
                            "name": p.name,
                            "format": p.format,
                            "video_codec": p.video_codec,
                            "audio_enabled": p.audio_enabled,
                            "resolution": p.resolution,
                            "framerate": p.framerate,
                            "bitrate": p.bitrate,
                        }
                        for p in config.profiles
                    ],
                }
                console.print(json_mod.dumps(data, indent=2))
                return

            # Groups table
            if config.groups:
                table = Table(title=f"Recording Groups ({len(config.groups)})")
                table.add_column("ID", style="cyan")
                table.add_column("Name", style="white")
                table.add_column("Storage", style="white")
                table.add_column("Retention", style="white")
                table.add_column("Max Size", style="white")

                for group in config.groups:
                    retention = f"{group.retention_days}d" if group.retention_days else "-"
                    max_size = f"{group.max_size_mb}MB" if group.max_size_mb else "-"
                    table.add_row(
                        group.id,
                        group.name,
                        group.storage_id or "-",
                        retention,
                        max_size,
                    )
                console.print(table)
            else:
                console.print("[yellow]No recording groups configured[/yellow]")

            # Profiles table
            if config.profiles:
                prof_table = Table(title=f"Recording Profiles ({len(config.profiles)})")
                prof_table.add_column("ID", style="cyan")
                prof_table.add_column("Name", style="white")
                prof_table.add_column("Format", style="white")
                prof_table.add_column("Codec", style="white")
                prof_table.add_column("Resolution", style="white")
                prof_table.add_column("FPS", style="white")

                for prof in config.profiles:
                    prof_table.add_row(
                        prof.id,
                        prof.name,
                        prof.format,
                        prof.video_codec,
                        prof.resolution or "-",
                        str(prof.framerate) if prof.framerate else "-",
                    )
                console.print(prof_table)

    run_async(_show_recording())


@media_app.command("storage")
def show_storage(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    digest: DigestOption = True,
    json_output: JsonOption = False,
):
    """Show remote storage configuration."""
    import json as json_mod

    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )
    device_class = get_device_class(device_type)

    async def _show_storage():
        async with device_class(
            host_addr, user, passwd, port_num, use_digest_auth=digest
        ) as dev:
            config = await dev.get_storage_config()

            if json_output:
                data = {
                    "destinations": [
                        {
                            "id": d.id,
                            "name": d.name,
                            "type": d.storage_type.value,
                            "endpoint": d.endpoint,
                            "bucket": d.bucket,
                            "region": d.region,
                            "enabled": d.enabled,
                        }
                        for d in config.destinations
                    ],
                }
                console.print(json_mod.dumps(data, indent=2))
                return

            # Destinations table
            if config.destinations:
                table = Table(title=f"Storage Destinations ({len(config.destinations)})")
                table.add_column("ID", style="cyan")
                table.add_column("Name", style="white")
                table.add_column("Type", style="white")
                table.add_column("Bucket", style="white")
                table.add_column("Region", style="white")
                table.add_column("Enabled", style="white")

                for dest in config.destinations:
                    enabled = "[green]Yes[/green]" if dest.enabled else "[red]No[/red]"
                    table.add_row(
                        dest.id,
                        dest.name,
                        dest.storage_type.value.upper(),
                        dest.bucket or "-",
                        dest.region or "-",
                        enabled,
                    )
                console.print(table)
            else:
                console.print("[yellow]No storage destinations configured[/yellow]")

    run_async(_show_storage())


# =============================================================================
# Geolocation Command
# =============================================================================


@app.command("location")
def show_location(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    digest: DigestOption = True,
    json_output: JsonOption = False,
):
    """Show device geolocation configuration."""
    import json as json_mod

    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )
    device_class = get_device_class(device_type)

    async def _show_location():
        async with device_class(
            host_addr, user, passwd, port_num, use_digest_auth=digest
        ) as dev:
            config = await dev.get_geolocation_config()

            if json_output:
                data = {
                    "latitude": config.latitude,
                    "longitude": config.longitude,
                    "altitude": config.altitude,
                    "direction": config.direction,
                    "heading": config.heading,
                    "speed": config.speed,
                    "horizontal_accuracy": config.horizontal_accuracy,
                    "vertical_accuracy": config.vertical_accuracy,
                    "timestamp": config.timestamp,
                }
                console.print(json_mod.dumps(data, indent=2))
                return

            # Check if location is configured
            if config.latitude is None and config.longitude is None:
                console.print("[yellow]No geolocation configured[/yellow]")
                return

            # Location table
            table = Table(title=f"Geolocation: {host_addr}", show_header=False)
            table.add_column("Property", style="cyan")
            table.add_column("Value", style="white")

            if config.latitude is not None:
                table.add_row("Latitude", f"{config.latitude:.6f}°")
            if config.longitude is not None:
                table.add_row("Longitude", f"{config.longitude:.6f}°")
            if config.altitude is not None:
                table.add_row("Altitude", f"{config.altitude:.1f} m")
            if config.direction is not None:
                table.add_row("Direction", f"{config.direction:.1f}°")
            if config.heading is not None:
                table.add_row("Heading", f"{config.heading:.1f}°")
            if config.speed is not None:
                table.add_row("Speed", f"{config.speed:.2f} m/s")
            if config.horizontal_accuracy is not None:
                table.add_row("H. Accuracy", f"{config.horizontal_accuracy:.1f} m")
            if config.vertical_accuracy is not None:
                table.add_row("V. Accuracy", f"{config.vertical_accuracy:.1f} m")
            if config.timestamp:
                table.add_row("Timestamp", config.timestamp)

            console.print(table)

    run_async(_show_location())


# --- Stream Commands ---

stream_app = typer.Typer(
    name="stream",
    help="Stream diagnostics commands (RTSP, RTP, profiles).",
    no_args_is_help=True,
)
app.add_typer(stream_app, name="stream")


@stream_app.command("show")
def stream_show(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = True,
    json_output: Annotated[
        bool, typer.Option("--json", "-j", help="Output as JSON")
    ] = False,
):
    """Show stream diagnostics (RTSP, RTP, profiles).

    Displays streaming configuration useful for troubleshooting
    connectivity issues with third-party systems.
    """
    import json as json_mod

    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )

    device_class = get_device_class(device_type)

    async def _show_stream():
        async with device_class(host_addr, user, passwd, port_num, use_digest_auth=digest) as dev:
            diag = await dev.get_stream_diagnostics(device or host_addr)

            if json_output:
                data = {
                    "device": diag.device_name,
                    "rtsp": {
                        "enabled": diag.rtsp.enabled,
                        "port": diag.rtsp.port,
                        "authentication": diag.rtsp.authentication,
                        "timeout": diag.rtsp.timeout,
                    },
                    "rtp": {
                        "start_port": diag.rtp.start_port,
                        "end_port": diag.rtp.end_port,
                        "multicast_enabled": diag.rtp.multicast_enabled,
                        "multicast_address": diag.rtp.multicast_address,
                    },
                    "profiles": [
                        {
                            "name": p.name,
                            "codec": p.video_codec,
                            "resolution": p.resolution,
                            "fps": p.fps,
                            "bitrate": p.bitrate,
                            "gop_length": p.gop_length,
                        }
                        for p in diag.profiles
                    ],
                    "errors": diag.errors,
                }
                console.print(json_mod.dumps(data, indent=2))
                return

            # RTSP panel
            console.print(
                Panel(
                    f"[green]Enabled[/green]" if diag.rtsp.enabled else "[red]Disabled[/red]",
                    title=f"Stream Diagnostics: {host_addr}",
                )
            )

            # RTSP table
            rtsp_table = Table(title="RTSP Configuration", show_header=False)
            rtsp_table.add_column("Property", style="cyan")
            rtsp_table.add_column("Value", style="white")
            rtsp_table.add_row("Port", str(diag.rtsp.port))
            rtsp_table.add_row("Authentication", diag.rtsp.authentication)
            rtsp_table.add_row("Timeout", f"{diag.rtsp.timeout}s")
            console.print(rtsp_table)

            # RTP table
            rtp_table = Table(title="RTP Configuration", show_header=False)
            rtp_table.add_column("Property", style="cyan")
            rtp_table.add_column("Value", style="white")
            rtp_table.add_row("Port Range", f"{diag.rtp.start_port}-{diag.rtp.end_port}")
            rtp_table.add_row(
                "Multicast",
                "[green]Yes[/green]" if diag.rtp.multicast_enabled else "[red]No[/red]",
            )
            if diag.rtp.multicast_address:
                rtp_table.add_row("Multicast Address", diag.rtp.multicast_address)
            console.print(rtp_table)

            # Stream profiles
            if diag.profiles:
                profile_table = Table(title="Stream Profiles")
                profile_table.add_column("Name", style="cyan")
                profile_table.add_column("Codec", style="green")
                profile_table.add_column("Resolution", style="white")
                profile_table.add_column("FPS", style="white")
                profile_table.add_column("Bitrate", style="white")
                profile_table.add_column("GOP", style="dim")

                for profile in diag.profiles:
                    bitrate = f"{profile.bitrate} kbps" if profile.bitrate else "VBR"
                    profile_table.add_row(
                        profile.name,
                        profile.video_codec,
                        profile.resolution or "-",
                        str(profile.fps),
                        bitrate,
                        str(profile.gop_length),
                    )

                console.print(profile_table)

            # Show errors if any
            if diag.errors:
                console.print("\n[yellow]Warnings:[/yellow]")
                for error in diag.errors:
                    console.print(f"  [yellow]•[/yellow] {error}")

    run_async(_show_stream())


# --- Report Command ---

@app.command("report")
def device_report(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    digest: DigestOption = True,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Output file")
    ] = None,
    format_opt: Annotated[
        str, typer.Option("--format", "-f", help="Output format (json, yaml)")
    ] = "json",
    full: Annotated[
        bool, typer.Option("--full", help="Include all available configurations")
    ] = False,
):
    """Generate comprehensive device report.

    Collects device info, network config, security settings, stream
    diagnostics, LLDP info, and time configuration.

    Use --full to include ALL available configurations (SSH, SNMP, certs,
    MQTT, actions, recording, storage, geolocation, analytics, etc.)
    """
    import json as json_mod

    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )

    device_class = get_device_class(device_type)

    async def _generate_report():
        async with device_class(host_addr, user, passwd, port_num, use_digest_auth=digest) as dev:
            # Collect all information
            report: dict = {"device": device or host_addr, "errors": []}

            # Device info
            try:
                info = await dev.get_info()
                report["info"] = {
                    "brand": info.brand,
                    "model": info.product_number,
                    "product_name": info.product_full_name,
                    "serial_number": info.serial_number,
                    "firmware": info.firmware_version,
                    "hardware_id": info.hardware_id,
                    "architecture": info.architecture,
                    "soc": info.soc,
                }
            except Exception as e:
                report["errors"].append(f"Device info: {e}")

            # Time info
            try:
                time_info = await dev.get_time_info()
                report["time"] = {
                    "utc_time": str(time_info.utc_time) if time_info.utc_time else None,
                    "timezone": time_info.timezone,
                }
            except Exception as e:
                report["errors"].append(f"Time info: {e}")

            # Network config
            try:
                network = await dev.get_network_config()
                if network.interfaces:
                    iface = network.interfaces[0]
                    report["network"] = {
                        "interface": iface.name,
                        "ip_address": iface.ip_address,
                        "mac_address": iface.mac_address,
                        "dhcp": iface.dhcp_enabled,
                    }
            except Exception as e:
                report["errors"].append(f"Network config: {e}")

            # LLDP info
            try:
                lldp = await dev.get_lldp_info()
                report["lldp"] = {
                    "enabled": lldp.activated,
                    "neighbors": [
                        {
                            "system": n.sys_name,
                            "port": n.port_id.value,
                            "port_desc": n.port_descr,
                        }
                        for n in lldp.neighbors
                    ],
                }
            except Exception as e:
                report["errors"].append(f"LLDP info: {e}")

            # Stream diagnostics (cameras only)
            if device_type == "camera":
                try:
                    stream = await dev.get_stream_diagnostics()
                    report["stream"] = {
                        "rtsp_port": stream.rtsp.port,
                        "rtsp_auth": stream.rtsp.authentication,
                        "rtp_range": f"{stream.rtp.start_port}-{stream.rtp.end_port}",
                        "profiles": [
                            {"name": p.name, "codec": p.video_codec, "resolution": p.resolution}
                            for p in stream.profiles
                        ],
                    }
                except Exception as e:
                    report["errors"].append(f"Stream diagnostics: {e}")

            # Security status
            try:
                firewall = await dev.get_firewall_config()
                report["security"] = {
                    "firewall_enabled": firewall.enabled,
                    "ipv4_rules_count": len(firewall.ipv4_rules),
                    "ipv6_rules_count": len(firewall.ipv6_rules),
                }
            except Exception as e:
                report["errors"].append(f"Security config: {e}")

            # NTP status
            try:
                ntp = await dev.get_ntp_config()
                report["ntp"] = {
                    "enabled": ntp.enabled,
                    "servers": [s.address for s in ntp.servers] if ntp.servers else [],
                }
            except Exception as e:
                report["errors"].append(f"NTP config: {e}")

            # Full configuration export
            if full:
                # SSH config
                try:
                    ssh = await dev.get_ssh_config()
                    report["ssh"] = {
                        "enabled": ssh.enabled,
                        "port": ssh.port,
                    }
                except Exception as e:
                    report["errors"].append(f"SSH config: {e}")

                # SNMP config
                try:
                    snmp = await dev.get_snmp_config()
                    report["snmp"] = {
                        "enabled": snmp.enabled,
                        "version": snmp.version.value if snmp.version else None,
                        "v3_enabled": snmp.v3_enabled,
                        "read_community": snmp.read_community,
                        "system_location": snmp.system_location,
                        "system_contact": snmp.system_contact,
                    }
                except Exception as e:
                    report["errors"].append(f"SNMP config: {e}")

                # Certificate config
                try:
                    cert = await dev.get_cert_config()
                    report["certificates"] = {
                        "count": len(cert.certificates) if cert.certificates else 0,
                        "certificates": [
                            {
                                "cert_id": c.cert_id,
                                "subject": c.subject,
                                "issuer": c.issuer,
                                "not_before": c.not_before if c.not_before else None,
                                "not_after": c.not_after if c.not_after else None,
                            }
                            for c in (cert.certificates or [])
                        ],
                    }
                except Exception as e:
                    report["errors"].append(f"Certificate config: {e}")

                # Action rules
                try:
                    actions = await dev.get_action_config()
                    report["actions"] = {
                        "rules_count": len(actions.rules) if actions.rules else 0,
                        "rules": [
                            {"id": r.id, "name": r.name, "enabled": r.enabled}
                            for r in (actions.rules or [])
                        ],
                    }
                except Exception as e:
                    report["errors"].append(f"Action config: {e}")

                # MQTT config
                try:
                    mqtt = await dev.get_mqtt_config()
                    report["mqtt"] = {
                        "enabled": mqtt.enabled,
                        "connected": mqtt.connected,
                        "clients": [
                            {
                                "id": c.id,
                                "host": c.host,
                                "port": c.port,
                                "client_id": c.client_id,
                            }
                            for c in (mqtt.clients or [])
                        ],
                    }
                except Exception as e:
                    report["errors"].append(f"MQTT config: {e}")

                # Recording config
                try:
                    recording = await dev.get_recording_config()
                    report["recording"] = {
                        "groups_count": len(recording.groups) if recording.groups else 0,
                        "groups": [
                            {"id": g.id, "name": g.name}
                            for g in (recording.groups or [])
                        ],
                    }
                except Exception as e:
                    report["errors"].append(f"Recording config: {e}")

                # Storage config
                try:
                    storage = await dev.get_storage_config()
                    report["storage"] = {
                        "destinations_count": len(storage.destinations) if storage.destinations else 0,
                        "destinations": [
                            {
                                "id": d.id,
                                "storage_type": d.storage_type.value if d.storage_type else None,
                                "enabled": d.enabled,
                            }
                            for d in (storage.destinations or [])
                        ],
                    }
                except Exception as e:
                    report["errors"].append(f"Storage config: {e}")

                # Geolocation
                try:
                    geo = await dev.get_geolocation_config()
                    report["geolocation"] = {
                        "latitude": geo.latitude,
                        "longitude": geo.longitude,
                        "altitude": geo.altitude,
                        "direction": geo.direction,
                    }
                except Exception as e:
                    report["errors"].append(f"Geolocation config: {e}")

                # Analytics (cameras)
                if device_type == "camera":
                    try:
                        analytics = await dev.get_analytics_config()
                        report["analytics"] = {
                            "profiles_count": len(analytics.profiles) if analytics.profiles else 0,
                            "profiles": [
                                {"id": p.id, "name": p.name, "enabled": p.enabled}
                                for p in (analytics.profiles or [])
                            ],
                        }
                    except Exception as e:
                        report["errors"].append(f"Analytics config: {e}")

                # OIDC config
                try:
                    oidc = await dev.get_oidc_config()
                    report["oidc"] = {
                        "enabled": oidc.enabled,
                        "issuer_uri": oidc.provider.issuer_uri if oidc.provider else None,
                        "client_id": oidc.provider.client_id if oidc.provider else None,
                    }
                except Exception as e:
                    report["errors"].append(f"OIDC config: {e}")

                # OAuth config
                try:
                    oauth = await dev.get_oauth_config()
                    report["oauth"] = {
                        "enabled": oauth.enabled,
                    }
                except Exception as e:
                    report["errors"].append(f"OAuth config: {e}")

                # Crypto policy
                try:
                    crypto = await dev.get_crypto_policy_config()
                    report["crypto_policy"] = {
                        "tls_min_version": crypto.tls_min_version.value if crypto.tls_min_version else None,
                        "tls_max_version": crypto.tls_max_version.value if crypto.tls_max_version else None,
                        "cipher_suites": [c.name for c in (crypto.cipher_suites or [])],
                    }
                except Exception as e:
                    report["errors"].append(f"Crypto policy config: {e}")

            # Format output
            if format_opt == "yaml":
                try:
                    import yaml
                    output_str = yaml.dump(report, default_flow_style=False, sort_keys=False)
                except ImportError:
                    output_str = json_mod.dumps(report, indent=2)
                    console.print("[yellow]PyYAML not installed, using JSON[/yellow]")
            elif format_opt == "text":
                lines = [f"Device Report: {report['device']}", "=" * 50]
                if "info" in report:
                    lines.append(f"Model: {report['info'].get('model', '-')}")
                    lines.append(f"Serial: {report['info'].get('serial_number', '-')}")
                    lines.append(f"Firmware: {report['info'].get('firmware', '-')}")
                if "network" in report:
                    lines.append(f"IP: {report['network'].get('ip_address', '-')}")
                    lines.append(f"MAC: {report['network'].get('mac_address', '-')}")
                if "lldp" in report and report["lldp"]["neighbors"]:
                    lines.append(f"Connected to: {report['lldp']['neighbors'][0].get('system', '-')}")
                output_str = "\n".join(lines)
            else:
                output_str = json_mod.dumps(report, indent=2)

            # Output
            if output:
                output.write_text(output_str)
                console.print(f"[green]Report saved to:[/green] {output}")
            else:
                console.print(output_str)

    run_async(_generate_report())


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
        console.print(f"\n[dim]* = default device[/dim]")


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
    import os
    os.chmod(new_config, 0o600)

    # Also copy .env if it exists
    legacy_env = legacy_dir / ".env"
    if legacy_env.exists():
        new_env = new_dir / ".env"
        shutil.copy2(legacy_env, new_env)
        os.chmod(new_env, 0o600)
        console.print(f"[green]Copied .env file[/green]")

    console.print(f"[green]Config migrated to:[/green] {new_config}")
    console.print("\n[dim]Legacy config preserved at original location.[/dim]")
    console.print("[dim]Delete ~/.config/axis/ manually when ready.[/dim]")


# =============================================================================
# Download Commands
# =============================================================================


@download_app.command("report")
def download_server_report(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o",
            help="Output file path. If not specified, auto-generates filename.",
        ),
    ] = None,
    format_opt: Annotated[
        str,
        typer.Option(
            "--format", "-f",
            help="Report format: zip_with_image (default), zip, or text.",
        ),
    ] = "zip_with_image",
    timeout: Annotated[
        float,
        typer.Option(
            "--timeout", "-t",
            help="Download timeout in seconds.",
        ),
    ] = 60.0,
    digest: DigestOption = True,
):
    """Download server report from an AXIS device.

    The server report contains diagnostic information including system logs,
    configuration, and optionally a snapshot image.

    Examples:
        axiscam download report -d front_of_house -o ~/report.zip
        axiscam download report -d camera1 --format text -o ~/report.txt
        axiscam download report -H 192.168.1.10 -u admin -p secret
    """
    # Resolve device configuration
    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )

    # Map format string to enum
    format_map = {
        "zip_with_image": ServerReportFormat.ZIP_WITH_IMAGE,
        "zip": ServerReportFormat.ZIP,
        "text": ServerReportFormat.TEXT,
    }
    report_format = format_map.get(format_opt.lower())
    if not report_format:
        console.print(f"[red]Error:[/red] Invalid format '{format_opt}'")
        console.print("Valid formats: zip_with_image, zip, text")
        raise typer.Exit(1)

    # Determine output filename
    if not output:
        device_name = device or host_addr.replace(".", "_")
        ext = ".txt" if report_format == ServerReportFormat.TEXT else ".zip"
        output = Path(f"server_report_{device_name}{ext}")

    device_class = get_device_class(device_type)

    async def _download():
        async with device_class(host_addr, user, passwd, port_num, use_digest_auth=digest) as dev:
            with console.status(f"[bold blue]Downloading server report from {host_addr}...[/bold blue]"):
                report = await dev.download_server_report(
                    format=report_format,
                    timeout=timeout,
                )

            if not report.success:
                console.print(f"[red]Error:[/red] {report.error}")
                raise typer.Exit(1)

            # Write to file
            output.write_bytes(report.content)
            size_kb = report.size_bytes / 1024
            console.print(f"[green]Server report downloaded:[/green] {output}")
            console.print(f"[dim]Size: {size_kb:.1f} KB, Format: {report_format.value}[/dim]")

    run_async(_download())


@download_app.command("debug")
def download_debug_archive(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = 443,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o",
            help="Output file path. If not specified, auto-generates filename.",
        ),
    ] = None,
    timeout: Annotated[
        float,
        typer.Option(
            "--timeout", "-t",
            help="Download timeout in seconds (debug archives can be large).",
        ),
    ] = 120.0,
    digest: DigestOption = True,
):
    """Download debug archive from an AXIS device.

    The debug archive (debug.tgz) is a comprehensive diagnostic package
    containing system logs, configuration files, core dumps, and other
    debugging information. This file is typically requested by AXIS
    technical support for troubleshooting.

    Note: Debug archives can be large and may take longer to generate
    and download. The default timeout is 120 seconds.

    Examples:
        axiscam download debug -d front_of_house -o ~/debug.tgz
        axiscam download debug -d camera1 --timeout 180
        axiscam download debug -H 192.168.1.10 -u admin -p secret
    """
    # Resolve device configuration
    host_addr, user, passwd, port_num, device_type = resolve_device_config(
        device, host, username, password, port
    )

    # Determine output filename
    if not output:
        device_name = device or host_addr.replace(".", "_")
        output = Path(f"debug_{device_name}.tgz")

    device_class = get_device_class(device_type)

    async def _download():
        async with device_class(host_addr, user, passwd, port_num, use_digest_auth=digest) as dev:
            with console.status(f"[bold blue]Downloading debug archive from {host_addr}...[/bold blue]"):
                report = await dev.download_debug_archive(timeout=timeout)

            if not report.success:
                console.print(f"[red]Error:[/red] {report.error}")
                raise typer.Exit(1)

            # Write to file
            output.write_bytes(report.content)
            size_kb = report.size_bytes / 1024
            if size_kb > 1024:
                size_str = f"{size_kb / 1024:.1f} MB"
            else:
                size_str = f"{size_kb:.1f} KB"
            console.print(f"[green]Debug archive downloaded:[/green] {output}")
            console.print(f"[dim]Size: {size_str}[/dim]")

    run_async(_download())


def main():
    """Main entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
