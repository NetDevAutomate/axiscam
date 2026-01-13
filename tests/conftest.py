"""Pytest fixtures for axis_cam tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from pathlib import Path
import tempfile
import os

from axis_cam.client import VapixClient
from axis_cam.models import (
    BasicDeviceInfo,
    DeviceCapabilities,
    DeviceStatus,
    DeviceType,
    LogEntry,
    LogLevel,
    LogReport,
    LogType,
    NtpStatus,
    TimeInfo,
    TimeZoneSource,
)


@pytest.fixture
def mock_device_info():
    """Create a mock BasicDeviceInfo instance."""
    return BasicDeviceInfo(
        serial_number="ACCC12345678",
        brand="AXIS",
        product_full_name="AXIS M3216-LVE Network Camera",
        product_number="M3216-LVE",
        firmware_version="11.5.64",
        hardware_id="ABC123",
        architecture="armv7hf",
        soc="ARTPEC-7",
        soc_serial_number="SN123456",
        web_url="https://192.168.1.10",
    )


@pytest.fixture
def mock_capabilities():
    """Create a mock DeviceCapabilities instance."""
    return DeviceCapabilities(
        available_apis={
            "basic-device-info": {"v2": {"state": "beta"}},
            "param": {"v2": {"state": "beta"}},
            "time": {"v2": {"state": "released"}},
            "log": {"v1": {"state": "beta"}},
            "video-analytics": {"v1": {"state": "beta"}},
        },
        ptz_supported=False,
        audio_supported=True,
        io_supported=True,
        analytics_supported=True,
    )


@pytest.fixture
def mock_time_info():
    """Create a mock TimeInfo instance."""
    return TimeInfo(
        utc_time=datetime(2024, 1, 15, 12, 0, 0),
        local_time=datetime(2024, 1, 15, 13, 0, 0),
        timezone="Europe/Stockholm",
        timezone_source=TimeZoneSource.IANA,
        posix_timezone="CET-1CEST,M3.5.0,M10.5.0/3",
        dst_enabled=True,
        max_supported_year=2037,
    )


@pytest.fixture
def mock_ntp_status():
    """Create a mock NtpStatus instance."""
    return NtpStatus(
        enabled=True,
        server="pool.ntp.org",
        synchronized=True,
    )


@pytest.fixture
def mock_log_entry():
    """Create a mock LogEntry instance."""
    return LogEntry(
        timestamp=datetime(2024, 1, 15, 12, 0, 0),
        hostname="axis-device",
        level=LogLevel.INFO,
        process="httpd",
        pid=1234,
        message="Test log message",
        raw="2024-01-15T12:00:00+00:00 axis-device [ INFO ] httpd[1234]: Test log message",
    )


@pytest.fixture
def mock_log_report(mock_log_entry):
    """Create a mock LogReport instance."""
    return LogReport(
        device_name="test-device",
        device_address="192.168.1.10",
        log_type=LogType.SYSTEM,
        entries=[mock_log_entry],
    )


@pytest.fixture
def mock_device_status():
    """Create a mock DeviceStatus instance."""
    return DeviceStatus(
        host="192.168.1.10",
        reachable=True,
        device_type=DeviceType.CAMERA,
        model="M3216-LVE",
        serial_number="ACCC12345678",
        firmware_version="11.5.64",
        uptime_seconds=86400,
        current_time=datetime(2024, 1, 15, 12, 0, 0),
    )


@pytest.fixture
def mock_http_client():
    """Create a mock httpx AsyncClient."""
    client = AsyncMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    return client


@pytest.fixture
def mock_vapix_client(mock_http_client):
    """Create a mock VapixClient."""
    client = MagicMock(spec=VapixClient)
    client.host = "192.168.1.10"
    client.get_json = AsyncMock()
    client.post_json = AsyncMock()
    client.get_raw = AsyncMock()
    client.discover_apis = AsyncMock()
    client.check_connectivity = AsyncMock(return_value=True)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@pytest.fixture
def temp_config_dir():
    """Create a temporary config directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_env_vars():
    """Set mock environment variables."""
    env_vars = {
        "AXIS_ADMIN_USERNAME": "testuser",
        "AXIS_ADMIN_PASSWORD": "testpass",
        "AXIS_HOST": "192.168.1.10",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


@pytest.fixture
def sample_config_yaml():
    """Sample YAML configuration content."""
    return """
default_device: camera1
timeout: 30.0
devices:
  camera1:
    host: 192.168.1.10
    username: admin
    password: password123
    port: 443
    ssl_verify: false
    device_type: camera
    name: "Front Camera"

  recorder:
    host: 192.168.1.100
    username: admin
    password: password123
    port: 443
    ssl_verify: false
    device_type: recorder
    name: "Main NVR"
"""


@pytest.fixture
def sample_server_report():
    """Sample server report content."""
    return """2024-01-15T12:00:00+00:00 axis-device [ INFO ] httpd[1234]: Connection from 192.168.1.1
2024-01-15T12:00:01+00:00 axis-device [ WARNING ] watchdog[100]: Process restarted
2024-01-15T12:00:02+00:00 axis-device [ ERR ] kernel: Out of memory
"""


@pytest.fixture
def sample_api_response():
    """Sample API discovery response."""
    return {
        "basic-device-info": {
            "v2": {
                "rest_api": "/config/rest/basic-device-info/v2beta",
                "state": "beta",
                "version": "2.0.0-beta.2"
            }
        },
        "param": {
            "v2": {
                "rest_api": "/config/rest/param/v2beta",
                "state": "beta",
                "version": "2.0.0-beta.1"
            }
        },
        "time": {
            "v2": {
                "rest_api": "/config/rest/time/v2",
                "state": "released",
                "version": "2.0.1"
            }
        }
    }
