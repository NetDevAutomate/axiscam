"""Shared fakes for the MCP server tests.

The server is exercised through the SDK's in-process ``Client(server)``, so
every test goes over the real tool/resource machinery (schemas, validation,
result envelopes). Devices are faked at the resolver boundary: a
``FakeResolver`` hands out ``FakeDevice`` objects whose modules return fixed
models or raise fixed errors. The resolver carries a canary password so the
secrets-boundary tests can assert it never appears anywhere.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, MagicMock

from axis_cam.connection import DeviceConnection
from axis_cam.exceptions import AxisApiNotSupportedError
from axis_cam.mcp_server.devices import DeviceSummary
from axis_cam.models import BasicDeviceInfo, SshConfig, SshUser, UserAccount, UserAccounts, UserRole

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from pydantic import BaseModel

    from axis_cam.devices.base import AxisDevice

CANARY = "Canary-Sup3r-S3cret!"  # pragma: allowlist secret
USERNAME = "admin"
#: What an HTTP Basic header would carry for the canary.
CANARY_BASIC = base64.b64encode(f"{USERNAME}:{CANARY}".encode()).decode()

INFO = BasicDeviceInfo(
    ProdNbr="M3216-LVE",
    SerialNumber="ACCC8E000001",
    Version="12.11.118",
)
SSH = SshConfig(enabled=True, users=[SshUser(username="ops")])
ACCOUNTS = UserAccounts(
    accounts=[
        UserAccount(username="admin", role=UserRole.ADMIN, ptz=True),
        UserAccount(username="second", role=UserRole.ADMIN, ptz=False),
        UserAccount(username="viewer1", role=UserRole.VIEWER, ptz=False),
    ]
)
PARAMS: dict[str, str] = {
    "root.Network.Bonjour.Enabled": "yes",
    "root.Network.Bonjour.FriendlyName": "AXIS M3216-LVE",
    "root.Network.UPnP.Enabled": "yes",
    "root.SNMP.Enabled": "no",
    "root.SNMP.ReadCommunity": "public",
    "root.SNMP.WriteCommunity": "s3cret-community",  # pragma: allowlist secret
    "root.Network.Proxy.Password": CANARY,
    "root.Network.Interface.I0.dot1x.EAPOL.KeyPassword": "k3y",  # pragma: allowlist secret
    "root.Properties.System.SerialNumber": "ACCC8E000001",
    "root.Image.I0.Name": "View Area 1",
}


class FakeModule:
    """A resource module: ``read()`` returns a model or raises."""

    def __init__(self, name: str, result: BaseModel | Exception, api_id: str | None = None) -> None:
        self.name = name
        self.api_id = api_id
        self._result = result

    async def read(self) -> BaseModel:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeDevice:
    """Enough of ``AxisDevice`` for the Phase A tools.

    Args:
        host: Reported host.
        modules: Resource modules on the device.
        advertised: Module names the device "advertises"; ``None`` means all.
        params: What ``params.export()`` returns (or raises).
        info: What ``get_info()`` returns (or raises).
        accounts: What ``users.list()`` returns (or raises).
    """

    def __init__(
        self,
        host: str,
        modules: Iterable[FakeModule] = (),
        *,
        advertised: Iterable[str] | None = None,
        params: Mapping[str, str] | Exception | None = None,
        info: BasicDeviceInfo | Exception = INFO,
        accounts: UserAccounts | Exception = ACCOUNTS,
        username: str = USERNAME,
    ) -> None:
        self.host = host
        self.resources: dict[str, Any] = {m.name: m for m in modules}
        self._advertised = None if advertised is None else set(advertised)
        self._info = info
        self.entered = 0
        self.exited = 0

        self.params = MagicMock()
        params_value = dict(PARAMS) if params is None else params
        self.params.export = AsyncMock(
            side_effect=params_value if isinstance(params_value, Exception) else None,
            return_value=None if isinstance(params_value, Exception) else params_value,
        )
        self.params.definitions = AsyncMock(return_value={})

        self.users = MagicMock()
        self.users.list = AsyncMock(
            side_effect=accounts if isinstance(accounts, Exception) else None,
            return_value=None if isinstance(accounts, Exception) else accounts,
        )
        self.users.read = self.users.list
        self.client = MagicMock()
        self.client.username = username
        self.client.password = CANARY
        self.client.host = host

    def __getattr__(self, name: str) -> FakeModule:
        """``device.<module>`` as the audit reads it; a module the fake lacks answers 404."""
        if name.startswith("_"):
            raise AttributeError(name)
        resources = self.__dict__.get("resources", {})
        if name in resources:
            return resources[name]
        return FakeModule(name, AxisApiNotSupportedError(f"404 Not Found: {name}"))

    async def __aenter__(self) -> FakeDevice:
        self.entered += 1
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.exited += 1

    async def get_info(self) -> BasicDeviceInfo:
        if isinstance(self._info, Exception):
            raise self._info
        return self._info

    async def available_resources(self) -> dict[str, Any]:
        if self._advertised is None:
            return dict(self.resources)
        return {
            name: module
            for name, module in self.resources.items()
            if module.api_id is None or name in self._advertised
        }


class FakeResolver:
    """A resolver over a fixed set of named fake devices.

    ``open(name)`` returns the same ``FakeDevice`` each time so tests can
    inspect it afterwards (``entered``/``exited`` prove the context manager
    was used).
    """

    def __init__(
        self,
        devices: Mapping[str, FakeDevice],
        *,
        groups: Mapping[str, list[str]] | None = None,
        types: Mapping[str, str] | None = None,
    ) -> None:
        self._devices = dict(devices)
        self._groups = (
            {name: list(groups.get(name, [])) for name in devices}
            if groups
            else {name: [] for name in devices}
        )
        self._types = dict(types or {})

    def names(self) -> list[str]:
        return list(self._devices)

    def describe(self, name: str) -> DeviceSummary:
        return DeviceSummary(
            name=name,
            device_type=self._types.get(name, "camera"),
            groups=self._groups[name],
            host=self._devices[name].host,
        )

    def connection(self, name: str) -> DeviceConnection:
        dev = self._devices[name]
        return DeviceConnection(
            host=dev.host,
            username=USERNAME,
            password=CANARY,
            port=443,
            device_type=self._types.get(name, "camera"),
        )

    def open(self, name: str) -> AxisDevice:
        return cast("AxisDevice", self._devices[name])

    def select(self, selection: str) -> list[str]:
        if selection == "all":
            return self.names()
        return [
            name
            for name in self._devices
            if selection in self._groups[name] or self._types.get(name, "camera") == selection
        ]

    def device(self, name: str) -> FakeDevice:
        """The fake behind ``name`` (test inspection)."""
        return self._devices[name]


def two_cameras(**overrides: Any) -> FakeResolver:
    """Standard fixture: ``back_of_house`` (full), ``front_of_house`` (ssh not advertised)."""
    back = FakeDevice(
        "192.168.10.21",
        [
            FakeModule("device_info", INFO),
            FakeModule("ssh", SSH, api_id="ssh"),
        ],
    )
    front = FakeDevice(
        "192.168.10.22",
        [
            FakeModule("device_info", INFO),
            FakeModule("ssh", SSH, api_id="ssh"),
        ],
        advertised=[],
    )
    devices: dict[str, FakeDevice] = {"back_of_house": back, "front_of_house": front}
    devices.update(overrides)
    return FakeResolver(
        devices, groups={"back_of_house": ["indoor"]}, types={"front_of_house": "camera"}
    )
