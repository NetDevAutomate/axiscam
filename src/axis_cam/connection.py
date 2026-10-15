"""Opening a device from resolved settings — no console, no CLI.

:class:`DeviceConnection` is the single place a device class is instantiated,
so transport settings (``https``, ``ssl_verify``, ``timeout``, ``auth_mode``)
cannot be dropped on the way from a config entry to a client. The CLI's
``DeviceContext`` and the MCP server's device resolver are both this type.

The password is excluded from ``repr`` on purpose: a traceback, a log line or
a debugger that prints the object must not print the credential.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

from axis_cam.auth import AuthMode
from axis_cam.devices import AxisCamera, AxisIntercom, AxisRecorder, AxisSpeaker

if TYPE_CHECKING:
    from collections.abc import Mapping

    from axis_cam.config import DeviceConfig
    from axis_cam.devices.base import AxisDevice

#: Device type (as written in the config file) → class. Unknown types are cameras.
DEVICE_CLASSES: Mapping[str, type[AxisDevice]] = MappingProxyType(
    {
        "camera": AxisCamera,
        "recorder": AxisRecorder,
        "intercom": AxisIntercom,
        "speaker": AxisSpeaker,
    }
)


def get_device_class(device_type: str) -> type[AxisDevice]:
    """Return the device class for a config ``device_type`` (``AxisCamera`` if unknown)."""
    return DEVICE_CLASSES.get(device_type.lower(), AxisCamera)


@dataclass(frozen=True)
class DeviceConnection:
    """Everything needed to open one device.

    Attributes:
        host: Device address.
        username: Authentication username.
        password: Authentication password (never part of ``repr``).
        port: TCP port.
        device_type: ``camera`` / ``recorder`` / ``intercom`` / ``speaker``.
        https: Use HTTPS (never inferred from the port).
        ssl_verify: Verify the device certificate.
        timeout: Request timeout in seconds.
        auth_mode: ``auto`` (follow the device's challenge), ``basic`` or ``digest``.
    """

    host: str
    username: str
    password: str = field(repr=False)
    port: int = 443
    device_type: str = "camera"
    https: bool = True
    ssl_verify: bool = False
    timeout: float = 30.0
    auth_mode: AuthMode = AuthMode.AUTO

    def open(self) -> AxisDevice:
        """Instantiate the device class for ``device_type`` with these settings.

        The device is an async context manager; nothing is sent until it is
        entered or a method is awaited.
        """
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

    @classmethod
    def from_config(
        cls,
        config: DeviceConfig,
        *,
        timeout: float,
        username: str | None = None,
        password: str | None = None,
        port: int | None = None,
        auth_mode: AuthMode = AuthMode.AUTO,
    ) -> DeviceConnection:
        """Build a connection from a config entry, with optional overrides.

        Args:
            config: The device's entry in the config file.
            timeout: Request timeout (the app-level setting).
            username: Override the configured username.
            password: Override the configured password.
            port: Override the configured port.
            auth_mode: Authentication scheme policy.
        """
        return cls(
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


__all__ = ["DEVICE_CLASSES", "DeviceConnection", "get_device_class"]
