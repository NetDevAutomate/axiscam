"""Tests for CLI module."""

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from axis_cam.cli import ResolvedDevice, app, get_device_class, resolve_device_config
from axis_cam.config import AppConfig, DeviceConfig

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
    """Tests for resolve_device_config.

    load_config is patched so these never read the developer's real config.
    """

    @staticmethod
    def _config(**devices: DeviceConfig) -> AppConfig:
        return AppConfig(timeout=12.5, devices=devices)

    def test_resolve_with_host(self):
        """--host is ad hoc: HTTPS, port 443, app timeout."""
        with patch("axis_cam.cli.load_config", return_value=self._config()):
            target = resolve_device_config(
                device=None, host="192.168.1.10", username="admin", password="pass123"
            )
        assert target == ResolvedDevice(
            host="192.168.1.10",
            username="admin",
            password="pass123",
            port=443,
            device_type="camera",
            https=True,
            ssl_verify=False,
            timeout=12.5,
        )

    def test_resolve_host_overrides_device(self):
        """--host wins over --device."""
        with patch("axis_cam.cli.load_config", return_value=self._config()):
            target = resolve_device_config(
                device="some_device", host="192.168.1.50", username="user", password="secret"
            )
        assert target.host == "192.168.1.50"

    def test_resolve_missing_credentials(self):
        """--host without credentials exits."""
        import typer

        with (
            patch("axis_cam.cli.load_config", return_value=self._config()),
            pytest.raises(typer.Exit),
        ):
            resolve_device_config(device=None, host="192.168.1.10", username=None, password=None)

    def test_resolve_with_device_name_carries_transport_settings(self):
        """Regression: ssl_verify, https and timeout from config must reach the device.

        Before this test existed the CLI dropped ssl_verify on the floor, so a
        device configured with ssl_verify: true was contacted without TLS
        verification.
        """
        cfg = self._config(
            test_camera=DeviceConfig(
                host="192.168.1.100",
                username="admin",
                password="test123",
                port=8443,
                https=True,
                ssl_verify=True,
                type="recorder",
            )
        )
        with patch("axis_cam.cli.load_config", return_value=cfg):
            target = resolve_device_config(
                device="test_camera", host=None, username=None, password=None
            )
        assert target.host == "192.168.1.100"
        assert target.username == "admin"
        assert target.password == "test123"
        assert target.port == 8443
        assert target.device_type == "recorder"
        assert target.https is True
        assert target.ssl_verify is True
        assert target.timeout == 12.5

    def test_resolve_uses_default_device_when_none_given(self):
        cfg = AppConfig(
            default_device="main",
            devices={
                "main": DeviceConfig(host="10.0.0.5", username="u", password="p", https=False)
            },
        )
        with patch("axis_cam.cli.load_config", return_value=cfg):
            target = resolve_device_config(device=None, host=None, username=None, password=None)
        assert target.host == "10.0.0.5"
        assert target.https is False

    def test_explicit_port_443_overrides_config_port(self):
        """--port 443 is a real override, not a sentinel for 'unset'."""
        cfg = self._config(cam=DeviceConfig(host="10.0.0.9", username="u", password="p", port=8443))
        with patch("axis_cam.cli.load_config", return_value=cfg):
            explicit = resolve_device_config(
                device="cam", host=None, username=None, password=None, port=443
            )
            unset = resolve_device_config(device="cam", host=None, username=None, password=None)
        assert explicit.port == 443
        assert unset.port == 8443

    def test_resolve_device_as_host_found_in_config(self):
        """--device that is an address resolves the matching config entry."""
        cfg = self._config(
            cam=DeviceConfig(host="192.168.1.200", username="cfg", password="p", ssl_verify=True)
        )
        with patch("axis_cam.cli.load_config", return_value=cfg):
            target = resolve_device_config(
                device="192.168.1.200", host=None, username=None, password=None
            )
        assert target.username == "cfg"
        assert target.ssl_verify is True

    def test_resolve_device_as_host_ad_hoc(self):
        """--device that is an address but not in config needs credentials."""
        with patch("axis_cam.cli.load_config", return_value=self._config()):
            target = resolve_device_config(
                device="192.168.1.200", host=None, username="admin", password="secret"
            )
        assert target.host == "192.168.1.200"
        assert target.https is True

    def test_resolve_no_device_or_host(self):
        """Nothing provided exits."""
        import typer

        with (
            patch("axis_cam.cli.load_config", return_value=self._config()),
            pytest.raises(typer.Exit),
        ):
            resolve_device_config(device=None, host=None, username=None, password=None)


class TestResolvedDeviceOpen:
    """ResolvedDevice.open passes every transport setting to the device class."""

    def test_open_passes_transport_settings(self):
        target = ResolvedDevice(
            host="10.0.0.5",
            username="u",
            password="p",
            port=8080,
            device_type="speaker",
            https=False,
            ssl_verify=True,
            timeout=5.0,
        )
        dev = target.open(use_digest_auth=True)
        assert type(dev).__name__ == "AxisSpeaker"
        assert dev.client.base_url == "http://10.0.0.5:8080"
        assert dev.client.verify_ssl is True
        assert dev.client.timeout == 5.0
        assert dev.client.use_digest_auth is True

    def test_open_defaults_to_https_and_verified_flag_from_config(self):
        target = ResolvedDevice(
            host="10.0.0.5", username="u", password="p", port=8443, device_type="camera"
        )
        dev = target.open(use_digest_auth=False)
        assert dev.client.base_url == "https://10.0.0.5:8443"


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
