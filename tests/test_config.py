"""Tests for configuration management."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from axis_cam.config import (
    APP_NAME,
    AppConfig,
    DeviceConfig,
    create_default_config,
    get_config_dir,
    get_config_file,
    get_data_dir,
    get_device_config,
    interpolate_env_vars,
    load_config,
    load_env_config,
    load_yaml_config,
)


class TestDeviceConfig:
    """Tests for DeviceConfig model."""

    def test_create_with_required_fields(self):
        """Test creating DeviceConfig with required fields."""
        config = DeviceConfig(
            host="192.168.1.10",
            username="admin",
            password=SecretStr("password123"),
        )
        assert config.host == "192.168.1.10"
        assert config.username == "admin"
        assert config.password.get_secret_value() == "password123"
        assert config.port == 443
        assert config.ssl_verify is False
        assert config.device_type == "camera"

    def test_create_with_all_fields(self):
        """Test creating DeviceConfig with all fields."""
        config = DeviceConfig(
            host="192.168.1.10",
            username="admin",
            password=SecretStr("password123"),
            port=8080,
            ssl_verify=True,
            device_type="recorder",
            name="Front Camera",
        )
        assert config.port == 8080
        assert config.ssl_verify is True
        assert config.device_type == "recorder"
        assert config.name == "Front Camera"

    def test_host_validation_empty(self):
        """Test that empty host raises validation error."""
        with pytest.raises(ValueError, match="Host cannot be empty"):
            DeviceConfig(
                host="",
                username="admin",
                password=SecretStr("password"),
            )

    def test_host_validation_whitespace(self):
        """Test that whitespace-only host raises validation error."""
        with pytest.raises(ValueError, match="Host cannot be empty"):
            DeviceConfig(
                host="   ",
                username="admin",
                password=SecretStr("password"),
            )

    def test_host_is_stripped(self):
        """Test that host is stripped of whitespace."""
        config = DeviceConfig(
            host="  192.168.1.10  ",
            username="admin",
            password=SecretStr("password"),
        )
        assert config.host == "192.168.1.10"

    def test_device_type_defaults_unknown_to_camera(self):
        """Test that unknown device_type defaults to camera."""
        config = DeviceConfig(
            host="192.168.1.10",
            username="admin",
            password=SecretStr("password"),
            device_type="unknown_type",
        )
        # Unknown device types default to "camera" for compatibility
        assert config.device_type == "camera"

    def test_device_type_normalization(self):
        """Test that device type is normalized to lowercase."""
        config = DeviceConfig(
            host="192.168.1.10",
            username="admin",
            password=SecretStr("password"),
            device_type="CAMERA",
        )
        assert config.device_type == "camera"

    def test_valid_device_types(self):
        """Test all valid device types."""
        for device_type in ["camera", "recorder", "intercom", "speaker"]:
            config = DeviceConfig(
                host="192.168.1.10",
                username="admin",
                password=SecretStr("password"),
                device_type=device_type,
            )
            assert config.device_type == device_type

    def test_port_validation_range(self):
        """Test port number validation range."""
        # Valid port
        config = DeviceConfig(
            host="192.168.1.10",
            username="admin",
            password=SecretStr("password"),
            port=8080,
        )
        assert config.port == 8080

        # Invalid port - too low
        with pytest.raises(ValueError):
            DeviceConfig(
                host="192.168.1.10",
                username="admin",
                password=SecretStr("password"),
                port=0,
            )

        # Invalid port - too high
        with pytest.raises(ValueError):
            DeviceConfig(
                host="192.168.1.10",
                username="admin",
                password=SecretStr("password"),
                port=70000,
            )


class TestAppConfig:
    """Tests for AppConfig model."""

    def test_create_with_defaults(self):
        """Test creating AppConfig with defaults."""
        config = AppConfig()
        assert config.default_device is None
        assert config.timeout == 30.0
        assert config.devices == {}

    def test_create_with_devices(self):
        """Test creating AppConfig with devices."""
        devices = {
            "camera1": DeviceConfig(
                host="192.168.1.10",
                username="admin",
                password=SecretStr("password"),
            )
        }
        config = AppConfig(
            default_device="camera1",
            timeout=60.0,
            devices=devices,
        )
        assert config.default_device == "camera1"
        assert config.timeout == 60.0
        assert "camera1" in config.devices

    def test_timeout_validation_range(self):
        """Test timeout validation range."""
        # Valid timeout
        config = AppConfig(timeout=120.0)
        assert config.timeout == 120.0

        # Too low
        with pytest.raises(ValueError):
            AppConfig(timeout=0.5)

        # Too high
        with pytest.raises(ValueError):
            AppConfig(timeout=500.0)


class TestInterpolateEnvVars:
    """Tests for interpolate_env_vars function."""

    def test_interpolate_string(self):
        """Test interpolating environment variables in a string."""
        with patch.dict(os.environ, {"TEST_VAR": "test_value"}):
            result = interpolate_env_vars("prefix_${TEST_VAR}_suffix")
            assert result == "prefix_test_value_suffix"

    def test_interpolate_missing_var(self):
        """Test interpolating missing environment variable."""
        with patch.dict(os.environ, {}, clear=True):
            result = interpolate_env_vars("${MISSING_VAR}")
            assert result == ""

    def test_interpolate_dict(self):
        """Test interpolating environment variables in a dict."""
        with patch.dict(os.environ, {"USER": "admin", "PASS": "secret"}):
            data = {"username": "${USER}", "password": "${PASS}"}
            result = interpolate_env_vars(data)
            assert result == {"username": "admin", "password": "secret"}

    def test_interpolate_list(self):
        """Test interpolating environment variables in a list."""
        with patch.dict(os.environ, {"VAR1": "value1", "VAR2": "value2"}):
            data = ["${VAR1}", "${VAR2}"]
            result = interpolate_env_vars(data)
            assert result == ["value1", "value2"]

    def test_interpolate_nested(self):
        """Test interpolating environment variables in nested structures."""
        with patch.dict(os.environ, {"HOST": "192.168.1.10"}):
            data = {
                "device": {
                    "host": "${HOST}",
                    "ports": ["${HOST}:80", "${HOST}:443"],
                }
            }
            result = interpolate_env_vars(data)
            assert result["device"]["host"] == "192.168.1.10"
            assert result["device"]["ports"][0] == "192.168.1.10:80"

    def test_interpolate_non_string(self):
        """Test that non-string values pass through unchanged."""
        assert interpolate_env_vars(123) == 123
        assert interpolate_env_vars(True) is True
        assert interpolate_env_vars(None) is None


class TestLoadYamlConfig:
    """Tests for load_yaml_config function."""

    def test_load_nonexistent_file(self, tmp_path):
        """Test loading a nonexistent file returns empty dict."""
        result = load_yaml_config(tmp_path / "nonexistent.yaml")
        assert result == {}

    def test_load_valid_yaml(self, tmp_path):
        """Test loading a valid YAML file."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("""
