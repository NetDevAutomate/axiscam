"""``axiscam network``: interfaces and DNS."""

from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from axis_cam.cli.app import (
    console,
    emit_json,
    network_app,
    run_async,
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


@network_app.command("show")
def network_show(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    digest: DigestOption = True,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
):
    """Show network configuration."""
    target = resolve_device_config(device, host, username, password, port, digest=digest)

    async def _show_network():
        async with target.open() as dev:
            config = await dev.network.get_config()

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
                emit_json(data)
                return

            # Main info panel
            console.print(
                Panel(
                    f"Hostname: [cyan]{config.hostname}[/cyan]",
                    title=f"Network Config: {target.host}",
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
                    dhcp = "[green]Yes[/green]" if iface.dhcp_enabled else "[red]No[/red]"
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
                "[green]Enabled[/green]" if config.bonjour_enabled else "[red]Disabled[/red]",
            )
            svc_table.add_row(
                "UPnP",
                "[green]Enabled[/green]" if config.upnp_enabled else "[red]Disabled[/red]",
            )
            console.print(svc_table)

    run_async(_show_network())


@network_app.command("dns")
def network_dns(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    digest: DigestOption = True,
):
    """Show DNS configuration."""
    target = resolve_device_config(device, host, username, password, port, digest=digest)

    async def _show_dns():
        async with target.open() as dev:
            dns = await dev.network.get_dns()

            table = Table(title=f"DNS Configuration: {target.host}", show_header=False)
            table.add_column("Setting", style="cyan")
            table.add_column("Value", style="white")
            table.add_row("Primary DNS", dns.primary or "[dim](not set)[/dim]")
            table.add_row("Secondary DNS", dns.secondary or "[dim](not set)[/dim]")
            table.add_row("Domain", dns.domain or "[dim](not set)[/dim]")
            console.print(table)

    run_async(_show_dns())
