"""``axiscam security``: firewall, SSH and certificates."""

from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from axis_cam.cli.app import (
    console,
    emit_json,
    run_async,
    security_app,
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


@security_app.command("firewall")
def security_firewall(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    digest: DigestOption = True,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
):
    """Show firewall configuration."""
    target = resolve_device_config(device, host, username, password, port, digest=digest)

    async def _show_firewall():
        async with target.open() as dev:
            config = await dev.firewall.get_config()

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
                emit_json(data)
                return

            # Status panel
            status = "[green]Enabled[/green]" if config.enabled else "[red]Disabled[/red]"
            policy_color = "green" if config.default_policy.value == "allow" else "red"
            policy_val = config.default_policy.value.upper()
            panel_content = (
                f"Status: {status}\nDefault Policy: [{policy_color}]{policy_val}[/{policy_color}]"
            )
            console.print(Panel(panel_content, title=f"Firewall: {target.host}"))

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
                    enabled = "[green]Yes[/green]" if rule.enabled else "[red]No[/red]"
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
    port: PortOption = None,
    digest: DigestOption = True,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
):
    """Show SSH configuration."""
    target = resolve_device_config(device, host, username, password, port, digest=digest)

    async def _show_ssh():
        async with target.open() as dev:
            config = await dev.ssh.get_config()

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
                emit_json(data)
                return

            # Status panel
            status = "[green]Enabled[/green]" if config.enabled else "[red]Disabled[/red]"
            console.print(
                Panel(
                    f"Status: {status}\nPort: {config.port}",
                    title=f"SSH Configuration: {target.host}",
                )
            )

            # Settings table
            table = Table(title="SSH Settings", show_header=False)
            table.add_column("Setting", style="cyan")
            table.add_column("Value", style="white")
            table.add_row(
                "Root Login",
                "[green]Enabled[/green]" if config.root_login_enabled else "[red]Disabled[/red]",
            )
            table.add_row(
                "Password Auth",
                "[green]Enabled[/green]" if config.password_auth_enabled else "[red]Disabled[/red]",
            )
            console.print(table)

            # Authorized keys
            if config.authorized_keys:
                keys_table = Table(title=f"Authorized Keys ({len(config.authorized_keys)})")
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
    port: PortOption = None,
    digest: DigestOption = True,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
):
    """Show certificate configuration."""
    target = resolve_device_config(device, host, username, password, port, digest=digest)

    async def _show_certs():
        async with target.open() as dev:
            config = await dev.cert.get_config()

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
                emit_json(data)
                return

            # Status panel
            cert_id = config.https_cert_id or "(default)"
            client_auth = (
                "[green]Enabled[/green]" if config.client_cert_enabled else "[red]Disabled[/red]"
            )
            panel_content = (
                f"HTTPS Certificate ID: [cyan]{cert_id}[/cyan]\nClient Cert Auth: {client_auth}"
            )
            console.print(Panel(panel_content, title=f"Certificate Configuration: {target.host}"))

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
                    valid_to = cert.valid_to.strftime("%Y-%m-%d") if cert.valid_to else "-"
                    status = (
                        "[green]Valid[/green]" if cert.is_valid else "[red]Invalid/Expired[/red]"
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
