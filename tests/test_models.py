"""Tests for Pydantic models."""

import pytest
from datetime import datetime

from axis_cam.models import (
    ApiResponse,
    AuthState,
    BasicDeviceInfo,
    DeviceCapabilities,
    DeviceParameter,
    DeviceProperties,
    DeviceStatus,
    DeviceType,
    DnsSettings,
    LogEntry,
    LogLevel,
    LogReport,
    LogType,
    NetworkInterface,
    NetworkSettings,
    NtpStatus,
    ParameterGroup,
    TimeInfo,
    TimeZoneSource,
)


class TestEnums:
    """Tests for enumeration types."""

    def test_device_type_values(self):
        """Test DeviceType enum values."""
        assert DeviceType.CAMERA.value == "camera"
        assert DeviceType.RECORDER.value == "recorder"
        assert DeviceType.INTERCOM.value == "intercom"
        assert DeviceType.SPEAKER.value == "speaker"
        assert DeviceType.UNKNOWN.value == "unknown"

    def test_log_level_values(self):
        """Test LogLevel enum values."""
        assert LogLevel.EMERGENCY.value == "emergency"
        assert LogLevel.ALERT.value == "alert"
        assert LogLevel.CRITICAL.value == "critical"
        assert LogLevel.ERROR.value == "error"
        assert LogLevel.WARNING.value == "warning"
        assert LogLevel.NOTICE.value == "notice"
        assert LogLevel.INFO.value == "info"
        assert LogLevel.DEBUG.value == "debug"

    def test_log_type_values(self):
        """Test LogType enum values."""
        assert LogType.SYSTEM.value == "system"
        assert LogType.ACCESS.value == "access"
        assert LogType.AUDIT.value == "audit"
        assert LogType.ALL.value == "all"

    def test_timezone_source_values(self):
        """Test TimeZoneSource enum values."""
        assert TimeZoneSource.DHCP.value == "dhcp"
        assert TimeZoneSource.IANA.value == "iana"
        assert TimeZoneSource.POSIX.value == "posix"

    def test_auth_state_values(self):
        """Test AuthState enum values."""
        assert AuthState.UNKNOWN.value == "unknown"
        assert AuthState.AUTHENTICATED.value == "authenticated"
        assert AuthState.AUTHENTICATING.value == "authenticating"
        assert AuthState.STOPPED.value == "stopped"
        assert AuthState.FAILED.value == "failed"


class TestBasicDeviceInfo:
    """Tests for BasicDeviceInfo model."""

    def test_create_with_defaults(self):
        """Test creating BasicDeviceInfo with defaults."""
        info = BasicDeviceInfo()
        assert info.product_full_name == ""
        assert info.serial_number == ""
        assert info.brand == "AXIS"

    def test_create_with_values(self):
        """Test creating BasicDeviceInfo with values."""
        info = BasicDeviceInfo(
            serial_number="ACCC12345678",
            product_number="M3216-LVE",
            firmware_version="11.5.64",
            brand="AXIS",
        )
        assert info.serial_number == "ACCC12345678"
        assert info.product_number == "M3216-LVE"
        assert info.firmware_version == "11.5.64"

    def test_create_with_aliases(self):
        """Test creating BasicDeviceInfo using field aliases."""
        info = BasicDeviceInfo.model_validate({
            "SerialNumber": "ACCC12345678",
            "ProdNbr": "M3216-LVE",
            "Version": "11.5.64",
            "Brand": "AXIS",
        })
        assert info.serial_number == "ACCC12345678"
        assert info.product_number == "M3216-LVE"
        assert info.firmware_version == "11.5.64"

    def test_model_is_frozen(self):
        """Test that BasicDeviceInfo is immutable."""
        info = BasicDeviceInfo(serial_number="ABC123")
        with pytest.raises(Exception):
            info.serial_number = "XYZ789"