default_device: camera1
timeout: 60.0
devices:
  camera1:
    host: 192.168.1.10
    username: admin
    password: password123
""")
        result = load_yaml_config(yaml_file)
        assert result["default_device"] == "camera1"
        assert result["timeout"] == 60.0
        assert result["devices"]["camera1"]["host"] == "192.168.1.10"

    def test_load_yaml_with_env_interpolation(self, tmp_path):
        """Test loading YAML with environment variable interpolation."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("""
devices:
  camera1:
    host: 192.168.1.10
    username: ${TEST_USERNAME}
    password: ${TEST_PASSWORD}
""")
        with patch.dict(os.environ, {"TEST_USERNAME": "admin", "TEST_PASSWORD": "secret"}):
            result = load_yaml_config(yaml_file)
            assert result["devices"]["camera1"]["username"] == "admin"
            assert result["devices"]["camera1"]["password"] == "secret"

    def test_load_empty_yaml(self, tmp_path):
        """Test loading an empty YAML file returns empty dict."""
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("")
        result = load_yaml_config(yaml_file)
        assert result == {}


class TestLoadEnvConfig:
    """Tests for load_env_config function."""

    def test_load_empty_env(self):
        """Test loading with no AXIS environment variables."""
        with patch.dict(os.environ, {}, clear=True):
            result = load_env_config()
            assert result == {}

    def test_load_basic_env_vars(self):
        """Test loading basic AXIS environment variables."""
        env_vars = {
            "AXIS_HOST": "192.168.1.10",
            "AXIS_USERNAME": "admin",
            "AXIS_PASSWORD": "password123",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            result = load_env_config()
            assert result["host"] == "192.168.1.10"
            assert result["username"] == "admin"
            assert result["password"] == "password123"

    def test_load_admin_env_vars(self):
        """Test loading AXIS_ADMIN_* environment variables."""
        env_vars = {
            "AXIS_ADMIN_USERNAME": "admin_user",
            "AXIS_ADMIN_PASSWORD": "admin_pass",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            result = load_env_config()
            assert result["username"] == "admin_user"
            assert result["password"] == "admin_pass"

    def test_load_port_as_int(self):
        """Test that port is converted to int."""
        with patch.dict(os.environ, {"AXIS_PORT": "8080"}, clear=True):
            result = load_env_config()
            assert result["port"] == 8080
            assert isinstance(result["port"], int)

    def test_load_ssl_verify_true(self):
        """Test ssl_verify conversion for true values."""
        for value in ["true", "True", "TRUE", "1", "yes"]:
            with patch.dict(os.environ, {"AXIS_SSL_VERIFY": value}, clear=True):
                result = load_env_config()
                assert result["ssl_verify"] is True

    def test_load_ssl_verify_false(self):
        """Test ssl_verify conversion for false values."""
        for value in ["false", "False", "FALSE", "0", "no"]:
            with patch.dict(os.environ, {"AXIS_SSL_VERIFY": value}, clear=True):
                result = load_env_config()
                assert result["ssl_verify"] is False


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_empty(self, tmp_path):
        """Test loading config with no config file."""
        # Clear the LRU cache
        load_config.cache_clear()

        with (
            patch("axis_cam.config.get_config_file", return_value=tmp_path / "nonexistent.yaml"),
            patch.dict(os.environ, {}, clear=True),
        ):
            config = load_config()
            assert isinstance(config, AppConfig)
            assert config.devices == {}

    def test_load_config_from_file(self, tmp_path):
        """Test loading config from file."""
        load_config.cache_clear()

        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("""
