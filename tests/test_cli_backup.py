"""Tests for ``axiscam backup``."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