class TestDeviceProperties:
    """Tests for DeviceProperties model."""

    def test_create_with_defaults(self):
        """Test creating DeviceProperties with defaults."""
        props = DeviceProperties()
        assert props.friendly_name == ""
        assert props.location == ""
        assert props.uptime == 0

    def test_create_with_values(self):
        """Test creating DeviceProperties with values."""
        props = DeviceProperties(
            friendly_name="Front Camera",
            location="Main Entrance",
            uptime=86400,
        )
        assert props.friendly_name == "Front Camera"
        assert props.location == "Main Entrance"
        assert props.uptime == 86400


class TestTimeInfo:
    """Tests for TimeInfo model."""

    def test_create_with_required_fields(self):
        """Test creating TimeInfo with required fields."""
        time_info = TimeInfo(
            utc_time=datetime(2024, 1, 15, 12, 0, 0),
        )
        assert time_info.utc_time == datetime(2024, 1, 15, 12, 0, 0)
        assert time_info.timezone_source == TimeZoneSource.IANA
        assert time_info.dst_enabled is True

    def test_create_with_all_fields(self):
        """Test creating TimeInfo with all fields."""
        time_info = TimeInfo(
            utc_time=datetime(2024, 1, 15, 12, 0, 0),
            local_time=datetime(2024, 1, 15, 13, 0, 0),
            timezone="Europe/Stockholm",
            timezone_source=TimeZoneSource.DHCP,
            posix_timezone="CET-1CEST",
            dst_enabled=False,
            max_supported_year=2050,
        )
        assert time_info.timezone == "Europe/Stockholm"
        assert time_info.timezone_source == TimeZoneSource.DHCP
        assert time_info.dst_enabled is False


class TestNtpStatus:
    """Tests for NtpStatus model."""

    def test_create_with_defaults(self):
        """Test creating NtpStatus with defaults."""
        ntp = NtpStatus()
        assert ntp.enabled is False
        assert ntp.server == ""
        assert ntp.synchronized is False
        assert ntp.last_sync is None

    def test_create_with_values(self):
        """Test creating NtpStatus with values."""
        sync_time = datetime.now()
        ntp = NtpStatus(
            enabled=True,
            server="pool.ntp.org",
            synchronized=True,
            last_sync=sync_time,
        )
        assert ntp.enabled is True
        assert ntp.server == "pool.ntp.org"
        assert ntp.synchronized is True
        assert ntp.last_sync == sync_time


class TestNetworkInterface:
    """Tests for NetworkInterface model."""

    def test_create_with_required_fields(self):
        """Test creating NetworkInterface with required name."""
        interface = NetworkInterface(name="eth0")
        assert interface.name == "eth0"
        assert interface.mac_address == ""
        assert interface.dhcp_enabled is True

    def test_create_with_all_fields(self):
        """Test creating NetworkInterface with all fields."""
        interface = NetworkInterface(
            name="eth0",
            mac_address="AA:BB:CC:DD:EE:FF",
            ip_address="192.168.1.10",
            subnet_mask="255.255.255.0",
            gateway="192.168.1.1",
            dhcp_enabled=False,
            ipv6_address="fe80::1",
        )
        assert interface.mac_address == "AA:BB:CC:DD:EE:FF"
        assert interface.dhcp_enabled is False


class TestDnsSettings:
    """Tests for DnsSettings model."""

    def test_create_with_defaults(self):
        """Test creating DnsSettings with defaults."""
        dns = DnsSettings()
        assert dns.primary == ""
        assert dns.secondary == ""
        assert dns.domain == ""

    def test_create_with_values(self):
        """Test creating DnsSettings with values."""
        dns = DnsSettings(
            primary="8.8.8.8",
            secondary="8.8.4.4",
            domain="example.com",
        )
        assert dns.primary == "8.8.8.8"
        assert dns.secondary == "8.8.4.4"