default_device: camera1
timeout: 45.0
devices:
  camera1:
    host: 192.168.1.10
    username: admin
    password: password123
    device_type: camera
""")
        with (
            patch("axis_cam.config.get_config_file", return_value=yaml_file),
            patch.dict(os.environ, {}, clear=True),
        ):
            config = load_config()
            assert config.default_device == "camera1"
            assert config.timeout == 45.0
            assert "camera1" in config.devices

    def test_load_config_env_override(self, tmp_path):
        """Test that environment config creates default device."""
        load_config.cache_clear()

        env_vars = {
            "AXIS_HOST": "192.168.1.100",
            "AXIS_USERNAME": "env_user",
            "AXIS_PASSWORD": "env_pass",
        }
        with (
            patch("axis_cam.config.get_config_file", return_value=tmp_path / "nonexistent.yaml"),
            patch.dict(os.environ, env_vars, clear=True),
        ):
            config = load_config()
            assert "default" in config.devices
            assert config.devices["default"].host == "192.168.1.100"


class TestGetDeviceConfig:
    """Tests for get_device_config function."""

    def test_get_existing_device(self, tmp_path):
        """Test getting config for an existing device."""
        load_config.cache_clear()

        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("""
devices:
  camera1:
    host: 192.168.1.10
    username: admin
    password: password123
    device_type: camera
""")
        with (
            patch("axis_cam.config.get_config_file", return_value=yaml_file),
            patch.dict(os.environ, {}, clear=True),
        ):
            device_config = get_device_config("camera1")
            assert device_config is not None
            assert device_config.host == "192.168.1.10"

    def test_get_nonexistent_device(self, tmp_path):
        """Test getting config for a nonexistent device."""
        load_config.cache_clear()

        with (
            patch("axis_cam.config.get_config_file", return_value=tmp_path / "nonexistent.yaml"),
            patch.dict(os.environ, {}, clear=True),
        ):
            device_config = get_device_config("nonexistent")
            assert device_config is None

    def test_get_default_device(self, tmp_path):
        """Test getting config using default device."""
        load_config.cache_clear()

        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("""
default_device: camera1
devices:
  camera1:
    host: 192.168.1.10
    username: admin
    password: password123
""")
        with (
            patch("axis_cam.config.get_config_file", return_value=yaml_file),
            patch.dict(os.environ, {}, clear=True),
        ):
            device_config = get_device_config(None)
            assert device_config is not None
            assert device_config.host == "192.168.1.10"


class TestConfigPaths:
    """Tests for configuration path functions."""

    def test_get_config_dir(self):
        """Test get_config_dir returns a Path."""
        result = get_config_dir()
        assert isinstance(result, Path)
        assert APP_NAME in str(result)

    def test_get_data_dir(self):
        """Test get_data_dir returns a Path."""
        result = get_data_dir()
        assert isinstance(result, Path)
        assert APP_NAME in str(result)

    def test_get_config_file(self):
        """Test get_config_file returns config.yaml path."""
        result = get_config_file()
        assert isinstance(result, Path)
        assert result.name == "config.yaml"


class TestCreateDefaultConfig:
    """Tests for create_default_config function."""

    def test_returns_yaml_string(self):
        """Test that create_default_config returns a valid YAML string."""
        result = create_default_config()
        assert isinstance(result, str)
        assert "default_device:" in result
        assert "devices:" in result

    def test_contains_example_devices(self):
        """Test that default config contains example devices."""
        result = create_default_config()
        assert "front_door:" in result
        assert "main_nvr:" in result
        assert "front_intercom:" in result
        assert "office_speaker:" in result

    def test_contains_env_var_placeholders(self):
        """Test that default config contains environment variable placeholders."""
        result = create_default_config()
        assert "${AXIS_ROOT_USER_NAME}" in result
        assert "${AXIS_ROOT_USER_PASSWORD}" in result
