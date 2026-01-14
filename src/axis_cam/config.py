"""Configuration management for AXIS Camera Manager.

This module handles loading configuration from:
- Environment variables (AXIS_*)
- YAML configuration files
- XDG-compliant config paths
- .env files in config directory

Configuration precedence (highest to lowest):
1. Command-line arguments
2. Environment variables
3. .env file in config directory
4. User config file (~/.config/axiscam/config.yaml)
5. Legacy config file (~/.config/axis/config.yaml) - with warning
6. System defaults
"""

import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, SecretStr, field_validator

# Track if .env has been loaded
_env_loaded = False

# Application name for XDG paths
APP_NAME = "axiscam"

# Legacy application name (backward compatibility)
LEGACY_APP_NAME = "axis"

# Environment variable prefix
ENV_PREFIX = "AXIS_"

# Device type mappings from descriptive names to normalized types
DEVICE_TYPE_MAPPINGS: dict[str, str] = {
    # Direct types
    "camera": "camera",
    "recorder": "recorder",
    "intercom": "intercom",
    "speaker": "speaker",
    # Descriptive names
    "network camera": "camera",
    "dome camera": "camera",
    "bullet camera": "camera",
    "ptz camera": "camera",
    "thermal camera": "camera",
    "modular camera": "camera",
    "network video recorder": "recorder",
    "nvr": "recorder",
    "s3008": "recorder",
    "s3016": "recorder",
    "network video intercom": "intercom",
    "door station": "intercom",
    "network speaker": "speaker",
    "network mini speaker": "speaker",
    "horn speaker": "speaker",
    "network audio": "speaker",
}

# Track if legacy path warning has been shown
_legacy_path_warning_shown = False


def get_config_dir() -> Path:
    """Get the configuration directory path.

    Checks for config directory in order:
    1. AXIS_CONFIG_DIR environment variable
    2. XDG_CONFIG_HOME/axiscam/ or ~/.config/axiscam/ (preferred)
    3. XDG_CONFIG_HOME/axis/ or ~/.config/axis/ (legacy, with warning)

    Returns:
        Path to the configuration directory.
    """
    global _legacy_path_warning_shown

    # Check environment override first
    env_config_dir = os.environ.get("AXIS_CONFIG_DIR")
    if env_config_dir:
        return Path(env_config_dir)

    # Get XDG config home (default to ~/.config)
    xdg_config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

    # Check primary path
    primary_path = xdg_config_home / APP_NAME
    if primary_path.exists():
        return primary_path

    # Check legacy path
    legacy_path = xdg_config_home / LEGACY_APP_NAME
    if legacy_path.exists():
        # Show warning once, only in interactive mode
        if not _legacy_path_warning_shown and sys.stderr.isatty():
            sys.stderr.write(
                f"\033[33mWarning:\033[0m Using legacy config path: {legacy_path}\n"
                f"         Consider migrating to: {primary_path}\n"
                f"         Run 'axiscam config migrate' to migrate automatically.\n"
            )
            _legacy_path_warning_shown = True
        return legacy_path

    # Return primary path even if it doesn't exist
    return primary_path


def get_data_dir() -> Path:
    """Get the data directory path.

    Returns:
        Path to the data directory (XDG_DATA_HOME/axiscam or ~/.local/share/axiscam).
    """
    xdg_data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return xdg_data_home / APP_NAME


def get_config_file() -> Path:
    """Get the default config file path.

    Returns:
        Path to config.yaml file.
    """
    return get_config_dir() / "config.yaml"


def load_env_file() -> None:
    """Load .env file from config directory into environment.

    Loads variables from .env file if it exists, without overwriting
    existing environment variables.
    """
    global _env_loaded
    if _env_loaded:
        return

    env_file = get_config_dir() / ".env"
    if not env_file.exists():
        _env_loaded = True
        return

    try:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue
                # Parse KEY=VALUE format
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    # Remove surrounding quotes if present
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    # Only set if not already in environment
                    if key not in os.environ:
                        os.environ[key] = value
    except OSError:
        pass  # Silently ignore read errors

    _env_loaded = True


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
        """Validate and normalize device type.

        Accepts both direct types (camera, recorder, intercom, speaker)
        and descriptive names (Dome Camera, Network Video Intercom, etc.)
        """
        valid_types = {"camera", "recorder", "intercom", "speaker"}
        # Strip whitespace and remove any surrounding quotes (ASCII and Unicode)
        # ASCII quotes: " (U+0022), ' (U+0027)
        # Unicode quotes: " (U+201C), " (U+201D), ' (U+2018), ' (U+2019)
        quote_chars = '"\'""\u201c\u201d\u2018\u2019'
        v_clean = v.strip()
        for char in quote_chars:
            v_clean = v_clean.strip(char)
        v_clean = v_clean.lower()

        # Check if it's already a valid type
        if v_clean in valid_types:
            return v_clean

        # Check mappings for descriptive names
        normalized = DEVICE_TYPE_MAPPINGS.get(v_clean)
        if normalized:
            return normalized

        # Default to camera for unknown types (most common)
        return "camera"

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


def normalize_devices_format(config: dict[str, Any]) -> dict[str, Any]:
    """Normalize devices from list format to dict format.

    The legacy config uses a list format:
        devices:
          - name: 'Front_Camera'
            address: 192.168.1.10
            ...

    The new format uses a dict:
        devices:
          front_camera:
            address: 192.168.1.10
            ...

    This function converts list format to dict format.

    Args:
        config: Raw configuration dictionary.

    Returns:
        Configuration with devices as dict.
    """
    devices = config.get("devices", {})

    if isinstance(devices, list):
        # Convert list to dict using 'name' field as key
        devices_dict: dict[str, Any] = {}
        for device in devices:
            if isinstance(device, dict) and "name" in device:
                # Use name as key, normalize it for use as identifier
                name = device["name"]
                key = name.lower().replace(" ", "_").replace("-", "_")
                # Copy device config, keeping original name in 'name' field
                device_config = dict(device)
                devices_dict[key] = device_config
        config["devices"] = devices_dict

    return config


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

    # First interpolate env vars
    config = interpolate_env_vars(raw_config)

    # Then normalize devices format (list -> dict)
    config = normalize_devices_format(config)

    return config


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
    1. .env file from config directory
    2. Default config file (if exists)
    3. Specified config file (if provided)
    4. Environment variables (override file settings)

    Args:
        config_path: Optional path to config file.

    Returns:
        Merged AppConfig instance.
    """
    # Load .env file first so env vars are available for interpolation
    load_env_file()

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


def get_device_config_by_host(
    host: str,
    config_path: Path | None = None,
) -> DeviceConfig | None:
    """Get configuration for a device by its host/IP address.

    Args:
        host: Host address or IP to look up.
        config_path: Optional path to config file.

    Returns:
        DeviceConfig for the device, or None if not found.
    """
    app_config = load_config(config_path)

    for device in app_config.devices.values():
        if device.host == host:
            return device

    return None


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
