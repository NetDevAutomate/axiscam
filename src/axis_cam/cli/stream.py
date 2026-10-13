"""``axiscam stream``: RTSP/RTP/profile diagnostics."""

from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from axis_cam.cli.app import (
    console,
    run_async,
    stream_app,
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


@stream_app.command("show")
def stream_show(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    digest: DigestOption = True,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
):
    """Show stream diagnostics (RTSP, RTP, profiles).

    Displays streaming configuration useful for troubleshooting
    connectivity issues with third-party systems.
    """
    import json as json_mod

    target = resolve_device_config(device, host, username, password, port, digest=digest)

    async def _show_stream():
        async with target.open() as dev:
            diag = await dev.stream.get_diagnostics(device or target.host)

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
                    "[green]Enabled[/green]" if diag.rtsp.enabled else "[red]Disabled[/red]",
                    title=f"Stream Diagnostics: {target.host}",
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
