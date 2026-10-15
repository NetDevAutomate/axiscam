"""Tests for ``axiscam backup``."""

import json
from pathlib import Path
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from axis_cam.backup import MANIFEST_FILE, BackupFile, BackupManifest
from axis_cam.cli import DeviceContext, app
from axis_cam.config import AppConfig
from axis_cam.exceptions import AxisAuthenticationError

runner = CliRunner()
HOST_ARGS = ["--host", "10.0.0.5", "-u", "admin", "-p", "secret"]


class FakeDevice:
    host = "10.0.0.5"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None


@pytest.fixture
def no_config():
    with patch("axis_cam.cli.context.load_config", return_value=AppConfig()):
        yield


def _manifest(**overrides) -> BackupManifest:
    manifest = BackupManifest(
        format_version=1,
        created_at="2026-10-13T11:00:00+00:00",
        tool={"name": "axiscam", "version": "0.1.0"},
        device={"host": "10.0.0.5", "name": "front", "product_number": "M3216-LVE"},
        files=[
            BackupFile("device_info", "device_info.json", "a" * 64, 120, "cgi"),
            BackupFile("ssh", "ssh.json", "b" * 64, 2048, "ssh"),
        ],
    )
    for key, value in overrides.items():
        setattr(manifest, key, value)
    return manifest


def _text(result) -> str:
    return " ".join(result.output.replace("│", " ").split())


