"""Tests for fleet fan-out (``--all`` / ``--group``)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from axis_cam.audit import AuditReport, Finding, Severity, Status
from axis_cam.cli import DeviceContext, app
from axis_cam.cli.context import select_targets
from axis_cam.cli.fleet import FleetResult, fleet_json, run_fleet
from axis_cam.config import AppConfig, DeviceConfig
from axis_cam.exceptions import AxisAuthenticationError, AxisConnectionError
from axis_cam.models import (
    BasicDeviceInfo,
    OnvifAccount,
    OnvifAccounts,
    OnvifUserLevel,
    UserAccount,
    UserAccounts,
    UserRole,
)

runner = CliRunner()


def _config() -> AppConfig:
    return AppConfig(
        devices={
            "cam1": DeviceConfig(
                host="10.0.0.1",
                username="root",
                password="pw",
                device_type="camera",
                groups=["front"],
            ),
            "cam2": DeviceConfig(
                host="10.0.0.2", username="root", password="pw", device_type="camera"
            ),
            "spk": DeviceConfig(
                host="10.0.0.3",
                username="root",
                password="pw",
                device_type="speaker",
                groups=["Front", "audio"],
            ),
        }
    )


@pytest.fixture
def config():
    with patch("axis_cam.cli.context.load_config", return_value=_config()):
        yield


class TestSelectTargets:
    def test_all_in_config_order(self, config):
        targets = select_targets(all_devices=True, group=None)
        assert [name for name, _ in targets] == ["cam1", "cam2", "spk"]
        assert targets[0][1].host == "10.0.0.1" and targets[0][1].https is True

    def test_group_by_type(self, config):
        assert [n for n, _ in select_targets(all_devices=False, group="camera")] == ["cam1", "cam2"]

    def test_group_by_tag_case_insensitive(self, config):
        assert [n for n, _ in select_targets(all_devices=False, group="front")] == ["cam1", "spk"]
        assert [n for n, _ in select_targets(all_devices=False, group="AUDIO")] == ["spk"]

    def test_overrides_apply_to_every_target(self, config):
        targets = select_targets(all_devices=True, group=None, username="ops", port=8443)
        assert all(ctx.username == "ops" and ctx.port == 8443 for _, ctx in targets)

    def test_unknown_group_exits_with_the_known_names(self, config, capsys):
        import typer

        with pytest.raises(typer.Exit):
            select_targets(all_devices=False, group="garden")
        out = capsys.readouterr().out
        assert "camera" in out and "speaker" in out and "front" in out

    def test_no_devices_configured(self):
        import typer

        with (
            patch("axis_cam.cli.context.load_config", return_value=AppConfig()),
            pytest.raises(typer.Exit),
        ):
            select_targets(all_devices=True, group=None)


class FakeDevice:
    def __init__(self, host: str, value=None, error: Exception | None = None):
        self.client = MagicMock()
        self.client.host = host
        self.value = value
        self.error = error

    async def __aenter__(self):
        if isinstance(self.error, AxisConnectionError):
            raise self.error
        return self

    async def __aexit__(self, *exc):
        return None


def _targets(*hosts: str):
    return [
        (f"d{i}", DeviceContext(host=h, username="u", password="p", port=443, device_type="camera"))
        for i, h in enumerate(hosts, 1)
    ]


class TestRunFleet:
    async def test_results_in_target_order_with_per_device_errors(self):
        devices = {
            "10.0.0.1": FakeDevice("10.0.0.1", value="one"),
            "10.0.0.2": FakeDevice("10.0.0.2", error=AxisConnectionError("unreachable")),
            "10.0.0.3": FakeDevice("10.0.0.3", value="three"),
        }

        async def op(dev):
            if dev.client.host == "10.0.0.3":
                await asyncio.sleep(0.01)  # finishes last; order must still be config order
            return dev.value

        with patch.object(DeviceContext, "open", lambda self: devices[self.host]):
            results = await run_fleet(
                _targets("10.0.0.1", "10.0.0.2", "10.0.0.3"), op, concurrency=3
            )

        assert [(r.name, r.ok, r.value, r.error) for r in results] == [
            ("d1", True, "one", None),
            ("d2", False, None, "unreachable"),
            ("d3", True, "three", None),
        ]

    async def test_auth_error_inside_the_operation_is_that_devices_error(self):
        dev = FakeDevice("10.0.0.1")

        async def op(_dev):
            raise AxisAuthenticationError("401")

        with patch.object(DeviceContext, "open", lambda self: dev):
            [result] = await run_fleet(_targets("10.0.0.1"), op)
        assert not result.ok and result.error == "401"

    async def test_a_bug_in_the_operation_propagates(self):
        dev = FakeDevice("10.0.0.1")

        async def op(_dev):
            raise KeyError("bug")

        with patch.object(DeviceContext, "open", lambda self: dev), pytest.raises(KeyError):
            await run_fleet(_targets("10.0.0.1"), op)

    async def test_concurrency_is_bounded(self):
        running = 0
        peak = 0

        async def op(_dev):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1
            return True

        with patch.object(DeviceContext, "open", lambda self: FakeDevice(self.host)):
            results = await run_fleet(
                _targets(*(f"10.0.0.{i}" for i in range(1, 7))), op, concurrency=2
            )
        assert all(r.ok for r in results) and peak == 2


class TestFleetJson:
    def test_shape(self):
        results = [
            FleetResult(name="a", host="h1", value={"x": 1}),
            FleetResult(name="b", host="h2", error="boom"),
        ]
        data = fleet_json(results, lambda v: v)
        assert data == {
            "devices": {
                "a": {"host": "h1", "ok": True, "result": {"x": 1}},
                "b": {"host": "h2", "ok": False, "error": "boom"},
            },
            "failed": ["b"],
        }


def _report(name: str, *, failing: int) -> AuditReport:
    report = AuditReport(host="h", device_name=name, generated_at="t", product="P", firmware="1")
    for i in range(failing):
        report.findings.append(Finding(f"check.{i}", f"Check {i}", Status.FAIL, Severity.HIGH))
    report.findings.append(Finding("check.ok", "Fine", Status.PASS, Severity.LOW))
    return report


def _text(result) -> str:
    return " ".join(result.output.replace("│", " ").split())


class TestCliFleet:
    def _patch_devices(self, by_host):
        return patch.object(DeviceContext, "open", lambda self: by_host[self.host])

    def test_audit_all_matrix_and_exit_code(self, config):
        reports = {
            "10.0.0.1": _report("cam1", failing=2),
            "10.0.0.2": _report("cam2", failing=0),
            "10.0.0.3": _report("spk", failing=1),
        }
        with (
            self._patch_devices({h: FakeDevice(h) for h in reports}),
            patch(
                "axis_cam.cli.security.run_audit",
                side_effect=lambda dev, device_name="": reports[dev.client.host],
            ),
        ):
            result = runner.invoke(app, ["security", "audit", "--all"])

        assert result.exit_code == 1, result.output
        text = _text(result)
        assert "fleet summary" in text and "cam1" in text and "spk" in text
        assert "check.0" in text and "check.ok" not in text  # only failing/unknown rows

    def test_audit_group_no_fail_json(self, config):
        reports = {"10.0.0.1": _report("cam1", failing=1), "10.0.0.2": _report("cam2", failing=0)}
        with (
            self._patch_devices({h: FakeDevice(h) for h in reports}),
            patch(
                "axis_cam.cli.security.run_audit",
                side_effect=lambda dev, device_name="": reports[dev.client.host],
            ),
        ):
            result = runner.invoke(
                app, ["security", "audit", "--group", "camera", "--json", "--no-fail"]
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert set(data["devices"]) == {"cam1", "cam2"} and data["failed"] == []
        assert data["devices"]["cam1"]["result"]["counts"]["fail"] == 1

    def test_audit_device_error_is_a_row_and_exit_1(self, config):
        reports = {"10.0.0.1": _report("cam1", failing=0), "10.0.0.2": _report("cam2", failing=0)}
        devices = {
            "10.0.0.1": FakeDevice("10.0.0.1"),
            "10.0.0.2": FakeDevice(
                "10.0.0.2", error=AxisConnectionError("All connection attempts failed")
            ),
        }
        with (
            self._patch_devices(devices),
            patch(
                "axis_cam.cli.security.run_audit",
                side_effect=lambda dev, device_name="": reports[dev.client.host],
            ),
        ):
            result = runner.invoke(app, ["security", "audit", "--group", "camera", "--no-fail"])

        assert result.exit_code == 1
        text = _text(result)
        assert (
            "1 device(s) failed" in text
            and "cam2" in text
            and "All connection attempts failed" in text
        )

    def test_info_all_inventory(self, config):
        infos = {
            h: BasicDeviceInfo(
                product_full_name=f"AXIS {i}",
                serial_number=f"S{i}",
                firmware_version="12.11.118",
                soc="Artpec-8",
            )
            for i, h in enumerate(("10.0.0.1", "10.0.0.2", "10.0.0.3"), 1)
        }
        devices = {}
        for h, info in infos.items():
            dev = FakeDevice(h)
            dev.get_info = AsyncMock(return_value=info)  # type: ignore[attr-defined]
            devices[h] = dev
        with self._patch_devices(devices):
            result = runner.invoke(app, ["info", "--all", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["devices"]["spk"]["result"]["serial_number"] == "S3" and data["failed"] == []

    def test_accounts_and_onvif_list_fleet_tables(self, config):
        devices = {}
        for h in ("10.0.0.1", "10.0.0.2"):
            dev = FakeDevice(h)
            dev.users = MagicMock(
                list=AsyncMock(
                    return_value=UserAccounts(
                        accounts=[
                            UserAccount(username="root", role=UserRole.ADMIN),
                            UserAccount(username="vms", role=UserRole.VIEWER),
                        ]
                    )
                )
            )
            dev.onvif_users = MagicMock(
                list=AsyncMock(
                    return_value=OnvifAccounts(
                        accounts=[OnvifAccount(username="onvif", level=OnvifUserLevel.OPERATOR)]
                    )
                )
            )
            devices[h] = dev
        with self._patch_devices(devices):
            accounts = runner.invoke(app, ["accounts", "list", "--group", "camera"])
            onvif = runner.invoke(app, ["onvif", "list", "--group", "camera"])

        assert accounts.exit_code == 0, accounts.output
        assert "Fleet accounts" in _text(accounts) and "vms" in _text(accounts)
        assert onvif.exit_code == 0, onvif.output
        assert "Fleet ONVIF users" in _text(onvif) and "onvif" in _text(onvif)

    def test_backup_all_writes_one_directory_per_device(self, config, tmp_path):
        from axis_cam.backup import BackupManifest

        def fake_create(dev, output, *, name, include_server_report):
            d = output / f"backup-{name}-x"
            d.mkdir()
            manifest = BackupManifest(
                format_version=1,
                created_at="t",
                tool={},
                device={"host": dev.client.host},
                files=[],
            )
            return d, manifest

        devices = {h: FakeDevice(h) for h in ("10.0.0.1", "10.0.0.2", "10.0.0.3")}
        with (
            self._patch_devices(devices),
            patch("axis_cam.cli.backup.create_backup", side_effect=fake_create),
        ):
            result = runner.invoke(app, ["backup", "create", "--all", "-o", str(tmp_path)])

        assert result.exit_code == 0, result.output
        assert sorted(p.name for p in tmp_path.iterdir()) == [
            "backup-cam1-x",
            "backup-cam2-x",
            "backup-spk-x",
        ]
        assert "Fleet backup" in _text(result)

    def test_single_device_paths_are_unchanged(self, config):
        dev = FakeDevice("10.0.0.1")
        dev.users = MagicMock(list=AsyncMock(return_value=UserAccounts(accounts=[])))
        with self._patch_devices({"10.0.0.1": dev}):
            result = runner.invoke(app, ["accounts", "list", "--device", "cam1"])
        assert result.exit_code == 0 and "Fleet" not in result.output
