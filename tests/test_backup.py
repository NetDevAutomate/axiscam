"""Tests for the backup service."""

import json
import stat
import sys
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from axis_cam import __version__
from axis_cam.api import registry
from axis_cam.api.base import BaseAPI
from axis_cam.api.registry import register
from axis_cam.backup import (
    MANIFEST_FILE,
    MANIFEST_VERSION,
    NOT_IMPLEMENTED,
    NOT_INCLUDED_BY_DESIGN,
    BackupManifest,
    backup_dir_name,
    create_backup,
    load_manifest,
    verify_backup,
)
from axis_cam.devices.base import AxisDevice
from axis_cam.devices.camera import AxisCamera
from axis_cam.exceptions import AxisAuthenticationError, AxisDeviceError
from axis_cam.models import BasicDeviceInfo, NtpConfig, ServerReport, ServerReportFormat, SshConfig

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")


class FakeModule:
    def __init__(self, name, result, api_id=None):
        self.name, self.api_id, self._result = name, api_id, result

    async def read(self) -> BaseModel:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeDevice:
    host = "10.0.0.5"

    def __init__(self, modules, *, params=None, server_report=None):
        self.resources = {m.name: m for m in modules}
        self.params = MagicMock()
        self.params.export = AsyncMock(
            side_effect=params if isinstance(params, Exception) else None,
            return_value=params if not isinstance(params, Exception) else None,
        )
        self.serverreport = MagicMock()
        self.serverreport.download_report = AsyncMock(return_value=server_report)

    async def available_resources(self):
        return dict(self.resources)


def _device(*modules, **kwargs) -> AxisDevice:
    return cast("AxisDevice", FakeDevice(list(modules), **kwargs))


INFO = BasicDeviceInfo(
    product_number="M3216-LVE", serial_number="ACCC8E000001", firmware_version="12.1.60"
)
PARAMS = {"root.Network.Media": "auto", "root.Properties.FriendlyName": "Front Door"}


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class TestCreateBackup:
    async def test_layout_manifest_and_hashes(self, tmp_path):
        device = _device(
            FakeModule("device_info", INFO),
            FakeModule("ssh", SshConfig(enabled=True, port=2222), api_id="ssh"),
            params=PARAMS,
        )

        backup_dir, manifest = await create_backup(device, tmp_path, name="front-door")

        assert backup_dir.parent == tmp_path and backup_dir.name.startswith("backup-front-door-")
        assert sorted(p.name for p in backup_dir.iterdir()) == [
            "device_info.json",
            MANIFEST_FILE,
            "params.json",
            "ssh.json",
        ]
        assert json.loads((backup_dir / "ssh.json").read_text())["port"] == 2222
        assert json.loads((backup_dir / "params.json").read_text()) == PARAMS

        assert manifest.format_version == MANIFEST_VERSION
        assert manifest.tool == {"name": "axiscam", "version": __version__}
        assert manifest.device == {
            "host": "10.0.0.5",
            "name": "front-door",
            "product_number": "M3216-LVE",
            "serial_number": "ACCC8E000001",
            "firmware_version": "12.1.60",
        }
        assert [(f.section, f.file, f.source) for f in manifest.files] == [
            ("device_info", "device_info.json", "cgi"),
            ("ssh", "ssh.json", "ssh"),
            ("params", "params.json", "param.cgi"),
        ]
        for entry in manifest.files:
            assert (
                len(entry.sha256) == 64 and entry.size == (backup_dir / entry.file).stat().st_size
            )
        assert manifest.errors == {} and manifest.skipped == []
        assert verify_backup(backup_dir) == []

    async def test_manifest_file_round_trips(self, tmp_path):
        device = _device(FakeModule("ssh", SshConfig(), api_id="ssh"), params=PARAMS)

        backup_dir, manifest = await create_backup(device, tmp_path)

        on_disk = json.loads((backup_dir / MANIFEST_FILE).read_text())
        assert on_disk == manifest.to_dict()
        assert load_manifest(backup_dir) == manifest

    async def test_manifest_is_honest_about_what_is_missing(self, tmp_path):
        device = _device(FakeModule("ssh", SshConfig(), api_id="ssh"), params=PARAMS)

        _, manifest = await create_backup(device, tmp_path)

        assert manifest.not_included["by_design"] == list(NOT_INCLUDED_BY_DESIGN)
        assert manifest.not_included["not_implemented"] == list(NOT_IMPLEMENTED)
        assert any("passwords" in line for line in manifest.not_included["by_design"])
        assert any("private keys" in line for line in manifest.not_included["by_design"])
        assert any("ACAP" in line for line in manifest.not_included["by_design"])
        assert any("recordings" in line for line in manifest.not_included["by_design"])
        assert any("ONVIF" in line for line in manifest.not_included["not_implemented"])
        assert "not implemented" in manifest.restore

    async def test_module_errors_and_skips_are_recorded_not_fatal(self, tmp_path):
        class Unadvertised(FakeDevice):
            async def available_resources(self):
                return {k: v for k, v in self.resources.items() if k != "ntp"}

        device = cast(
            "AxisDevice",
            Unadvertised(
                [
                    FakeModule("ssh", AxisDeviceError("500"), api_id="ssh"),
                    FakeModule("ntp", NtpConfig(), api_id="network-time-sync"),
                    FakeModule("device_info", INFO),
                ],
                params=PARAMS,
            ),
        )

        backup_dir, manifest = await create_backup(device, tmp_path)

        assert manifest.errors == {"ssh": "500"}
        assert manifest.skipped == ["ntp"]
        assert {f.section for f in manifest.files} == {"device_info", "params"}
        assert not (backup_dir / "ssh.json").exists()

    async def test_params_failure_is_recorded(self, tmp_path):
        device = _device(
            FakeModule("ssh", SshConfig(), api_id="ssh"), params=AxisDeviceError("403?")
        )

        backup_dir, manifest = await create_backup(device, tmp_path)

        assert manifest.errors == {"params": "403?"}
        assert not (backup_dir / "params.json").exists()

    async def test_auth_error_propagates_and_creates_no_directory(self, tmp_path):
        device = _device(FakeModule("ssh", AxisAuthenticationError("401"), api_id="ssh"))

        with pytest.raises(AxisAuthenticationError):
            await create_backup(device, tmp_path)
        assert list(tmp_path.iterdir()) == []

    async def test_server_report_is_optional_and_recorded(self, tmp_path):
        ok = ServerReport(content=b"PK-zip", format=ServerReportFormat.ZIP_WITH_IMAGE, size_bytes=6)
        device = _device(
            FakeModule("ssh", SshConfig(), api_id="ssh"), params=PARAMS, server_report=ok
        )

        backup_dir, manifest = await create_backup(device, tmp_path, include_server_report=True)

        entry = manifest.get("server_report")
        assert (
            entry is not None
            and entry.file == "server-report.zip"
            and entry.source == "serverreport.cgi"
        )
        assert (backup_dir / "server-report.zip").read_bytes() == b"PK-zip"
        device.serverreport.download_report.assert_awaited_once_with(
            format=ServerReportFormat.ZIP_WITH_IMAGE
        )

    async def test_server_report_not_requested_by_default(self, tmp_path):
        device = _device(FakeModule("ssh", SshConfig(), api_id="ssh"), params=PARAMS)

        _, manifest = await create_backup(device, tmp_path)

        device.serverreport.download_report.assert_not_awaited()
        assert manifest.get("server_report") is None

    async def test_failed_server_report_is_an_error_entry(self, tmp_path):
        failed = ServerReport(content=b"", size_bytes=0, error="Device error 500")
        device = _device(
            FakeModule("ssh", SshConfig(), api_id="ssh"), params=PARAMS, server_report=failed
        )

        backup_dir, manifest = await create_backup(device, tmp_path, include_server_report=True)

        assert manifest.errors == {"server_report": "Device error 500"}
        assert not (backup_dir / "server-report.zip").exists()

    @posix_only
    async def test_directory_is_0700_and_files_0600(self, tmp_path):
        device = _device(FakeModule("ssh", SshConfig(), api_id="ssh"), params=PARAMS)

        backup_dir, _ = await create_backup(device, tmp_path)

        assert _mode(backup_dir) == 0o700
        for path in backup_dir.iterdir():
            assert _mode(path) == 0o600, path

    async def test_new_registered_module_appears_without_backup_code_changes(
        self, tmp_path, monkeypatch
    ):
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
        for name, module in device.resources.items():
            if name != "widgets":
                module.read = AsyncMock(return_value=SshConfig())  # type: ignore[method-assign]
        device.params.export = AsyncMock(return_value=PARAMS)  # type: ignore[method-assign]

        backup_dir, manifest = await create_backup(device, tmp_path)

        assert json.loads((backup_dir / "widgets.json").read_text()) == {"widgets": 3}
        assert manifest.get("widgets") is not None
        assert {f.section for f in manifest.files} == set(device.resources) | {"params"}


