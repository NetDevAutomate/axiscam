"""Configuration management for AXIS Camera Manager.

This module handles loading configuration from:
- Environment variables (AXIS_*)
- YAML configuration files
- XDG-compliant config paths

Configuration precedence (highest to lowest):
1. Command-line arguments
2. Environment variables
3. User config file (~/.config/axiscam/config.yaml)
4. System defaults
"""

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from platformdirs import user_config_dir, user_data_dir
from pydantic import BaseModel, Field, SecretStr, field_validator

# Application name for XDG paths
APP_NAME = "axiscam"

# Environment variable prefix
ENV_PREFIX = "AXIS_"


def get_config_dir() -> Path:
    """Get the configuration directory path.

    Returns:
        Path to the configuration directory.
    """
    return Path(user_config_dir(APP_NAME))


def get_data_dir() -> Path:
    """Get the data directory path.

    Returns:
        Path to the data directory.
    """
    return Path(user_data_dir(APP_NAME))


def get_config_file() -> Path:
    """Get the default config file path.

    Returns:
        Path to config.yaml file.
    """
    return get_config_dir() / "config.yaml"


class DeviceConfig(BaseModel):
    """Configuration for a single AXIS device.

    Attributes:
        host: Device IP address or hostname (alias: address).
        username: Authentication username.
        password: Authentication password.
        port: HTTPS port number.
        ssl_verify: Whether to verify SSL certificates.
        device_type: Type of device (camera, recorder, intercom, speaker).
        name: Optional friendly name for the device.
        vendor: Device vendor (e.g., "axis").
        model: Device model number.
    """

    model_config = {"frozen": True, "populate_by_name": True}

    host: str = Field(
        ...,
        alias="address",
        description="Device IP address or hostname",
    )
    username: str = Field(..., description="Authentication username")
    password: SecretStr = Field(..., description="Authentication password")
    port: int = Field(default=443, ge=1, le=65535, description="HTTPS port")
    ssl_verify: bool = Field(default=False, description="Verify SSL certificates")
    device_type: str = Field(
        default="camera",
        alias="type",
        description="Device type",
    )
    name: str | None = Field(default=None, description="Friendly name")
    vendor: str = Field(default="axis", description="Device vendor")
    model: str | None = Field(default=None, description="Device model")

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Validate host is not empty."""
        if not v or not v.strip():
            raise ValueError("Host cannot be empty")
        return v.strip()

    @field_validator("device_type")
    @classmethod
    def validate_device_type(cls, v: str) -> str:
        """Validate device type."""
        valid_types = {"camera", "recorder", "intercom", "speaker"}
        v_lower = v.lower()
        if v_lower not in valid_types:
            raise ValueError(f"Device type must be one of: {valid_types}")
        return v_lower

    @field_validator("vendor")
    @classmethod
    def validate_vendor(cls, v: str) -> str:
        """Validate and normalize vendor name."""
        return v.lower().strip()


class AppConfig(BaseModel):
    """Application-wide configuration.

    Attributes:
        default_device: Default device name to use.
        timeout: Default request timeout in seconds.
        devices: Dictionary of device configurations.
    """

    model_config = {"frozen": True}

    default_device: str | None = Field(
        default=None, description="Default device name"
    )
    timeout: float = Field(
        default=30.0, ge=1.0, le=300.0, description="Request timeout"
    )
    devices: dict[str, DeviceConfig] = Field(
        default_factory=dict, description="Device configurations"
    )


def interpolate_env_vars(value: Any) -> Any:
    """Recursively interpolate environment variables in configuration values.

    Supports ${VAR_NAME} syntax for environment variable substitution.

    Args:
        value: Configuration value (string, dict, or list).

    Returns:
        Value with environment variables interpolated.
    """
    if isinstance(value, str):
        # Match ${VAR_NAME} patterns
        pattern = re.compile(r"\$\{([^}]+)\}")
        matches = pattern.findall(value)
        for var_name in matches:
            env_value = os.environ.get(var_name, "")
            value = value.replace(f"${{{var_name}}}", env_value)
        return value
    elif isinstance(value, dict):
        return {k: interpolate_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [interpolate_env_vars(item) for item in value]
    return value


def load_yaml_config(config_path: Path) -> dict[str, Any]:
    """Load configuration from a YAML file.

    Args:
        config_path: Path to the YAML config file.

    Returns:
        Parsed configuration dictionary.
    """
    if not config_path.exists():
        return {}

    with open(config_path) as f:
        raw_config = yaml.safe_load(f) or {}

    return interpolate_env_vars(raw_config)


def load_env_config() -> dict[str, Any]:
    """Load configuration from environment variables.

    Environment variables with AXIS_ prefix are loaded.
    Common variables:
    - AXIS_HOST: Device hostname/IP
    - AXIS_USERNAME: Username
    - AXIS_PASSWORD: Password
    - AXIS_PORT: Port number

    Returns:
        Configuration dictionary from environment.
    """
    config: dict[str, Any] = {}

    # Map environment variables to config keys
    env_mapping = {
        "AXIS_HOST": "host",
        "AXIS_USERNAME": "username",
        "AXIS_PASSWORD": "password",
        "AXIS_PORT": "port",
        "AXIS_SSL_VERIFY": "ssl_verify",
        "AXIS_ADMIN_USERNAME": "username",
        "AXIS_ADMIN_PASSWORD": "password",
    }

    for env_var, config_key in env_mapping.items():
        value = os.environ.get(env_var)
        if value:
            if config_key == "port":
                config[config_key] = int(value)
            elif config_key == "ssl_verify":
                config[config_key] = value.lower() in ("true", "1", "yes")
            else:
                config[config_key] = value

    return config


@lru_cache(maxsize=1)
def load_config(config_path: Path | None = None) -> AppConfig:
    """Load application configuration from all sources.

    Configuration is loaded from:
    1. Default config file (if exists)
    2. Specified config file (if provided)
    3. Environment variables (override file settings)

    Args:
        config_path: Optional path to config file.

    Returns:
        Merged AppConfig instance.
    """
    # Start with empty config
    config_data: dict[str, Any] = {"devices": {}}

    # Load from default config file
    default_config_file = get_config_file()
    if default_config_file.exists():
        file_config = load_yaml_config(default_config_file)
        if file_config:
            config_data.update(file_config)

    # Load from specified config file
    if config_path and config_path.exists():
        file_config = load_yaml_config(config_path)
        if file_config:
            config_data.update(file_config)

    # Load environment config as a default device
    env_config = load_env_config()
    if env_config.get("host"):
        # Create a default device from environment
        config_data.setdefault("devices", {})
        config_data["devices"]["default"] = {
            "host": env_config.get("host", ""),
            "username": env_config.get("username", ""),
            "password": env_config.get("password", ""),
            "port": env_config.get("port", 443),
            "ssl_verify": env_config.get("ssl_verify", False),
        }
        config_data.setdefault("default_device", "default")

    return AppConfig.model_validate(config_data)


def get_device_config(
    device_name: str | None = None,
    config_path: Path | None = None,
) -> DeviceConfig | None:
    """Get configuration for a specific device.

    Args:
        device_name: Name of the device to get config for.
        config_path: Optional path to config file.

    Returns:
        DeviceConfig for the device, or None if not found.
    """
    app_config = load_config(config_path)

    # Use default device if no name specified
    name = device_name or app_config.default_device

    if not name:
        return None

    return app_config.devices.get(name)


def create_default_config() -> str:
    """Create a default configuration template.

    Returns:
        YAML string with example configuration.
    """
    return """# AXIS Camera Manager Configuration
