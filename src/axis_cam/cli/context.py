"""Resolving a command's device options into an open device.

Every device command takes the same options (``--device``/``--host``,
credentials, ``--port``, ``--auth``). :func:`resolve_device_config` turns
them, plus the config file, into one :class:`DeviceContext`; ``open()`` on
that context is the single place the device class is instantiated, so
transport settings (``https``, ``ssl_verify``, ``timeout``) cannot be dropped
on the way.
"""

from dataclasses import dataclass

import typer

from axis_cam import AxisCamera, AxisIntercom, AxisRecorder, AxisSpeaker
from axis_cam.auth import AuthMode
from axis_cam.cli.app import console
from axis_cam.config import DeviceConfig, load_config
from axis_cam.devices.base import AxisDevice


def get_device_class(device_type: str) -> type[AxisDevice]:
    """Get the appropriate device class for a device type.

    Args:
        device_type: Device type string.

    Returns:
        Device class for the type; ``AxisCamera`` for unknown types.
    """
    type_map: dict[str, type[AxisDevice]] = {
        "camera": AxisCamera,
        "recorder": AxisRecorder,
        "intercom": AxisIntercom,
        "speaker": AxisSpeaker,
    }
    return type_map.get(device_type.lower(), AxisCamera)


@dataclass(frozen=True)
class DeviceContext:
    """Everything needed to open one device, resolved from options and config.

    Attributes:
        host: Device address.
        username: Authentication username.
        password: Authentication password.
        port: TCP port.
        device_type: ``camera`` / ``recorder`` / ``intercom`` / ``speaker``.
        https: Use HTTPS (never inferred from the port).
        ssl_verify: Verify the device certificate.
        timeout: Request timeout in seconds.
        auth_mode: ``auto`` (follow the device's challenge), ``basic`` or ``digest``.
    """

    host: str
    username: str
    password: str
    port: int
    device_type: str
    https: bool = True
    ssl_verify: bool = False
    timeout: float = 30.0
    auth_mode: AuthMode = AuthMode.AUTO

    def open(self) -> AxisDevice:
        """Instantiate the device class for ``device_type`` with these parameters."""
        return get_device_class(self.device_type)(
            self.host,
            self.username,
            self.password,
            self.port,
            ssl_verify=self.ssl_verify,
            timeout=self.timeout,
            auth_mode=self.auth_mode,
            https=self.https,
        )


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
    return DeviceContext(
        host=config.host,
        username=username or config.username,
        password=password or config.password.get_secret_value(),
        port=port if port is not None else config.port,
        device_type=config.device_type,
        https=config.https,
        ssl_verify=config.ssl_verify,
        timeout=timeout,
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
