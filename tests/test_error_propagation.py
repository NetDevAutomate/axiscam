"""Authentication and connection errors must propagate, never masquerade as data.

Before this change 62 ``except Exception`` sites in the API and device
modules turned a 401/403 or a timeout into an empty or default-valued result,
so ``ssh.get_config()`` on a device that refused the request reported
``enabled=False`` — "could not read" rendered as "disabled". Only
``AxisDeviceError`` (the device answered with an error or unusable payload)
and ``AxisApiNotSupportedError`` may be absorbed into a fallback.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

from axis_cam.api.param import ParamAPI
from axis_cam.api.serverreport import ServerReportAPI
from axis_cam.api.ssh import SshAPI
from axis_cam.cli import app
from axis_cam.devices import AxisRecorder
from axis_cam.exceptions import (
    AxisAuthenticationError,
    AxisConnectionError,
    AxisDeviceError,
)

runner = CliRunner()


def _client() -> MagicMock:
    client = MagicMock()
    client.host = "192.168.1.10"
    return client


class TestApiModulesPropagate:
    @pytest.mark.asyncio
    async def test_ssh_config_auth_error_propagates(self):
        api = SshAPI(_client())
        api._get = AsyncMock(side_effect=AxisAuthenticationError("403"))
        with pytest.raises(AxisAuthenticationError):
            await api.get_config()

    @pytest.mark.asyncio
    async def test_ssh_config_device_error_still_falls_back(self):
        api = SshAPI(_client())
        api._get = AsyncMock(side_effect=AxisDeviceError("404"))
        config = await api.get_config()
        assert config.enabled is False

    @pytest.mark.asyncio
    async def test_param_get_connection_error_propagates(self):
        api = ParamAPI(_client())
        api._get = AsyncMock(side_effect=AxisConnectionError("timeout"))
        with pytest.raises(AxisConnectionError):
            await api.get("root.Brand.Brand")

    @pytest.mark.asyncio
    async def test_param_export_does_not_fall_back_on_auth_error(self):
        api = ParamAPI(_client())
        api._get = AsyncMock(side_effect=AxisAuthenticationError("401"))
        with pytest.raises(AxisAuthenticationError):
            await api.export()


class TestServerReportPropagates:
    """download_report keeps error-as-value for device errors only."""

    @pytest.mark.asyncio
    async def test_device_error_is_returned_in_model(self):
        client = _client()
        client.get_binary = AsyncMock(side_effect=AxisDeviceError("500"))
        report = await ServerReportAPI(client).download_report()
        assert report.success is False
        assert "500" in (report.error or "")

    @pytest.mark.asyncio
    async def test_auth_error_propagates(self):
        client = _client()
        client.get_binary = AsyncMock(side_effect=AxisAuthenticationError("401"))
        with pytest.raises(AxisAuthenticationError):
            await ServerReportAPI(client).download_report()


class TestDeviceClassesPropagate:
    @pytest.mark.asyncio
    async def test_recorder_storage_info_auth_error_propagates(self):
        recorder = AxisRecorder("192.168.1.10", "admin", "password")
        recorder._client.get_json = AsyncMock(side_effect=AxisAuthenticationError("401"))
        with pytest.raises(AxisAuthenticationError):
            await recorder.get_storage_info()


class TestCliReportsAxisErrors:
    """run_async is the single place an AxisError becomes a clean exit 1."""

    def test_auth_error_is_a_one_line_error_not_a_traceback(self, monkeypatch):
        from axis_cam import cli

        class FailingDevice:
            async def __aenter__(self):
                raise AxisAuthenticationError("Authentication failed for 192.168.1.10")

            async def __aexit__(self, *exc):
                return None

        monkeypatch.setattr(cli.ResolvedDevice, "open", lambda self, **kw: FailingDevice())

        result = runner.invoke(
            app, ["info", "--host", "192.168.1.10", "-u", "admin", "-p", "secret"]
        )

        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "Authentication failed" in result.output
        assert "Traceback" not in result.output

    def test_tracebacks_never_show_locals(self):
        # Locals would include the device password.
        assert app.pretty_exceptions_show_locals is False
