"""Device-level commands: info, status, apis, lldp, params, location, report."""

from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from axis_cam.auth import AuthMode
from axis_cam.cli.app import (
    app,
    console,
    emit_json,
    run_async,
)
from axis_cam.cli.context import resolve_device_config
from axis_cam.cli.options import (
    AuthOption,
    DeviceOption,
    HostOption,
    JsonOption,
    PasswordOption,
    PortOption,
    UsernameOption,
)
from axis_cam.exceptions import AxisApiNotSupportedError, AxisDeviceError
from axis_cam.files import write_private
from axis_cam.report import DeviceReport, collect_report, render_text


@app.command("info")
def device_info(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
):
    """Get device information.

    Displays basic device info including model, serial number,
    firmware version, and available capabilities.
    """
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _get_info():
        async with target.open() as dev:
            info = await dev.get_info()
            capabilities = await dev.get_capabilities()

            # Time API may not be available on all devices (e.g., speakers)
            try:
                time_info = await dev.time.get_info()
            except (AxisDeviceError, AxisApiNotSupportedError):
                time_info = None

            # Create info table
            table = Table(title=f"Device Info: {target.host}", show_header=False)
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
            table.add_row("Device Type", target.device_type.capitalize())
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
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
):
    """Check device status and connectivity."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _check_status():
        async with target.open() as dev:
            status = await dev.get_status()

            panel = Panel(
                "[green]Reachable[/green]" if status.reachable else "[red]Unreachable[/red]",
                title=f"Status: {target.host}",
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
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
):
    """List available APIs on the device."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _list_apis():
        async with target.open() as dev:
            capabilities = await dev.get_capabilities()

            tree = Tree(f"[bold]APIs on {target.host}[/bold]")

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
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
):
    """Show LLDP neighbor information.

    Displays discovered network neighbors via LLDP (Link Layer Discovery Protocol).
    Shows the switch/device the camera is connected to, including port information.
    """
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _show_lldp():
        async with target.open() as dev:
            lldp_info = await dev.lldp.get_info()

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
                emit_json(data)
                return

            # Status panel
            status = "[green]Enabled[/green]" if lldp_info.activated else "[red]Disabled[/red]"
            console.print(Panel(f"LLDP Status: {status}", title=f"LLDP Info: {target.host}"))

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
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    group: Annotated[
        str | None, typer.Option("--group", "-g", help="Parameter group to list")
    ] = None,
    search: Annotated[str | None, typer.Option("--search", "-s", help="Search pattern")] = None,
    export: Annotated[bool, typer.Option("--export", "-e", help="Export as JSON")] = False,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output file")] = None,
):
    """List device parameters."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _list_params():
        async with target.open() as dev:
            if export:
                # Export all parameters as JSON
                import json

                data = await dev.params.export()
                json_output = json.dumps(data, indent=2, sort_keys=True)

                if output:
                    write_private(output, json_output.encode())
                    console.print(f"[green]Exported parameters to:[/green] {output} (0600)")
                else:
                    typer.echo(json_output)  # not console.print: Rich would wrap long lines
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


@app.command("location")
def show_location(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    json_output: JsonOption = False,
):
    """Show device geolocation configuration."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _show_location():
        async with target.open() as dev:
            config = await dev.geolocation.get_config()

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
                emit_json(data)
                return

            # Check if location is configured
            if config.latitude is None and config.longitude is None:
                console.print("[yellow]No geolocation configured[/yellow]")
                return

            # Location table
            table = Table(title=f"Geolocation: {target.host}", show_header=False)
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


@app.command("report")
def device_report(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output file")] = None,
    format_opt: Annotated[
        str, typer.Option("--format", "-f", help="Output format (json, yaml, text)")
    ] = "json",
    full: Annotated[
        bool, typer.Option("--full", help="Include every resource the device advertises")
    ] = False,
):
    """Generate a device report from every available configuration module.

    The default report covers device info, time, network, LLDP, stream
    diagnostics, firewall and NTP. Use --full to read every resource the
    device advertises via API discovery. Sections are keyed by module name
    and hold the complete model; per-module failures are listed under
    "errors" and modules the device does not advertise under "skipped".
    """
    import json as json_mod

    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _generate_report() -> DeviceReport:
        async with target.open() as dev:
            return await collect_report(dev, full=full, name=device or target.host)

    report = run_async(_generate_report())

    if format_opt == "yaml":
        try:
            import yaml

            output_str = yaml.dump(report.to_dict(), default_flow_style=False, sort_keys=False)
        except ImportError:
            output_str = json_mod.dumps(report.to_dict(), indent=2)
            console.print("[yellow]PyYAML not installed, using JSON[/yellow]")
    elif format_opt == "text":
        output_str = render_text(report)
    else:
        output_str = json_mod.dumps(report.to_dict(), indent=2)

    if output:
        write_private(output, output_str.encode())
        console.print(f"[green]Report saved to:[/green] {output} (0600)")
    else:
        # Plain echo: Rich would soft-wrap long lines and corrupt piped JSON.
        typer.echo(output_str)