class TestNetworkSettings:
    """Tests for NetworkSettings model."""

    def test_create_with_defaults(self):
        """Test creating NetworkSettings with defaults."""
        settings = NetworkSettings()
        assert settings.hostname == ""
        assert settings.interfaces == []
        assert settings.bonjour_enabled is True
        assert settings.upnp_enabled is False

    def test_create_with_interfaces(self):
        """Test creating NetworkSettings with interfaces."""
        settings = NetworkSettings(
            hostname="axis-device",
            interfaces=[NetworkInterface(name="eth0")],
            dns=DnsSettings(primary="8.8.8.8"),
        )
        assert settings.hostname == "axis-device"
        assert len(settings.interfaces) == 1
        assert settings.dns.primary == "8.8.8.8"


class TestLogEntry:
    """Tests for LogEntry model."""

    def test_create_with_required_fields(self):
        """Test creating LogEntry with required fields."""
        entry = LogEntry(
            timestamp=datetime(2024, 1, 15, 12, 0, 0),
            message="Test message",
        )
        assert entry.timestamp == datetime(2024, 1, 15, 12, 0, 0)
        assert entry.message == "Test message"
        assert entry.level == LogLevel.INFO
        assert entry.hostname == ""

    def test_level_normalization_from_string(self):
        """Test that log level strings are normalized."""
        entry = LogEntry(
            timestamp=datetime.now(),
            message="Error occurred",
            level="err",
        )
        assert entry.level == LogLevel.ERROR

    def test_level_normalization_warning(self):
        """Test warning level normalization."""
        entry = LogEntry(
            timestamp=datetime.now(),
            message="Warning message",
            level="warn",
        )
        assert entry.level == LogLevel.WARNING

    def test_level_normalization_emerg(self):
        """Test emergency level normalization."""
        entry = LogEntry(
            timestamp=datetime.now(),
            message="Emergency",
            level="emerg",
        )
        assert entry.level == LogLevel.EMERGENCY

    def test_level_normalization_crit(self):
        """Test critical level normalization."""
        entry = LogEntry(
            timestamp=datetime.now(),
            message="Critical",
            level="crit",
        )
        assert entry.level == LogLevel.CRITICAL

    def test_level_normalization_unknown(self):
        """Test unknown level defaults to INFO."""
        entry = LogEntry(
            timestamp=datetime.now(),
            message="Unknown level",
            level="unknown_level",
        )
        assert entry.level == LogLevel.INFO

    def test_level_normalization_from_enum(self):
        """Test that LogLevel enum passes through."""
        entry = LogEntry(
            timestamp=datetime.now(),
            message="Debug message",
            level=LogLevel.DEBUG,
        )
        assert entry.level == LogLevel.DEBUG

    def test_level_normalization_non_string(self):
        """Test non-string level defaults to INFO."""
        entry = LogEntry(
            timestamp=datetime.now(),
            message="Test",
            level=123,
        )
        assert entry.level == LogLevel.INFO


class TestLogReport:
    """Tests for LogReport model."""

    def test_create_with_required_fields(self):
        """Test creating LogReport with required fields."""
        report = LogReport(
            device_name="test-device",
            device_address="192.168.1.10",
            log_type=LogType.SYSTEM,
        )
        assert report.device_name == "test-device"
        assert report.device_address == "192.168.1.10"
        assert report.log_type == LogType.SYSTEM
        assert report.entries == []
        assert report.total_entries == 0

    def test_total_entries_calculated(self):
        """Test that total_entries is calculated from entries."""
        entries = [
            LogEntry(timestamp=datetime.now(), message="msg1"),
            LogEntry(timestamp=datetime.now(), message="msg2"),
            LogEntry(timestamp=datetime.now(), message="msg3"),
        ]
        report = LogReport(
            device_name="test",
            device_address="192.168.1.10",
            log_type=LogType.SYSTEM,
            entries=entries,
        )
        assert report.total_entries == 3

    def test_total_entries_preserves_explicit_value(self):
        """Test that explicit total_entries is preserved."""
        report = LogReport(
            device_name="test",
            device_address="192.168.1.10",
            log_type=LogType.SYSTEM,
            entries=[LogEntry(timestamp=datetime.now(), message="msg")],
            total_entries=100,
        )
        assert report.total_entries == 100


