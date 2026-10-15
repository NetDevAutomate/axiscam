"""Resolving a command's device options into an open device.

Every device command takes the same options (``--device``/``--host``,
credentials, ``--port``, ``--auth``). :func:`resolve_device_config` turns
them, plus the config file, into one :class:`DeviceContext` — the library's
:class:`~axis_cam.connection.DeviceConnection`, whose ``open()`` is the single
place the device class is instantiated, so transport settings (``https``,
``ssl_verify``, ``timeout``) cannot be dropped on the way. This module adds
only what is CLI-specific: option precedence and console error messages.
"""

import typer

from axis_cam.auth import AuthMode
from axis_cam.cli.app import console
from axis_cam.config import DeviceConfig, load_config
from axis_cam.connection import DeviceConnection, get_device_class

__all__ = [
    "DeviceContext",
    "get_device_class",
    "resolve_device_config",
    "select_targets",
]

#: The CLI's name for a resolved device: the library's connection type. Kept as
#: an alias so every command module (and its tests) reads the same way.
DeviceContext = DeviceConnection


def _from_config(
    config: DeviceConfig,
    *,
    username: str | None,
    password: str | None,
    port: int | None,
    timeout: float,
    auth_mode: AuthMode,
) -> DeviceContext:
    """Build a DeviceContext from a config entry plus CLI overrides."""
    return DeviceContext.from_config(
        config,
        timeout=timeout,
        username=username,
        password=password,
        port=port,
        auth_mode=auth_mode,
    )


def _ad_hoc(
    host: str,
    username: str | None,
    password: str | None,
    port: int | None,
    *,
    timeout: float,
    auth_mode: AuthMode,
) -> DeviceContext:
    """A device given by address only: credentials required, secure defaults."""
    if not username or not password:
        console.print(
            "[red]Error:[/red] Username and password are required for a device "
            "that is not in the config file",
            style="bold",
        )
        raise typer.Exit(1)
    return DeviceContext(
        host=host,
        username=username,
        password=password,
        port=port if port is not None else 443,
        device_type="camera",
        timeout=timeout,
        auth_mode=auth_mode,
    )


def select_targets(
    *,
    all_devices: bool,
    group: str | None,
    username: str | None = None,
    password: str | None = None,
    port: int | None = None,
    auth_mode: AuthMode = AuthMode.AUTO,
) -> list[tuple[str, DeviceContext]]:
    """Resolve the devices a fleet command runs against, in config order.

    ``--all`` is every configured device; ``--group NAME`` is every device whose
    ``groups`` contain NAME or whose type is NAME. Overrides (``--username``,
    ``--password``, ``--port``) apply to every selected device.

    Raises:
        typer.Exit: Nothing configured, or the group matches no device.
    """
    app_config = load_config()
    if not app_config.devices:
        console.print(
            "[red]Error:[/red] no devices in the config file; fleet commands need "
            "configured devices",
            style="bold",
        )
        raise typer.Exit(1)
    selected = [
        (name, config)
        for name, config in app_config.devices.items()
        if all_devices or (group is not None and config.in_group(group))
    ]
    if not selected:
        known = sorted({config.device_type for config in app_config.devices.values()})
        tags = sorted({g for config in app_config.devices.values() for g in config.groups})
        console.print(
            f"[red]Error:[/red] no device is in group '{group}'. Types: {', '.join(known)}"
            + (f"; tags: {', '.join(tags)}" if tags else "; no tags configured"),
            style="bold",
        )
        raise typer.Exit(1)
    return [
        (
            name,
            _from_config(
                config,
                username=username,
                password=password,
                port=port,
                timeout=app_config.timeout,
                auth_mode=auth_mode,
            ),
        )
        for name, config in selected
    ]


def resolve_device_config(
    device: str | None,
    host: str | None,
    username: str | None,
    password: str | None,
    port: int | None = None,
    *,
    auth_mode: AuthMode = AuthMode.AUTO,
) -> DeviceContext:
    """Resolve device connection parameters from options or config.

    Precedence: ``--host`` (ad hoc; credentials required) > named device in
    config (or the default device) > ``--device`` that looks like an address
    (config lookup by host, else ad hoc). An explicit ``--port`` always wins
    over the configured port. Ad hoc devices use HTTPS.

    Args:
        device: Device name from config, or a host address.
        host: Direct host address (overrides --device).
        username: Username override.
        password: Password override.
        port: Port override; ``None`` means the configured port, else 443.
        auth_mode: Authentication scheme policy (default: follow the device's challenge).

    Returns:
        DeviceContext carrying everything the device class needs, including
        https, ssl_verify and timeout from config.

    Raises:
        typer.Exit: If required parameters are missing.
    """
    app_config = load_config()

    if host:
        return _ad_hoc(
            host, username, password, port, timeout=app_config.timeout, auth_mode=auth_mode
        )

    # Named device, or the configured default device.
    name = device or app_config.default_device
    if name and name in app_config.devices:
        return _from_config(
            app_config.devices[name],
            username=username,
            password=password,
            port=port,
            timeout=app_config.timeout,
            auth_mode=auth_mode,
        )

    # --device that looks like a host/IP: config lookup by host, else ad hoc.
    if device and ("." in device or device.replace(".", "").isdigit()):
        for config in app_config.devices.values():
            if config.host == device:
                return _from_config(
                    config,
                    username=username,
                    password=password,
                    port=port,
                    timeout=app_config.timeout,
                    auth_mode=auth_mode,
                )
        return _ad_hoc(
            device, username, password, port, timeout=app_config.timeout, auth_mode=auth_mode
        )

    console.print(
        "[red]Error:[/red] No device specified. Use --device or --host",
        style="bold",
    )
    raise typer.Exit(1)
