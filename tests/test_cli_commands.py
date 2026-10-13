"""Tests for the cli package: structure, and commands run end to end.

``DeviceContext.open`` is the one seam between option parsing and the device,
so patching it lets a command run through resolve → open → run_async → render
without a network.
"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from axis_cam.cli import DeviceContext, app
from axis_cam.config import AppConfig
from axis_cam.exceptions import AxisAuthenticationError, AxisConnectionError
from axis_cam.models import SshConfig
from axis_cam.report import DeviceReport

runner = CliRunner()

GROUPS = ["logs", "network", "security", "services", "download", "automation", "media", "stream"]
TOP_LEVEL = {
    "info",
    "status",
    "apis",
    "lldp",
    "params",
    "location",
    "report",
    "config",
    "init",
    "version",
    "devices",
    "migrate",
}
HOST_ARGS = ["--host", "10.0.0.5", "-u", "admin", "-p", "secret"]


class FakeDevice:
    """Async-context-manager device with whatever modules a test hands it."""

    def __init__(self, *, enter_error: Exception | None = None, **modules):
        self.host = "10.0.0.5"
        self._enter_error = enter_error
        for name, module in modules.items():
            setattr(self, name, module)

    async def __aenter__(self):
        if self._enter_error:
            raise self._enter_error
        return self

    async def __aexit__(self, *exc_info):
        return None


@pytest.fixture
def no_config():
    """No config file: every --host run is ad hoc."""
    with patch("axis_cam.cli.context.load_config", return_value=AppConfig()):
        yield


def _open(device: FakeDevice):
    return patch.object(DeviceContext, "open", return_value=device)


class TestStructure:
    def test_top_level_commands(self):
        names = {cmd.name for cmd in app.registered_commands}
        assert names == TOP_LEVEL

    def test_groups(self):
        names = {group.name for group in app.registered_groups}
        assert names == set(GROUPS)

    @pytest.mark.parametrize("group", GROUPS)
    def test_group_help(self, group):
        result = runner.invoke(app, [group, "--help"])
        assert result.exit_code == 0, result.output
        assert "Usage" in result.output

    @pytest.mark.parametrize("command", sorted(TOP_LEVEL))
    def test_top_level_help(self, command):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, result.output

    def test_entry_point_main_is_importable(self):
        from axis_cam.cli import main

        assert callable(main)


class TestCommandsEndToEnd:
    def test_security_ssh_json_renders_the_module_result(self, no_config):
        ssh = SimpleNamespace(get_config=AsyncMock(return_value=SshConfig(enabled=True, port=2222)))

        with _open(FakeDevice(ssh=ssh)):
            result = runner.invoke(app, ["security", "ssh", *HOST_ARGS, "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["enabled"] is True and data["port"] == 2222

    def test_security_ssh_table_renders(self, no_config):
        ssh = SimpleNamespace(get_config=AsyncMock(return_value=SshConfig(enabled=False)))

        with _open(FakeDevice(ssh=ssh)):
            result = runner.invoke(app, ["security", "ssh", *HOST_ARGS])

        assert result.exit_code == 0, result.output
        assert "SSH Configuration" in result.output and "Disabled" in result.output

    def test_digest_flag_reaches_the_context(self, no_config):
        opened: list[DeviceContext] = []

        def fake_open(self):
            opened.append(self)
            return FakeDevice(ssh=SimpleNamespace(get_config=AsyncMock(return_value=SshConfig())))

        with patch.object(DeviceContext, "open", fake_open):
            runner.invoke(app, ["security", "ssh", *HOST_ARGS, "--no-digest"])
            runner.invoke(app, ["security", "ssh", *HOST_ARGS])

        assert [ctx.use_digest_auth for ctx in opened] == [False, True]
        assert opened[0].https is True and opened[0].port == 443

    @pytest.mark.parametrize(
        "exc",
        [AxisConnectionError("All connection attempts failed"), AxisAuthenticationError("401")],
    )
    def test_device_errors_become_one_line_and_exit_1(self, no_config, exc):
        with _open(FakeDevice(enter_error=exc)):
            result = runner.invoke(app, ["security", "ssh", *HOST_ARGS])

        assert result.exit_code == 1
        assert "Error:" in result.output and str(exc) in result.output
        assert "Traceback" not in result.output

    def test_missing_credentials_for_ad_hoc_host_exit_1(self, no_config):
        result = runner.invoke(app, ["security", "ssh", "--host", "10.0.0.5"])

        assert result.exit_code == 1
        assert "Username and password" in result.output


class TestReportCommand:
    def _report(self) -> DeviceReport:
        return DeviceReport(
            device="10.0.0.5",
            generated_at=datetime(2026, 10, 13, 9, 0, tzinfo=UTC),
            sections={"device_info": {"product_number": "M3216", "serial_number": "ACC"}},
            errors={"ntp": "boom"},
            skipped=["stream"],
        )

    def test_json_output_is_valid_and_nested(self, no_config):
        with (
            _open(FakeDevice()),
            patch("axis_cam.cli.device.collect_report", AsyncMock(return_value=self._report())),
        ):
            result = runner.invoke(app, ["report", *HOST_ARGS])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["sections"]["device_info"]["product_number"] == "M3216"
        assert data["errors"] == {"ntp": "boom"} and data["skipped"] == ["stream"]

    def test_full_flag_is_forwarded(self, no_config):
        collect = AsyncMock(return_value=self._report())
        with _open(FakeDevice()), patch("axis_cam.cli.device.collect_report", collect):
            runner.invoke(app, ["report", *HOST_ARGS, "--full"])
            runner.invoke(app, ["report", *HOST_ARGS])

        assert [call.kwargs["full"] for call in collect.await_args_list] == [True, False]

    def test_text_format_and_output_file(self, no_config, tmp_path):
        out = tmp_path / "report.txt"
        with (
            _open(FakeDevice()),
            patch("axis_cam.cli.device.collect_report", AsyncMock(return_value=self._report())),
        ):
            result = runner.invoke(app, ["report", *HOST_ARGS, "--format", "text", "-o", str(out)])

        assert result.exit_code == 0, result.output
        text = out.read_text()
        assert "Model: M3216" in text and "ntp: boom" in text
        assert "Not advertised by device: stream" in text
