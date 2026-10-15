"""The two console-free extractions the MCP server builds on.

``axis_cam.connection.DeviceConnection`` is where a device class is
instantiated from resolved settings; it must never print the password in its
``repr`` (a traceback or log of the object would otherwise leak it).
``axis_cam.fleet.run_fleet`` runs one operation across devices without a Rich
console, reporting progress through a callback — on stdio, a console write is
a corrupted JSON-RPC frame.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING, Any, cast

import pytest
from pydantic import SecretStr

from axis_cam.auth import AuthMode
from axis_cam.config import DeviceConfig
from axis_cam.connection import DeviceConnection, get_device_class
from axis_cam.devices import AxisCamera, AxisIntercom, AxisRecorder, AxisSpeaker
from axis_cam.exceptions import AxisAuthenticationError, AxisConnectionError
from axis_cam.fleet import FleetResult, fleet_json, run_fleet

if TYPE_CHECKING:
    from axis_cam.devices.base import AxisDevice

CANARY = "Canary-Sup3r-S3cret!"


def _connection(**overrides: Any) -> DeviceConnection:
    values: dict[str, Any] = {
        "host": "10.0.0.5",
        "username": "admin",
        "password": CANARY,
        "port": 443,
        "device_type": "camera",
    }
    values.update(overrides)
    return DeviceConnection(**values)


class TestDeviceConnection:
    def test_repr_and_str_never_contain_the_password(self) -> None:
        conn = _connection()
        assert CANARY not in repr(conn)
        assert CANARY not in str(conn)
        assert "10.0.0.5" in repr(conn)  # still useful for a log line
        assert conn.password == CANARY  # but the value is there for the client

    def test_is_frozen(self) -> None:
        conn = _connection()
        with pytest.raises(FrozenInstanceError):
            conn.port = 80  # type: ignore[misc]

    def test_secure_defaults(self) -> None:
        conn = _connection()
        assert conn.https is True
        assert conn.ssl_verify is False
        assert conn.auth_mode is AuthMode.AUTO
        assert conn.timeout == 30.0

    @pytest.mark.parametrize(
        ("device_type", "cls"),
        [
            ("camera", AxisCamera),
            ("recorder", AxisRecorder),
            ("intercom", AxisIntercom),
            ("speaker", AxisSpeaker),
            ("Camera", AxisCamera),
            ("doorbell", AxisCamera),  # unknown types fall back to a camera
        ],
    )
    def test_get_device_class(self, device_type: str, cls: type) -> None:
        assert get_device_class(device_type) is cls

    def test_open_passes_every_transport_setting(self) -> None:
        conn = _connection(
            device_type="speaker",
            port=8443,
            https=True,
            ssl_verify=True,
            timeout=7.5,
            auth_mode=AuthMode.BASIC,
        )
        device = conn.open()
        assert isinstance(device, AxisSpeaker)
        client = device.client
        assert client.host == "10.0.0.5"
        assert client.port == 8443
        assert client.username == "admin"
        assert client.use_https is True
        assert client.verify_ssl is True
        assert client.timeout == 7.5
        assert client.auth_mode is AuthMode.BASIC

    def test_from_config_takes_the_entry_and_applies_overrides(self) -> None:
        config = DeviceConfig(
            address="10.0.0.9",
            username="root",
            password=SecretStr(CANARY),
            port=443,
            type="intercom",
            https=True,
            ssl_verify=False,
        )
        conn = DeviceConnection.from_config(config, timeout=12.0)
        assert conn == _connection(
            host="10.0.0.9",
            username="root",
            port=443,
            device_type="intercom",
            timeout=12.0,
        )
        overridden = DeviceConnection.from_config(
            config,
            timeout=12.0,
            username="ops",
            password="other",  # pragma: allowlist secret
            port=8443,
        )
        assert (overridden.username, overridden.password, overridden.port) == (
            "ops",
            "other",
            8443,
        )
        assert CANARY not in repr(overridden) and "other" not in repr(overridden)


# --- fleet -----------------------------------------------------------------------


class _FakeDevice:
    """Enough of AxisDevice for run_fleet: an async context manager with a host."""

    def __init__(self, host: str, *, fail: Exception | None = None, delay: float = 0.0) -> None:
        self.host = host
        self._fail = fail
        self._delay = delay

    async def __aenter__(self) -> _FakeDevice:
        if self._fail is not None:
            raise self._fail
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_info(self) -> dict[str, str]:
        if self._delay:
            await asyncio.sleep(self._delay)
        return {"host": self.host}


class _Target(DeviceConnection):
    """A DeviceConnection whose open() returns a fake instead of a real device."""

    def open(self) -> AxisDevice:  # type: ignore[override]
        fake = _FakeDevice(
            self.host, fail=_FAILURES.get(self.host), delay=_DELAYS.get(self.host, 0)
        )
        return cast("AxisDevice", fake)


_FAILURES: dict[str, Exception] = {}
_DELAYS: dict[str, float] = {}


def _targets(*hosts: str) -> list[tuple[str, DeviceConnection]]:
    return [
        (f"dev{i}", _Target(host=h, username="u", password="p", port=443, device_type="camera"))
        for i, h in enumerate(hosts)
    ]


async def _info(dev: AxisDevice) -> dict[str, str]:
    return await dev.get_info()  # type: ignore[return-value]


class TestRunFleet:
    def setup_method(self) -> None:
        _FAILURES.clear()
        _DELAYS.clear()

    async def test_results_in_target_order_with_errors_as_rows(self) -> None:
        _FAILURES["10.0.0.2"] = AxisAuthenticationError("Authentication failed")
        _FAILURES["10.0.0.3"] = AxisConnectionError("Connection refused")
        results = await run_fleet(_targets("10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"), _info)

        assert [r.name for r in results] == ["dev0", "dev1", "dev2", "dev3"]
        assert results[0] == FleetResult(name="dev0", host="10.0.0.1", value={"host": "10.0.0.1"})
        assert results[1].ok is False and "Authentication failed" in (results[1].error or "")
        assert results[2].ok is False and "Connection refused" in (results[2].error or "")
        assert results[3].ok is True

    async def test_a_bug_in_the_operation_propagates(self) -> None:
        async def broken(dev: AxisDevice) -> None:
            raise KeyError("bug")

        with pytest.raises(KeyError):
            await run_fleet(_targets("10.0.0.1"), broken)

    async def test_progress_callback_counts_to_total_and_no_stdout(self, capsys) -> None:
        seen: list[tuple[int, int]] = []
        results = await run_fleet(
            _targets("10.0.0.1", "10.0.0.2", "10.0.0.3"),
            _info,
            on_progress=lambda done, total: seen.append((done, total)),
        )
        assert len(results) == 3
        assert seen == [(1, 3), (2, 3), (3, 3)]
        assert capsys.readouterr().out == ""

    async def test_concurrency_is_bounded(self) -> None:
        active = 0
        peak = 0

        async def op(dev: AxisDevice) -> None:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

        await run_fleet(_targets(*(f"10.0.0.{i}" for i in range(1, 9))), op, concurrency=2)
        assert peak == 2

    async def test_per_device_timeout_becomes_that_devices_error(self) -> None:
        _DELAYS["10.0.0.2"] = 0.5
        results = await run_fleet(_targets("10.0.0.1", "10.0.0.2"), _info, timeout=0.05)
        assert results[0].ok is True
        assert results[1].ok is False
        assert "timed out" in (results[1].error or "")

    def test_fleet_json_shape(self) -> None:
        results = [
            FleetResult(name="a", host="h1", value={"x": 1}),
            FleetResult(name="b", host="h2", error="boom"),
        ]
        assert fleet_json(results, lambda v: v) == {
            "devices": {
                "a": {"host": "h1", "ok": True, "result": {"x": 1}},
                "b": {"host": "h2", "ok": False, "error": "boom"},
            },
            "failed": ["b"],
        }


def test_library_modules_do_not_import_the_cli() -> None:
    """Importing the extractions must not pull in the CLI package or Typer.

    ``axis_cam.cli.app`` instantiates the Rich console and the Typer app at
    import time; a library module that imports it is one step from writing to
    stdout. (``rich`` itself is imported by httpx for its own ``httpx`` command,
    which is why the check is on our package and Typer, not on ``rich``.)
    """
    import subprocess

    code = (
        "import sys, axis_cam.connection, axis_cam.fleet; "
        "print(sorted(m for m in sys.modules "
        "if m == 'axis_cam.cli' or m.startswith('axis_cam.cli.') or m == 'typer'))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