class TestDeviceParameter:
    """Tests for DeviceParameter model."""

    def test_create_with_required_fields(self):
        """Test creating DeviceParameter with required fields."""
        param = DeviceParameter(name="Audio.MaxListeners", value="10")
        assert param.name == "Audio.MaxListeners"
        assert param.value == "10"
        assert param.group == ""
        assert param.writable is False

    def test_create_with_all_fields(self):
        """Test creating DeviceParameter with all fields."""
        param = DeviceParameter(
            name="Audio.MaxListeners",
            value="10",
            group="Audio",
            writable=True,
        )
        assert param.group == "Audio"
        assert param.writable is True


class TestParameterGroup:
    """Tests for ParameterGroup model."""

    def test_create_with_required_fields(self):
        """Test creating ParameterGroup with required fields."""
        group = ParameterGroup(name="Audio")
        assert group.name == "Audio"
        assert group.parameters == []

    def test_create_with_parameters(self):
        """Test creating ParameterGroup with parameters."""
        params = [
            DeviceParameter(name="Audio.MaxListeners", value="10"),
            DeviceParameter(name="Audio.Volume", value="80"),
        ]
        group = ParameterGroup(name="Audio", parameters=params)
        assert len(group.parameters) == 2


class TestApiResponse:
    """Tests for ApiResponse model."""

    def test_create_with_defaults(self):
        """Test creating ApiResponse with defaults."""
        response = ApiResponse()
        assert response.status == "success"
        assert response.data is None
        assert response.is_success is True

    def test_create_success_response(self):
        """Test creating a success response."""
        response = ApiResponse(status="success", data={"key": "value"})
        assert response.is_success is True
        assert response.data == {"key": "value"}

    def test_create_error_response(self):
        """Test creating an error response."""
        response = ApiResponse(
            status="error",
            error_code="AUTH_FAILED",
            error_message="Authentication failed",
        )
        assert response.is_success is False
        assert response.error_code == "AUTH_FAILED"


class TestDeviceStatus:
    """Tests for DeviceStatus model."""

    def test_create_with_defaults(self):
        """Test creating DeviceStatus with defaults."""
        status = DeviceStatus()
        assert status.reachable is False
        assert status.model == ""
        assert status.uptime_seconds is None

    def test_create_with_values(self):
        """Test creating DeviceStatus with values."""
        status = DeviceStatus(
            host="192.168.1.10",
            reachable=True,
            device_type=DeviceType.CAMERA,
            model="M3216-LVE",
            serial_number="ACCC12345678",
            firmware_version="11.5.64",
            uptime_seconds=86400,
        )
        assert status.reachable is True
        assert status.model == "M3216-LVE"
        assert status.uptime_seconds == 86400
        assert status.host == "192.168.1.10"
        assert status.device_type == DeviceType.CAMERA


class TestDeviceCapabilities:
    """Tests for DeviceCapabilities model."""

    def test_create_with_defaults(self):
        """Test creating DeviceCapabilities with defaults."""
        caps = DeviceCapabilities()
        assert caps.has_ptz is False
        assert caps.has_audio is False
        assert caps.has_analytics is False
        assert caps.supported_apis == []

    def test_create_with_values(self):
        """Test creating DeviceCapabilities with values."""
        caps = DeviceCapabilities(
            has_ptz=True,
            has_audio=True,
            has_speaker=True,
            has_microphone=True,
            has_io_ports=True,
            has_sd_card=True,
            has_analytics=True,
            supported_apis=["basic-device-info", "param", "time"],
        )
        assert caps.has_ptz is True
        assert caps.has_audio is True
        assert len(caps.supported_apis) == 3
