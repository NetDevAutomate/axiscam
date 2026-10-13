"""``axiscam download``: server reports and the debug archive."""

from pathlib import Path
from typing import Annotated

import typer

from axis_cam.cli.app import (
    console,
    download_app,
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
from axis_cam.models import ServerReportFormat


@download_app.command("report")
def download_server_report(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Output file path. If not specified, auto-generates filename.",
        ),
    ] = None,
    format_opt: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Report format: zip_with_image (default), zip, or text.",
        ),
    ] = "zip_with_image",
    timeout: Annotated[
        float,
        typer.Option(
            "--timeout",
            "-t",
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
    target = resolve_device_config(device, host, username, password, port, digest=digest)

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
        device_name = device or target.host.replace(".", "_")
        ext = ".txt" if report_format == ServerReportFormat.TEXT else ".zip"
        output = Path(f"server_report_{device_name}{ext}")

    async def _download():
        async with target.open() as dev:
            with console.status(
                f"[bold blue]Downloading server report from {target.host}...[/bold blue]"
            ):
                report = await dev.serverreport.download_report(
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
    port: PortOption = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Output file path. If not specified, auto-generates filename.",
        ),
    ] = None,
    timeout: Annotated[
        float,
        typer.Option(
            "--timeout",
            "-t",
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
    target = resolve_device_config(device, host, username, password, port, digest=digest)

    # Determine output filename
    if not output:
        device_name = device or target.host.replace(".", "_")
        output = Path(f"debug_{device_name}.tgz")

    async def _download():
        async with target.open() as dev:
            with console.status(
                f"[bold blue]Downloading debug archive from {target.host}...[/bold blue]"
            ):
                report = await dev.serverreport.get_debug_archive(timeout=timeout)

            if not report.success:
                console.print(f"[red]Error:[/red] {report.error}")
                raise typer.Exit(1)

            # Write to file
            output.write_bytes(report.content)
            size_kb = report.size_bytes / 1024
            size_str = f"{size_kb / 1024:.1f} MB" if size_kb > 1024 else f"{size_kb:.1f} KB"
            console.print(f"[green]Debug archive downloaded:[/green] {output}")
            console.print(f"[dim]Size: {size_str}[/dim]")

    run_async(_download())
