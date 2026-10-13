"""Tests for private file writes: write_private, download commands, init."""

import os
import stat
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from axis_cam.cli import DeviceContext, app
from axis_cam.cli.download import CRASH_REPORT_TIMEOUT
from axis_cam.config import AppConfig
from axis_cam.files import PRIVATE_MODE, write_private
from axis_cam.models import ServerReport, ServerReportFormat

runner = CliRunner()
HOST_ARGS = ["--host", "10.0.0.5", "-u", "admin", "-p", "secret"]
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")


def _mode(path) -> int:
    return stat.S_IMODE(Path(path).stat().st_mode)


class TestWritePrivate:
    @posix_only
    def test_creates_file_with_0600(self, tmp_path):
        target = tmp_path / "nested" / "report.zip"

        result = write_private(target, b"payload")

        assert result == target and target.read_bytes() == b"payload"
        assert _mode(target) == PRIVATE_MODE

    @posix_only
    def test_tightens_a_pre_existing_world_readable_file(self, tmp_path):
        target = tmp_path / "report.zip"
        target.write_bytes(b"old, longer content")
        target.chmod(0o644)

        write_private(target, b"new")

        assert target.read_bytes() == b"new"  # truncated, not appended
        assert _mode(target) == PRIVATE_MODE

    def test_writes_large_content_completely(self, tmp_path):
        payload = os.urandom(5 * 1024 * 1024)

        write_private(tmp_path / "big.tgz", payload)

        assert (tmp_path / "big.tgz").read_bytes() == payload

    def test_accepts_str_paths(self, tmp_path):
        write_private(str(tmp_path / "s.txt"), b"x")
        assert (tmp_path / "s.txt").read_bytes() == b"x"


class FakeServerReport:
    def __init__(self, report: ServerReport):
        self.get_debug_archive = AsyncMock(return_value=report)
        self.download_report = AsyncMock(return_value=report)


class FakeDevice:
    def __init__(self, serverreport: FakeServerReport):
        self.host = "10.0.0.5"
        self.serverreport = serverreport

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None


@pytest.fixture
def no_config():
    with patch("axis_cam.cli.context.load_config", return_value=AppConfig()):
        yield


def _archive(fmt=ServerReportFormat.DEBUG_TGZ, content=b"\x1f\x8b-fake-tgz") -> ServerReport:
    return ServerReport(content=content, format=fmt, size_bytes=len(content), filename="x")


def _run(serverreport: FakeServerReport, args: list[str]):
    with patch.object(DeviceContext, "open", return_value=FakeDevice(serverreport)):
        return runner.invoke(app, ["download", *args, *HOST_ARGS])


def _text(result) -> str:
    return " ".join(result.output.split())


class TestCrashReport:
    @posix_only
    def test_writes_0600_and_prints_the_privacy_notice(self, no_config, tmp_path):
        sr = FakeServerReport(_archive())
        out = tmp_path / "crash.tgz"

        result = _run(sr, ["crash-report", "-o", str(out)])

        assert result.exit_code == 0, result.output
        assert out.read_bytes() == b"\x1f\x8b-fake-tgz" and _mode(out) == PRIVATE_MODE
        text = _text(result)
        assert "Notice:" in text and "passwords" in text and "0600" in text
        assert "Crash report downloaded" in text

    def test_default_timeout_is_five_minutes(self, no_config, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        sr = FakeServerReport(_archive())

        result = _run(sr, ["crash-report"])

        assert result.exit_code == 0, result.output
        sr.get_debug_archive.assert_awaited_once_with(timeout=CRASH_REPORT_TIMEOUT)
        assert CRASH_REPORT_TIMEOUT == 300.0
        assert (tmp_path / "crash_report_10_0_0_5.tgz").exists()

    def test_timeout_option_is_forwarded(self, no_config, tmp_path):
        sr = FakeServerReport(_archive())

        _run(sr, ["crash-report", "-o", str(tmp_path / "c.tgz"), "--timeout", "600"])

        sr.get_debug_archive.assert_awaited_once_with(timeout=600.0)

    def test_debug_is_a_hidden_alias_of_crash_report(self, no_config, tmp_path):
        sr = FakeServerReport(_archive())
        out = tmp_path / "d.tgz"

        result = _run(sr, ["debug", "-o", str(out)])

        assert result.exit_code == 0, result.output
        assert out.exists() and "Crash report downloaded" in _text(result)
        commands = [
            line.split()[1]
            for line in runner.invoke(app, ["download", "--help"]).output.splitlines()
            if line.startswith("│ ") and len(line.split()) > 1 and line.split()[1].isalpha()
        ]
        assert "crash-report" in runner.invoke(app, ["download", "--help"]).output
        assert "debug" not in commands  # hidden alias

    def test_device_error_is_reported_and_nothing_written(self, no_config, tmp_path):
        failed = ServerReport(content=b"", size_bytes=0, error="Device error 500")
        sr = FakeServerReport(failed)
        out = tmp_path / "c.tgz"

        result = _run(sr, ["crash-report", "-o", str(out)])

        assert result.exit_code == 1 and "Device error 500" in _text(result)
        assert not out.exists()


class TestServerReportDownload:
    @posix_only
    def test_writes_0600(self, no_config, tmp_path):
        sr = FakeServerReport(_archive(ServerReportFormat.ZIP_WITH_IMAGE, b"PK-zip"))
        out = tmp_path / "r.zip"

        result = _run(sr, ["report", "-o", str(out)])

        assert result.exit_code == 0, result.output
        assert _mode(out) == PRIVATE_MODE
        sr.download_report.assert_awaited_once_with(
            format=ServerReportFormat.ZIP_WITH_IMAGE, timeout=60.0
        )

    def test_invalid_format_is_rejected(self, no_config):
        result = _run(FakeServerReport(_archive()), ["report", "--format", "pdf"])
        assert result.exit_code == 1 and "Invalid format" in _text(result)


class TestInitWritesPrivateConfig:
    @posix_only
    def test_init_creates_0600_config(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        with (
            patch("axis_cam.cli.config.get_config_file", return_value=config_file),
            patch("axis_cam.cli.config.get_config_dir", return_value=tmp_path),
        ):
            result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        assert config_file.exists() and _mode(config_file) == PRIVATE_MODE