class TestVerifyBackup:
    async def _backup(self, tmp_path) -> Path:
        device = _device(FakeModule("ssh", SshConfig(), api_id="ssh"), params=PARAMS)
        backup_dir, _ = await create_backup(device, tmp_path)
        return backup_dir

    async def test_intact(self, tmp_path):
        assert verify_backup(await self._backup(tmp_path)) == []

    async def test_tampered_file(self, tmp_path):
        backup_dir = await self._backup(tmp_path)
        path = backup_dir / "ssh.json"
        path.write_text(path.read_text().replace("false", "true "))  # same size

        problems = verify_backup(backup_dir)

        assert problems == ["ssh.json: sha256 mismatch"]

    async def test_missing_and_extra_files(self, tmp_path):
        backup_dir = await self._backup(tmp_path)
        (backup_dir / "params.json").unlink()
        (backup_dir / "notes.txt").write_text("hello")

        problems = verify_backup(backup_dir)

        assert "params.json: missing" in problems
        assert "notes.txt: not listed in the manifest" in problems

    def test_missing_manifest(self, tmp_path):
        assert verify_backup(tmp_path) == [f"{MANIFEST_FILE} is missing"]

    def test_unsupported_manifest_version(self, tmp_path):
        (tmp_path / MANIFEST_FILE).write_text(json.dumps({"format_version": 99}))
        assert verify_backup(tmp_path) == [
            f"{MANIFEST_FILE} is unreadable: unsupported manifest format_version 99"
        ]


class TestNaming:
    def test_backup_dir_name_is_path_safe_and_utc(self):
        from datetime import UTC, datetime, timedelta, timezone

        when = datetime(2026, 10, 13, 11, 5, 9, tzinfo=timezone(timedelta(hours=1)))
        assert (
            backup_dir_name("front door/cam:1", when) == "backup-front_door_cam_1-20261013T100509Z"
        )
        assert backup_dir_name("///", datetime(2026, 1, 1, tzinfo=UTC)).startswith("backup-device-")

    def test_manifest_from_dict_rejects_other_versions(self):
        with pytest.raises(ValueError, match="format_version"):
            BackupManifest.from_dict({"format_version": 2, "created_at": "x"})
