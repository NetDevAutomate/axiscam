"""``axiscam services``: SNMP and NTP."""

from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from axis_cam.auth import AuthMode
from axis_cam.cli.app import (
    console,
    emit_json,
    run_async,
    services_app,
)
from axis_cam.cli.context import resolve_device_config
from axis_cam.cli.options import (
    AuthOption,
    DeviceOption,
    HostOption,
    PasswordOption,
    PortOption,
    UsernameOption,
)


@services_app.command("snmp")
def services_snmp(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
):
    """Show SNMP state. Community strings are never shown: only whether they are set/default."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _show_snmp():
        async with target.open() as dev:
            config = await dev.snmp.read()
            if json_output:
                emit_json(config.model_dump(mode="json"))
                return

            status = "[green]Enabled[/green]" if config.enabled else "[red]Disabled[/red]"
            versions = ", ".join(
                name
                for name, on in (
                    ("v1", config.v1_enabled),
                    ("v2c", config.v2c_enabled),
                    ("v3", config.v3_enabled),
                )
                if on
            )
            console.print(
                Panel(
                    f"Status: {status}\nVersions: {versions or '-'}\n"
                    f"Transport: {config.transport_protocol}",
                    title=f"SNMP: {target.host}",
                )
            )
            table = Table(title="SNMP settings", show_header=False)
            table.add_column("Setting", style="cyan")
            table.add_column("Value", style="white")
            table.add_row(
                "Read community",
                "[red]default (public)[/red]" if config.read_community_is_default else "set",
            )
            table.add_row("Write community", "set" if config.write_community_set else "not set")
            table.add_row(
                "SNMPv3 user password", "set" if config.v3_password_set else "[dim]not set[/dim]"
            )
            table.add_row("SNMPv3 encryption", config.v3_encryption or "-")
            table.add_row(
                "Traps",
                f"enabled → {config.trap_address or '-'}" if config.trap_enabled else "disabled",
            )
            console.print(table)

    run_async(_show_snmp())


@services_app.command("ntp")
def services_ntp(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
):
    """Show NTP/PTP state."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _show_ntp():
        async with target.open() as dev:
            config = await dev.ntp.read()
            if json_output:
                emit_json(config.model_dump(mode="json"))
                return

            status = "[green]Enabled[/green]" if config.enabled else "[red]Disabled[/red]"
            synced = "[green]Yes[/green]" if config.synced else "[red]No[/red]"
            console.print(
                Panel(
                    f"Status: {status}\nSynchronised: {synced}\n"
                    f"Servers from: {config.servers_source or '-'}   "
                    f"Offset: {config.time_offset_s:+.3f}s\n"
                    f"NTS: {'on' if config.nts_enabled else 'off'}   "
                    f"PTP: {config.ptp_port_state or '-'}"
                    f"{'' if config.ptp_supported else ' (unsupported)'}",
                    title=f"NTP: {target.host}",
                )
            )
            servers = [(s, "static") for s in config.static_servers] + [
                (s, "DHCP") for s in config.advertised_servers
            ]
            if servers:
                table = Table(title=f"NTP servers ({len(servers)})")
                table.add_column("Server", style="cyan")
                table.add_column("Source", style="white")
                for address, source in servers:
                    table.add_row(address, source)
                console.print(table)
            else:
                console.print("[yellow]No NTP servers configured[/yellow]")

    run_async(_show_ntp())