class TestCreate:
    def test_create_calls_the_service_and_summarises(self, no_config, tmp_path):
        manifest = _manifest(errors={"ntp": "500"}, skipped=["stream"])
        create = AsyncMock(return_value=(tmp_path / "backup-x", manifest))

        with (
            patch.object(DeviceContext, "open", return_value=FakeDevice()),
            patch("axis_cam.cli.backup.create_backup", create),
        ):
            result = runner.invoke(
                app,
                ["backup", "create", "-o", str(tmp_path), "--with-server-report", *HOST_ARGS],
            )

        assert result.exit_code == 0, result.output
        create.assert_awaited_once()
        kwargs = create.await_args.kwargs
        assert kwargs == {"name": "10.0.0.5", "include_server_report": True}
        assert create.await_args.args[1] == tmp_path
        text = _text(result)
        assert "Backup written" in text and "2 files" in text
        assert "ntp: 500" in text and "stream" in text
        assert "Not included by design" in text

    def test_create_defaults(self, no_config, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        create = AsyncMock(return_value=(tmp_path / "backup-x", _manifest()))

        with (
            patch.object(DeviceContext, "open", return_value=FakeDevice()),
            patch("axis_cam.cli.backup.create_backup", create),
        ):
            result = runner.invoke(app, ["backup", "create", *HOST_ARGS])

        assert result.exit_code == 0, result.output
        assert create.await_args.args[1] == Path()
        assert create.await_args.kwargs["include_server_report"] is False

    def test_auth_error_is_one_line_exit_1(self, no_config, tmp_path):
        create = AsyncMock(side_effect=AxisAuthenticationError("401"))
        with (
            patch.object(DeviceContext, "open", return_value=FakeDevice()),
            patch("axis_cam.cli.backup.create_backup", create),
        ):
            result = runner.invoke(app, ["backup", "create", "-o", str(tmp_path), *HOST_ARGS])

        assert result.exit_code == 1 and "Error: 401" in result.output


class TestShowAndVerify:
    def _write_backup(self, tmp_path) -> Path:
        backup_dir = tmp_path / "backup-front-20261013T110000Z"
        backup_dir.mkdir()
        payloads = {
            "device_info.json": b'{"product_number": "M3216-LVE"}',
            "ssh.json": b'{"enabled": false}',
        }
        import hashlib

        files = []
        for name, content in payloads.items():
            (backup_dir / name).write_bytes(content)
            files.append(
                BackupFile(
                    name.removesuffix(".json"),
                    name,
                    hashlib.sha256(content).hexdigest(),
                    len(content),
                    "x",
                )
            )
        manifest = _manifest(files=files)
        (backup_dir / MANIFEST_FILE).write_text(json.dumps(manifest.to_dict()))
        return backup_dir

    def test_show_renders_identity_files_and_honesty_lists(self, tmp_path):
        backup_dir = self._write_backup(tmp_path)

        result = runner.invoke(app, ["backup", "show", str(backup_dir)])

        assert result.exit_code == 0, result.output
        text = _text(result)
        assert "M3216-LVE" in text and "ssh.json" in text and "Files (2)" in text
        assert "VAPIX offers no way to read these" in text and "passwords" in text
        assert "not read by this version" in text and "ONVIF" in text
        assert "not implemented" in text  # restore status

    def test_show_json(self, tmp_path):
        backup_dir = self._write_backup(tmp_path)

        result = runner.invoke(app, ["backup", "show", str(backup_dir), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["format_version"] == 1 and len(data["files"]) == 2
        assert "by_design" in data["not_included"]

    def test_show_without_manifest(self, tmp_path):
        result = runner.invoke(app, ["backup", "show", str(tmp_path)])
        assert result.exit_code == 1 and "no manifest.json" in result.output

    def test_show_missing_directory_is_a_usage_error(self, tmp_path):
        result = runner.invoke(app, ["backup", "show", str(tmp_path / "nope")])
        assert result.exit_code == 2

    def test_verify_intact(self, tmp_path):
        backup_dir = self._write_backup(tmp_path)

        result = runner.invoke(app, ["backup", "verify", str(backup_dir)])

        assert result.exit_code == 0, result.output
        assert "Backup intact" in result.output and "2 files" in result.output

    def test_verify_tampered_exits_1(self, tmp_path):
        backup_dir = self._write_backup(tmp_path)
        (backup_dir / "ssh.json").write_bytes(b'{"enabled": true }')

        result = runner.invoke(app, ["backup", "verify", str(backup_dir)])

        assert result.exit_code == 1
        assert "not intact" in result.output and "ssh.json: sha256 mismatch" in result.output


def test_backup_group_is_listed():
    result = runner.invoke(app, ["--help"])
    assert "backup" in result.output


class TestRestore:
    """backup restore follows the write-safety pattern; writes go through params.set."""

    CURRENT: ClassVar[dict[str, str]] = {
        "root.Properties.System.SerialNumber": "B8A44F9F0228",
        "root.Audio.MaxListeners": "10",
        "root.Network.eth0.IPAddress": "192.168.10.12",
    }

    def _backup(self, tmp_path: Path, params: dict, serial="B8A44F9F0228") -> Path:
        import hashlib

        root = tmp_path / "backup-cam-20261013T120000Z"
        root.mkdir()
        content = json.dumps(params).encode()
        (root / "params.json").write_bytes(content)
        manifest = _manifest(
            device={"host": "10.0.0.5", "name": "cam", "serial_number": serial},
            files=[
                BackupFile(
                    "params", "params.json", hashlib.sha256(content).hexdigest(), len(content), "x"
                )
            ],
        )
        (root / MANIFEST_FILE).write_text(json.dumps(manifest.to_dict()))
        return root

    def _device(self):
        state = dict(self.CURRENT)
        params = MagicMock()
        params.export = AsyncMock(return_value=dict(state))

        async def fake_set(name, value):
            state[name] = value

        async def fake_get(name):
            return state.get(name)

        params.set = AsyncMock(side_effect=fake_set)
        params.get = AsyncMock(side_effect=fake_get)
        params.definitions = AsyncMock(return_value={})  # no definitions: attempt everything
        device = FakeDevice()
        device.params = params  # type: ignore[attr-defined]
        return device

    def _run(self, device, args, input=None):
        with patch.object(DeviceContext, "open", return_value=device):
            return runner.invoke(app, ["backup", "restore", *args, *HOST_ARGS], input=input)

    def test_dry_run_shows_the_plan_and_writes_nothing(self, no_config, tmp_path):
        root = self._backup(tmp_path, dict(self.CURRENT, **{"root.Audio.MaxListeners": "20"}))
        device = self._device()

        result = self._run(device, [str(root), "--dry-run", "-v"])

        assert result.exit_code == 0, result.output
        text = _text(result)
        assert "Restore 1 parameter(s)" in text and "root.Audio.MaxListeners: '10' -> '20'" in text
        assert "Dry run" in text
        device.params.set.assert_not_awaited()

    def test_declining_writes_nothing_and_exits_1(self, no_config, tmp_path):
        root = self._backup(tmp_path, dict(self.CURRENT, **{"root.Audio.MaxListeners": "20"}))
        device = self._device()

        result = self._run(device, [str(root)], input="n\n")

        assert result.exit_code == 1 and device.params.set.await_count == 0

    def test_yes_applies_and_reports_per_parameter(self, no_config, tmp_path):
        root = self._backup(tmp_path, dict(self.CURRENT, **{"root.Audio.MaxListeners": "20"}))
        device = self._device()

        result = self._run(device, [str(root), "--yes"])

        assert result.exit_code == 0, result.output
        device.params.set.assert_awaited_once_with("root.Audio.MaxListeners", "20")
        text = _text(result)
        assert "Restored 1/1" in text and "verified" in text

    def test_network_excluded_by_default_and_warned_when_included(self, no_config, tmp_path):
        root = self._backup(
            tmp_path, dict(self.CURRENT, **{"root.Network.eth0.IPAddress": "192.168.10.99"})
        )

        result = self._run(self._device(), [str(root), "--dry-run"])
        assert result.exit_code == 0 and "Nothing to restore" in _text(result)
        assert "network group" in _text(result)

        result = self._run(self._device(), [str(root), "--dry-run", "--include-network"])
        assert "Restore 1 parameter(s)" in _text(result)
        assert "cuts this connection" in _text(result)

    def test_credentials_excluded_by_default_and_included_on_request(self, no_config, tmp_path):
        root = self._backup(
            tmp_path, dict(self.CURRENT, **{"root.SNMP.ReadCommunity": "zq-rotated"})
        )
        device = self._device()
        device.params.export.return_value = dict(  # type: ignore[attr-defined]
            self.CURRENT, **{"root.SNMP.ReadCommunity": "public"}
        )

        result = self._run(device, [str(root), "--dry-run", "-v"])
        assert result.exit_code == 0 and "Nothing to restore" in _text(result)
        assert "credential" in _text(result)
        assert "zq-rotated" not in _text(result)

        result = self._run(device, [str(root), "--dry-run", "-v", "--include-secrets"])
        assert "Restore 1 parameter(s)" in _text(result)
        assert "zq-rotated" not in _text(result) and "value not shown" in _text(result)
        assert "credentials are included" in _text(result)

    def test_backup_from_another_device_is_refused(self, no_config, tmp_path):
        root = self._backup(tmp_path, self.CURRENT, serial="ACCC8E000001")

        result = self._run(self._device(), [str(root), "--yes"])

        assert result.exit_code == 1 and "refusing to restore across devices" in _text(result)
        assert "Planned change" not in result.output

    def test_device_refusal_exits_1_but_other_changes_land(self, no_config, tmp_path):
        from axis_cam.exceptions import AxisDeviceError

        root = self._backup(
            tmp_path,
            dict(self.CURRENT, **{"root.Audio.MaxListeners": "20", "root.Image.Compression": "40"}),
        )
        device = self._device()
        device.params.export = AsyncMock(
            return_value=dict(self.CURRENT, **{"root.Image.Compression": "30"})
        )
        original_set = device.params.set.side_effect

        async def refusing_set(name, value):
            if name == "root.Image.Compression":
                raise AxisDeviceError("param.cgi: Error setting 'Image.Compression' to '40'!")
            await original_set(name, value)

        device.params.set = AsyncMock(side_effect=refusing_set)

        result = self._run(device, [str(root), "--yes"])

        assert result.exit_code == 1
        text = _text(result)
        assert "Restored 1/2" in text and "Error setting" in text
