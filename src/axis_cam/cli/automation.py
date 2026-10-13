"""``axiscam automation``: action rules and the MQTT event bridge."""

from rich.panel import Panel
from rich.table import Table

from axis_cam.cli.app import (
    automation_app,
    console,
    run_async,
)
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

    target = resolve_device_config(device, host, username, password, port, digest=digest)

    async def _show_actions():
        async with target.open() as dev:
            config = await dev.action.get_config()

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
                    table.add_row(rule.id, rule.name, enabled, rule.primary_condition or "-")
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

    target = resolve_device_config(device, host, username, password, port, digest=digest)

    async def _show_mqtt():
        async with target.open() as dev:
            config = await dev.mqtt.get_config()

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
                    title=f"MQTT Bridge: {target.host}",
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
