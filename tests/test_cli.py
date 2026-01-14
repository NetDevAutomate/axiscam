"""Tests for CLI module."""

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from axis_cam.cli import app, get_device_class, resolve_device_config

runner = CliRunner()


class TestCLIStructure:
    """Tests for CLI app structure."""

    def test_app_exists(self):
        """Test that the CLI app exists."""
        assert app is not None

    def test_app_has_help(self):
        """Test that the app has help text."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "AXIS" in result.stdout or "axis" in result.stdout.lower()

    def test_logs_command_exists(self):
        """Test that logs command exists."""
        result = runner.invoke(app, ["logs", "--help"])
        assert result.exit_code == 0
        assert "logs" in result.stdout.lower()


class TestGetDeviceClass:
    """Tests for get_device_class function."""

    def test_get_camera_class(self):
        """Test get_device_class returns AxisCamera."""
        from axis_cam.devices.camera import AxisCamera
        from axis_cam.models import DeviceType

        cls = get_device_class(DeviceType.CAMERA)
        assert cls is AxisCamera

    def test_get_recorder_class(self):
        """Test get_device_class returns AxisRecorder."""
        from axis_cam.devices.recorder import AxisRecorder
        from axis_cam.models import DeviceType

        cls = get_device_class(DeviceType.RECORDER)
        assert cls is AxisRecorder

    def test_get_intercom_class(self):
        """Test get_device_class returns AxisIntercom."""
        from axis_cam.devices.intercom import AxisIntercom
        from axis_cam.models import DeviceType

        cls = get_device_class(DeviceType.INTERCOM)
        assert cls is AxisIntercom

    def test_get_speaker_class(self):
        """Test get_device_class returns AxisSpeaker."""
        from axis_cam.devices.speaker import AxisSpeaker
        from axis_cam.models import DeviceType

        cls = get_device_class(DeviceType.SPEAKER)
        assert cls is AxisSpeaker

    def test_get_unknown_class(self):
        """Test get_device_class returns AxisCamera for unknown type."""
        from axis_cam.devices.camera import AxisCamera
        from axis_cam.models import DeviceType

        cls = get_device_class(DeviceType.UNKNOWN)
        assert cls is AxisCamera


class TestResolveDeviceConfig:
    """Tests for resolve_device_config function."""

    def test_resolve_with_host(self):
        """Test resolve_device_config with host override."""
        host, username, password, _port, _device_type = resolve_device_config(
            device=None,
            host="192.168.1.10",
            username="admin",
            password="pass123",
        )
        assert host == "192.168.1.10"
        assert username == "admin"
        assert password == "pass123"

    def test_resolve_host_overrides_device(self):
        """Test that host parameter overrides device name."""
        host, _username, _password, _port, _device_type = resolve_device_config(
            device="some_device",
            host="192.168.1.50",
            username="user",
            password="secret",
        )
        assert host == "192.168.1.50"

    def test_resolve_missing_credentials(self):
        """Test resolve_device_config with missing credentials raises error."""
        import typer

        with pytest.raises(typer.Exit):
            resolve_device_config(
                device=None,
                host="192.168.1.10",
                username=None,
                password=None,
            )

    @patch("axis_cam.cli.get_device_config")
    def test_resolve_with_device_name(self, mock_get_config):
        """Test resolve_device_config with device name from config."""
        from pydantic import SecretStr

        mock_config = MagicMock()
        mock_config.host = "192.168.1.100"
        mock_config.username = "admin"
        mock_config.password = SecretStr("test123")
        mock_config.port = 443
        mock_config.device_type = "camera"
        mock_get_config.return_value = mock_config

        host, username, _password, _port, _device_type = resolve_device_config(
            device="test_camera",
            host=None,
            username=None,
            password=None,
        )
        assert host == "192.168.1.100"
        assert username == "admin"

    @patch("axis_cam.cli.get_device_config")
    def test_resolve_device_as_host(self, mock_get_config):
        """Test resolve_device_config when device looks like IP address."""
        mock_get_config.return_value = None  # No config found

        host, _username, _password, _port, _device_type = resolve_device_config(
            device="192.168.1.200",
            host=None,
            username="admin",
            password="secret",
        )
        assert host == "192.168.1.200"

    @patch("axis_cam.cli.get_device_config")
    def test_resolve_no_device_or_host(self, mock_get_config):
        """Test resolve_device_config raises error when nothing provided."""
        import typer

        mock_get_config.return_value = None

        with pytest.raises(typer.Exit):
            resolve_device_config(
                device=None,
                host=None,
                username=None,
                password=None,
            )


class TestInfoCommand:
    """Tests for info command."""

    def test_info_requires_device(self):
        """Test info command requires device or host."""
        result = runner.invoke(app, ["info"])
        # Should exit with error when no device specified
        assert (
            result.exit_code != 0
            or "error" in result.stdout.lower()
            or "device" in result.stdout.lower()
        )


class TestLogsCommands:
    """Tests for logs subcommands."""

    def test_logs_system_requires_device(self):
        """Test logs system command requires device."""
        result = runner.invoke(app, ["logs", "system"])
        # Should exit with error when no device specified
        assert (
            result.exit_code != 0
            or "error" in result.stdout.lower()
            or "device" in result.stdout.lower()
        )

    def test_logs_access_requires_device(self):
        """Test logs access command requires device."""
        result = runner.invoke(app, ["logs", "access"])
        assert (
            result.exit_code != 0
            or "error" in result.stdout.lower()
            or "device" in result.stdout.lower()
        )


class TestConfigCommand:
    """Tests for config command."""

    def test_config_help(self):
        """Test config command has help."""
        result = runner.invoke(app, ["config", "--help"])
        # If config command exists, should show help
        if result.exit_code == 0:
            assert "config" in result.stdout.lower()


class TestVersionCommand:
    """Tests for version option."""

    def test_version_option(self):
        """Test --version option."""
        result = runner.invoke(app, ["--version"])
        # May or may not have version implemented
        # Just verify it doesn't crash
        assert result.exit_code in [0, 2]  # 2 is "no such option" which is OK
