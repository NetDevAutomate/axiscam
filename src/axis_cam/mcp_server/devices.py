"""Which devices the server may touch, and how it opens them.

A tool never receives a host or a credential: its ``device`` argument is a
configured device *name*, validated against an enum built from the config file
when the server starts, so an address or an unknown name is refused by schema
validation before any tool code runs.

:class:`DeviceResolver` is the seam the tools are written against; the
production implementation reads the config file, tests substitute fakes. The
config loader is ``lru_cache``'d (``axis_cam.config.load_config``), so a
long-running server sees config edits only after a restart (decision D4) —
``describe``/``open`` go through the resolver per call so that is the only
staleness.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

from axis_cam.config import AppConfig, load_config
from axis_cam.connection import DeviceConnection
from axis_cam.exceptions import AxisConfigError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from axis_cam.devices.base import AxisDevice


class DeviceSummary(BaseModel):
    """What ``list_devices`` says about a device: identity, never credentials."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Configured device name; the value every tool's `device` takes.")
    device_type: str = Field(description="camera / recorder / intercom / speaker.")
    groups: list[str] = Field(default_factory=list, description="Fleet group tags from the config.")
    host: str = Field(description="Address the server connects to (informational).")


class DeviceResolver(Protocol):
    """The tools' view of the configured devices."""

    def names(self) -> list[str]:
        """Configured device names, in config order."""
        ...

    def describe(self, name: str) -> DeviceSummary:
        """Identity of one device."""
        ...

    def connection(self, name: str) -> DeviceConnection:
        """Resolved connection settings for one device (carries the password)."""
        ...

    def open(self, name: str) -> AxisDevice:
        """A fresh, not yet connected device object (an async context manager)."""
        ...

    def select(self, selection: str) -> list[str]:
        """Names matching ``"all"`` or a group tag / device type, in config order."""
        ...


class ConfigResolver:
    """``DeviceResolver`` over the axiscam config file.

    Args:
        loader: Returns the app config; defaults to the cached file loader.
    """

    def __init__(self, loader: Callable[[], AppConfig] = load_config) -> None:
        self._loader = loader

    def _config(self) -> AppConfig:
        return self._loader()

    def names(self) -> list[str]:
        """Configured device names, in config order."""
        return list(self._config().devices)

    def describe(self, name: str) -> DeviceSummary:
        """Identity of one configured device."""
        entry = self._config().devices[name]
        return DeviceSummary(
            name=name,
            device_type=entry.device_type,
            groups=list(entry.groups),
            host=entry.host,
        )

    def connection(self, name: str) -> DeviceConnection:
        """Connection settings for one configured device."""
        config = self._config()
        return DeviceConnection.from_config(config.devices[name], timeout=config.timeout)

    def open(self, name: str) -> AxisDevice:
        """A fresh, unconnected device object."""
        return self.connection(name).open()

    def select(self, selection: str) -> list[str]:
        """Names for 'all', a group tag or a device type."""
        devices = self._config().devices
        if selection == "all":
            return list(devices)
        return [name for name, entry in devices.items() if entry.in_group(selection)]


def device_enum(names: Sequence[str]) -> type[StrEnum]:
    """Build the ``device`` argument type: a string enum of configured names.

    Raises:
        AxisConfigError: No devices are configured — the server exposes only
            configured devices, so there would be nothing to serve.
    """
    if not names:
        raise AxisConfigError(
            "no devices in the config file; the MCP server exposes only configured devices"
        )
    return cast("type[StrEnum]", StrEnum("DeviceName", {name: name for name in names}))


__all__ = ["ConfigResolver", "DeviceResolver", "DeviceSummary", "device_enum"]
