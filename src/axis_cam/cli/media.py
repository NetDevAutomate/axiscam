"""``axiscam media``: recording groups and remote storage."""

from rich.table import Table

from axis_cam.cli.app import (
    console,
    emit_json,
    media_app,
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
    target = resolve_device_config(device, host, username, password, port, digest=digest)

    async def _show_recording():
        async with target.open() as dev:
            config = await dev.recording.get_config()

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
                emit_json(data)
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
    target = resolve_device_config(device, host, username, password, port, digest=digest)

    async def _show_storage():
        async with target.open() as dev:
            config = await dev.storage.get_config()

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
                emit_json(data)
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
