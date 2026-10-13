"""Tests for the registry-driven device report."""

from datetime import UTC
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from axis_cam.api import registry
from axis_cam.api.base import BaseAPI
from axis_cam.api.registry import register
from axis_cam.devices.base import AxisDevice
from axis_cam.devices.camera import AxisCamera
from axis_cam.exceptions import (
    AxisApiNotSupportedError,
    AxisAuthenticationError,
    AxisConnectionError,
    AxisDeviceError,
)
from axis_cam.models import FirewallConfig, NtpConfig, SshConfig
from axis_cam.report import SUMMARY_SECTIONS, DeviceReport, collect_report, render_text


class FakeModule:
    """A ResourceModule stand-in that returns or raises on read()."""

    def __init__(self, name: str, result: BaseModel | Exception, api_id: str | None = None):
        self.name = name
        self.api_id = api_id
        self._result = result

    async def read(self) -> BaseModel:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeDevice:
    """Just enough of AxisDevice for collect_report."""

    host = "cam.example"

    def __init__(self, modules: list[FakeModule], advertised: set[str] | None = None):
        self.resources = {m.name: m for m in modules}
        self._advertised = advertised

    async def available_resources(self):
        if self._advertised is None:
            return dict(self.resources)
        return {
            n: m
            for n, m in self.resources.items()
            if m.api_id is None or m.api_id in self._advertised
        }


def _device(*modules: FakeModule, advertised: set[str] | None = None) -> AxisDevice:
    return cast("AxisDevice", FakeDevice(list(modules), advertised))


class TestCollectReport:
    async def test_summary_reads_only_summary_sections_in_order(self):
        device = _device(
            FakeModule("ssh", SshConfig(enabled=True)),
            FakeModule("ntp", NtpConfig()),
            FakeModule("firewall", FirewallConfig()),
        )

        report = await collect_report(device)

        assert list(report.sections) == ["firewall", "ntp"]  # SUMMARY_SECTIONS order
        assert "ssh" not in report.sections
        assert report.errors == {} and report.skipped == []

    async def test_full_reads_every_available_resource(self):
        device = _device(
            FakeModule("ssh", SshConfig(enabled=True, port=2222)),
            FakeModule("ntp", NtpConfig()),
        )

        report = await collect_report(device, full=True)

        assert set(report.sections) == {"ssh", "ntp"}
        assert report.sections["ssh"]["port"] == 2222

    async def test_sections_hold_json_mode_dumps(self):
        device = _device(FakeModule("ssh", SshConfig(enabled=True)))

        report = await collect_report(device, full=True)

        # model_dump(mode="json"): plain types only, round-trips through json.
        import json

        json.dumps(report.to_dict())
        assert report.sections["ssh"]["enabled"] is True

    async def test_device_errors_are_recorded_per_module_and_do_not_stop_the_report(self):
        device = _device(
            FakeModule("ssh", AxisDeviceError("500 from device")),
            FakeModule("ntp", AxisApiNotSupportedError("no such API")),
            FakeModule("firewall", FirewallConfig(enabled=True)),
        )

        report = await collect_report(device, full=True)

        assert report.sections["firewall"]["enabled"] is True
        assert report.errors == {"ssh": "500 from device", "ntp": "no such API"}

    @pytest.mark.parametrize("exc", [AxisAuthenticationError("401"), AxisConnectionError("down")])
    async def test_auth_and_connection_errors_propagate(self, exc):
        device = _device(FakeModule("ssh", exc), FakeModule("ntp", NtpConfig()))

        with pytest.raises(type(exc)):
            await collect_report(device, full=True)

    async def test_unadvertised_modules_are_skipped_not_errors(self):
        device = _device(
            FakeModule("ssh", SshConfig(), api_id="ssh"),
            FakeModule("ntp", NtpConfig(), api_id="network-time-sync"),
            FakeModule("device_info", SshConfig(), api_id=None),
            advertised={"ssh"},
        )

        report = await collect_report(device, full=True)

        assert set(report.sections) == {"ssh", "device_info"}
        assert report.skipped == ["ntp"]
        assert report.errors == {}

    async def test_skipped_is_relative_to_what_was_requested(self):
        # Not in the summary set, not advertised: not worth mentioning in a summary report.
        device = _device(FakeModule("oidc", SshConfig(), api_id="oidcsetup"), advertised=set())

        report = await collect_report(device)

        assert report.skipped == []

    async def test_name_defaults_to_host_and_timestamp_is_aware_utc(self):
        device = _device()

        report = await collect_report(device)

        assert report.device == "cam.example"
        assert report.generated_at.tzinfo is UTC
        named = await collect_report(device, name="front-door")
        assert named.device == "front-door"

    def test_summary_sections_are_registered_resources(self):
        names = set(registry.registered_modules())
        assert set(SUMMARY_SECTIONS) <= names


