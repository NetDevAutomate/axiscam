"""``axiscam download``: server reports and the crash report.

Both artefacts describe the device in detail, so every file is written with
``0600`` permissions via :func:`axis_cam.files.write_private`. The crash
report additionally carries a notice: Axis's privacy statement says it can
include user IDs, passwords, video images and network traffic.
"""

from pathlib import Path
from typing import Annotated

import typer

from axis_cam.cli.app import (
    console,
    download_app,
    run_async,
)
from axis_cam.cli.context import DeviceContext, resolve_device_config
from axis_cam.cli.options import (
    DeviceOption,
    DigestOption,
    HostOption,
    PasswordOption,
    PortOption,
    UsernameOption,
)
from axis_cam.files import write_private
from axis_cam.models import ServerReport, ServerReportFormat

#: The web UI says generating the crash report "can take several minutes".
CRASH_REPORT_TIMEOUT = 300.0

CRASH_REPORT_NOTICE = (
    "The crash report contains the server report plus detailed debug data. "
    "Axis's privacy statement says it can include user IDs, passwords, video "
    "images and network traffic. The file is written with 0600 permissions; "
    "share it only with Axis support."
)

OutputOption = Annotated[
    Path | None,
    typer.Option(
        "--output",
        "-o",
        help="Output file path. If not specified, auto-generates filename.",
    ),
]


def _default_name(prefix: str, device: str | None, target: DeviceContext, ext: str) -> Path:
    device_name = device or target.host.replace(".", "_")
    return Path(f"{prefix}_{device_name}{ext}")


def _size(report: ServerReport) -> str:
    size_kb = report.size_bytes / 1024
    return f"{size_kb / 1024:.1f} MB" if size_kb > 1024 else f"{size_kb:.1f} KB"


def _save(report: ServerReport, output: Path, label: str) -> None:
    """Fail on a device-side error, otherwise write the artefact privately."""
    if not report.success:
        console.print(f"[red]Error:[/red] {report.error}")
        raise typer.Exit(1)
    write_private(output, report.content)
    console.print(f"[green]{label} downloaded:[/green] {output}")
    console.print(f"[dim]Size: {_size(report)}, permissions 0600[/dim]")


@download_app.command("report")
def download_server_report(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    output: OutputOption = None,
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
    """Download the server report from an AXIS device.

    The server report contains diagnostic information including system logs,
    configuration, and (by default) a snapshot image. The file is written
    with 0600 permissions.

    Examples:
        axiscam download report -d front_of_house -o ~/report.zip
        axiscam download report -d camera1 --format text -o ~/report.txt
        axiscam download report -H 192.168.1.10 -u admin -p secret
    """
    target = resolve_device_config(device, host, username, password, port, digest=digest)

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

    ext = ".txt" if report_format == ServerReportFormat.TEXT else ".zip"
    destination = output or _default_name("server_report", device, target, ext)

    async def _download():
        async with target.open() as dev:
            with console.status(
                f"[bold blue]Downloading server report from {target.host}...[/bold blue]"
            ):
                report = await dev.serverreport.download_report(
                    format=report_format,
                    timeout=timeout,
                )
            _save(report, destination, "Server report")
            console.print(f"[dim]Format: {report_format.value}[/dim]")

    run_async(_download())


def _download_crash_report(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    output: OutputOption = None,
    timeout: Annotated[
        float,
        typer.Option(
            "--timeout",
            "-t",
            help="Download timeout in seconds (the device may take minutes to build the archive).",
        ),
    ] = CRASH_REPORT_TIMEOUT,
    digest: DigestOption = True,
):
    """Download the crash report (debug archive, debug.tgz) from an AXIS device.

    This is what the web interface calls "Download the crash report": the
    server report plus detailed debug information such as core dumps and
    network traces, as requested by AXIS technical support. It can include
    user IDs, passwords, video images and network traffic, so the file is
    written with 0600 permissions.

    Examples:
        axiscam download crash-report -d front_of_house -o ~/crash.tgz
        axiscam download crash-report -d camera1 --timeout 600
    """
    target = resolve_device_config(device, host, username, password, port, digest=digest)
    destination = output or _default_name("crash_report", device, target, ".tgz")
    console.print(f"[yellow]Notice:[/yellow] {CRASH_REPORT_NOTICE}")

    async def _download():
        async with target.open() as dev:
            with console.status(
                f"[bold blue]Downloading crash report from {target.host}...[/bold blue]"
            ):
                report = await dev.serverreport.get_debug_archive(timeout=timeout)
            _save(report, destination, "Crash report")

    run_async(_download())


download_app.command("crash-report")(_download_crash_report)
# Older name for the same artefact; kept working but not advertised.
download_app.command("debug", hidden=True)(_download_crash_report)