# Place this file at ~/.config/axiscam/config.yaml

# Default device to use when not specified
default_device: front_door

# Request timeout in seconds
timeout: 30.0

# Device configurations
# Supports environment variable interpolation with ${VAR_NAME} syntax
# For credentials, use .env file or 1Password CLI (op)
devices:
  front_door:
    name: "Front Door Camera"
    vendor: axis
    model: M3216-LVE
    type: camera
    address: 192.168.1.10
    port: 443
    username: ${AXIS_ROOT_USER_NAME}
    password: ${AXIS_ROOT_USER_PASSWORD}
    ssl_verify: false

  back_yard:
    name: "Back Yard Camera"
    vendor: axis
    model: P3265-LVE
    type: camera
    address: 192.168.1.11
    port: 443
    username: ${AXIS_ROOT_USER_NAME}
    password: ${AXIS_ROOT_USER_PASSWORD}
    ssl_verify: false

  main_nvr:
    name: "Main NVR"
    vendor: axis
    model: S3016
    type: recorder
    address: 192.168.1.100
    port: 443
    username: ${AXIS_ROOT_USER_NAME}
    password: ${AXIS_ROOT_USER_PASSWORD}
    ssl_verify: false

  front_intercom:
    name: "Front Door Intercom"
    vendor: axis
    model: I8016-LVE
    type: intercom
    address: 192.168.1.12
    port: 443
    username: ${AXIS_ROOT_USER_NAME}
    password: ${AXIS_ROOT_USER_PASSWORD}
    ssl_verify: false

  office_speaker:
    name: "Office Speaker"
    vendor: axis
    model: C1310-E
    type: speaker
    address: 192.168.1.45
    port: 443
    username: ${AXIS_ROOT_USER_NAME}
    password: ${AXIS_ROOT_USER_PASSWORD}
    ssl_verify: false
"""