class TestReportDoesNotKnowTheModules:
    """The definition-of-done for Phase 1.3: a new registered module shows up in
    a --full report without any change to report.py."""

    async def test_new_registered_module_appears_in_full_report(self, monkeypatch):
        monkeypatch.setattr(registry, "_MODULES", dict(registry._MODULES))

        class WidgetConfig(BaseModel):
            widgets: int = 3

        @register
        class WidgetAPI(BaseAPI):
            name = "widgets"
            api_id = None

            async def read(self) -> WidgetConfig:
                return WidgetConfig()

        with patch("axis_cam.devices.base.VapixClient") as mock:
            client = MagicMock()
            client.host = "192.168.1.10"
            client.discover_apis = AsyncMock(return_value={})
            mock.return_value = client
            device = AxisCamera("192.168.1.10", "admin", "pass")

        # The real modules would need a device; give each a canned answer.
        for name, module in device.resources.items():
            if name != "widgets":
                module.read = AsyncMock(return_value=SshConfig())  # type: ignore[method-assign]

        report = await collect_report(device, full=True)

        assert report.sections["widgets"] == {"widgets": 3}
        assert set(report.sections) == set(device.resources)
        assert report.errors == {}


class TestRenderText:
    def _report(self, **sections) -> DeviceReport:
        from datetime import datetime

        return DeviceReport(device="cam", generated_at=datetime.now(UTC), sections=sections)

    def test_renders_identity_network_and_neighbour(self):
        report = self._report(
            device_info={
                "product_number": "M3216",
                "serial_number": "ACC",
                "firmware_version": "12.1",
            },
            network={"interfaces": [{"ip_address": "10.0.0.5", "mac_address": "AA:BB"}]},
            lldp={"neighbors": [{"sys_name": "sw-core-1"}]},
        )

        text = render_text(report)

        assert text.splitlines()[0] == "Device Report: cam"
        for line in ("Model: M3216", "Serial: ACC", "Firmware: 12.1", "IP: 10.0.0.5", "MAC: AA:BB"):
            assert line in text
        assert "Connected to: sw-core-1" in text

    def test_missing_sections_and_fields_leave_lines_out(self):
        report = self._report(device_info={"product_number": "M3216"}, network={"interfaces": []})

        text = render_text(report)

        assert "Model: M3216" in text
        assert "Serial" not in text and "IP:" not in text and "Connected to" not in text

    def test_errors_and_skipped_are_listed(self):
        report = self._report()
        report.errors["ssh"] = "boom"
        report.skipped.append("ntp")

        text = render_text(report)

        assert "Errors (1):" in text and "  ssh: boom" in text
        assert "Not advertised by device: ntp" in text

    def test_to_dict_nests_sections_so_module_names_cannot_collide(self):
        report = self._report(device={"would": "collide"}, errors={"too": True})

        data = report.to_dict()

        assert data["device"] == "cam"
        assert data["sections"] == {"device": {"would": "collide"}, "errors": {"too": True}}
        assert data["errors"] == {} and data["skipped"] == []
