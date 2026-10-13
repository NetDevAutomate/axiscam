"""``axiscam services``: SNMP and NTP."""

from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from axis_cam.cli.app import (
    console,
    emit_json,
    run_async,
    services_app,
)
from axis_cam.cli.context import resolve_device_config
from axis_cam.cli.options import (
    DeviceOption,
    DigestOption,
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
    digest: DigestOption = True,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
):
    """Show SNMP configuration."""
    target = resolve_device_config(device, host, username, password, port, digest=digest)

    async def _show_snmp():
        async with target.open() as dev:
            config = await dev.snmp.get_config()

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
                emit_json(data)
                return

            # Status panel
            status = "[green]Enabled[/green]" if config.enabled else "[red]Disabled[/red]"
            console.print(
                Panel(
                    f"Status: {status}\nVersion: {config.version.value}",
                    title=f"SNMP Configuration: {target.host}",
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
                trap_table = Table(title=f"Trap Receivers ({len(config.trap_receivers)})")
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
    port: PortOption = None,
    digest: DigestOption = True,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
):
    """Show NTP configuration."""
    target = resolve_device_config(device, host, username, password, port, digest=digest)

    async def _show_ntp():
        async with target.open() as dev:
            config = await dev.ntp.get_config()

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
                emit_json(data)
                return

            # Status panel
            status = "[green]Enabled[/green]" if config.enabled else "[red]Disabled[/red]"
            dhcp = "[green]Yes[/green]" if config.use_dhcp_servers else "[red]No[/red]"
            console.print(
                Panel(
                    f"Status: {status}\nUse DHCP Servers: {dhcp}",
                    title=f"NTP Configuration: {target.host}",
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
