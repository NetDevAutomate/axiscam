"""Tests for Pydantic models."""

from datetime import datetime

import pytest

from axis_cam.models import (
    ActionConfig,
    ActionRule,
    ActionTemplate,
    AnalyticsConfig,
    AnalyticsMqttBroker,
    AnalyticsMqttConfig,
    AnalyticsMqttSubscription,
    AnalyticsProfile,
    AnalyticsScenario,
    ApiResponse,
    AudioMulticastConfig,
    AudioStream,
    AuthState,
    BasicDeviceInfo,
    BestSnapshotConfig,
    CertConfig,
    Certificate,
    CertificateType,
    DeviceCapabilities,
    DeviceParameter,
    DeviceProperties,
    DeviceStatus,
    DeviceType,
    DnsSettings,
    FirewallAction,
    FirewallConfig,
    FirewallProtocol,
    FirewallRule,
    GeolocationConfig,
    LogEntry,
    LogLevel,
    LogReport,
    LogType,
    MqttBridgeConfig,
    MqttClient,
    MqttEventFilter,
    MulticastGroup,
    NetworkConfig,
    NetworkInterface,
    NetworkSettings,
    NtpConfig,
    NtpServer,
    NtpStatus,
    NtpSyncStatus,
    ObjectClass,
    ParameterGroup,
    ProxySettings,
    RecordingConfig,
    RecordingGroup,
    RecordingProfile,
    RemoteStorageConfig,
    ServerReport,
    ServerReportFormat,
    SnapshotProfile,
    SnapshotTrigger,
    SnmpConfig,
    SnmpTrapReceiver,
    SnmpVersion,
    SshConfig,
    SshKey,
    StorageDestination,
    StorageType,
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
        info = BasicDeviceInfo.model_validate(
            {
                "SerialNumber": "ACCC12345678",
                "ProdNbr": "M3216-LVE",
                "Version": "11.5.64",
                "Brand": "AXIS",
            }
        )
        assert info.serial_number == "ACCC12345678"
        assert info.product_number == "M3216-LVE"
        assert info.firmware_version == "11.5.64"

    def test_model_is_frozen(self):
        """Test that BasicDeviceInfo is immutable."""
        from pydantic import ValidationError

        info = BasicDeviceInfo(serial_number="ABC123")
        with pytest.raises(ValidationError):
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


# =============================================================================
# High Priority API Models Tests
# =============================================================================


class TestProxySettings:
    """Tests for ProxySettings model."""

    def test_create_with_defaults(self):
        """Test creating ProxySettings with defaults."""
        proxy = ProxySettings()
        assert proxy.enabled is False
        assert proxy.server == ""
        assert proxy.port == 8080
        assert proxy.username == ""
        assert proxy.exceptions == []

    def test_create_with_values(self):
        """Test creating ProxySettings with values."""
        proxy = ProxySettings(
            enabled=True,
            server="proxy.example.com",
            port=3128,
            username="user",
            exceptions=["localhost", "192.168.1.0/24"],
        )
        assert proxy.enabled is True
        assert proxy.server == "proxy.example.com"
        assert proxy.port == 3128
        assert len(proxy.exceptions) == 2


class TestNetworkConfig:
    """Tests for NetworkConfig model."""

    def test_create_with_defaults(self):
        """Test creating NetworkConfig with defaults."""
        config = NetworkConfig()
        assert config.hostname == ""
        assert config.interfaces == []
        assert config.global_proxy is None
        assert config.bonjour_enabled is True
        assert config.websocket_enabled is True

    def test_create_with_proxy(self):
        """Test creating NetworkConfig with proxy."""
        config = NetworkConfig(
            hostname="axis-device",
            global_proxy=ProxySettings(enabled=True, server="proxy.local"),
        )
        assert config.hostname == "axis-device"
        assert config.global_proxy is not None
        assert config.global_proxy.server == "proxy.local"


class TestFirewallEnums:
    """Tests for Firewall enumeration types."""

    def test_firewall_action_values(self):
        """Test FirewallAction enum values."""
        assert FirewallAction.ALLOW.value == "allow"
        assert FirewallAction.DENY.value == "deny"
        assert FirewallAction.DROP.value == "drop"
        assert FirewallAction.REJECT.value == "reject"

    def test_firewall_protocol_values(self):
        """Test FirewallProtocol enum values."""
        assert FirewallProtocol.ANY.value == "any"
        assert FirewallProtocol.TCP.value == "tcp"
        assert FirewallProtocol.UDP.value == "udp"
        assert FirewallProtocol.ICMP.value == "icmp"
        assert FirewallProtocol.ICMPV6.value == "icmpv6"


class TestFirewallRule:
    """Tests for FirewallRule model."""

    def test_create_with_defaults(self):
        """Test creating FirewallRule with defaults."""
        rule = FirewallRule()
        assert rule.action == FirewallAction.ALLOW
        assert rule.protocol == FirewallProtocol.ANY
        assert rule.source == ""
        assert rule.dest_port == ""
        assert rule.enabled is True

    def test_create_with_values(self):
        """Test creating FirewallRule with values."""
        rule = FirewallRule(
            action=FirewallAction.DENY,
            protocol=FirewallProtocol.TCP,
            source="192.168.1.0/24",
            dest_port="22",
            description="Block SSH from internal",
            enabled=True,
        )
        assert rule.action == FirewallAction.DENY
        assert rule.protocol == FirewallProtocol.TCP
        assert rule.source == "192.168.1.0/24"
        assert rule.dest_port == "22"


class TestFirewallConfig:
    """Tests for FirewallConfig model."""

    def test_create_with_defaults(self):
        """Test creating FirewallConfig with defaults."""
        config = FirewallConfig()
        assert config.enabled is False
        assert config.ipv4_rules == []
        assert config.ipv6_rules == []
        assert config.default_policy == FirewallAction.ALLOW
        assert config.icmp_allowed is True

    def test_create_with_rules(self):
        """Test creating FirewallConfig with rules."""
        rules = [
            FirewallRule(action=FirewallAction.ALLOW, dest_port="443"),
            FirewallRule(action=FirewallAction.DROP, protocol=FirewallProtocol.TCP),
        ]
        config = FirewallConfig(
            enabled=True,
            ipv4_rules=rules,
            default_policy=FirewallAction.DENY,
        )
        assert config.enabled is True
        assert len(config.ipv4_rules) == 2
        assert config.default_policy == FirewallAction.DENY


class TestSshKey:
    """Tests for SshKey model."""

    def test_create_with_defaults(self):
        """Test creating SshKey with defaults."""
        key = SshKey()
        assert key.key_type == ""
        assert key.key == ""
        assert key.comment == ""
        assert key.fingerprint == ""

    def test_create_with_values(self):
        """Test creating SshKey with values."""
        key = SshKey(
            key_type="ssh-ed25519",
            key="AAAAC3NzaC1lZDI1NTE5AAAA...",
            comment="admin@example.com",
            fingerprint="SHA256:abc123...",
        )
        assert key.key_type == "ssh-ed25519"
        assert key.comment == "admin@example.com"


class TestSshConfig:
    """Tests for SshConfig model."""

    def test_create_with_defaults(self):
        """Test creating SshConfig with defaults."""
        config = SshConfig()
        assert config.enabled is False
        assert config.port == 22
        assert config.root_login_allowed is False
        assert config.password_auth_enabled is True
        assert config.authorized_keys == []

    def test_create_with_values(self):
        """Test creating SshConfig with values."""
        config = SshConfig(
            enabled=True,
            port=2222,
            root_login_allowed=True,
            authorized_keys=[SshKey(key_type="ssh-rsa", comment="test")],
        )
        assert config.enabled is True
        assert config.port == 2222
        assert len(config.authorized_keys) == 1


class TestSnmpVersion:
    """Tests for SnmpVersion enum."""

    def test_snmp_version_values(self):
        """Test SnmpVersion enum values."""
        assert SnmpVersion.V1.value == "v1"
        assert SnmpVersion.V2C.value == "v2c"
        assert SnmpVersion.V3.value == "v3"


class TestSnmpTrapReceiver:
    """Tests for SnmpTrapReceiver model."""

    def test_create_with_defaults(self):
        """Test creating SnmpTrapReceiver with defaults."""
        receiver = SnmpTrapReceiver()
        assert receiver.address == ""
        assert receiver.port == 162
        assert receiver.community == ""
        assert receiver.enabled is True

    def test_create_with_values(self):
        """Test creating SnmpTrapReceiver with values."""
        receiver = SnmpTrapReceiver(
            address="192.168.1.100",
            port=1162,
            community="private",
            enabled=True,
        )
        assert receiver.address == "192.168.1.100"
        assert receiver.port == 1162
        assert receiver.community == "private"


class TestSnmpConfig:
    """Tests for SnmpConfig model."""

    def test_create_with_defaults(self):
        """Test creating SnmpConfig with defaults."""
        config = SnmpConfig()
        assert config.enabled is False
        assert config.version == SnmpVersion.V2C
        assert config.read_community == "public"
        assert config.write_community == ""
        assert config.trap_receivers == []
        assert config.v3_enabled is False

    def test_create_with_values(self):
        """Test creating SnmpConfig with values."""
        config = SnmpConfig(
            enabled=True,
            version=SnmpVersion.V3,
            read_community="public",
            system_contact="admin@example.com",
            system_location="Building A, Room 101",
            v3_enabled=True,
            v3_username="admin",
        )
        assert config.enabled is True
        assert config.version == SnmpVersion.V3
        assert config.system_location == "Building A, Room 101"


class TestCertificateType:
    """Tests for CertificateType enum."""

    def test_certificate_type_values(self):
        """Test CertificateType enum values."""
        assert CertificateType.SERVER.value == "server"
        assert CertificateType.CLIENT.value == "client"
        assert CertificateType.CA.value == "ca"


class TestCertificate:
    """Tests for Certificate model."""

    def test_create_with_defaults(self):
        """Test creating Certificate with defaults."""
        cert = Certificate()
        assert cert.cert_id == ""
        assert cert.cert_type == CertificateType.SERVER
        assert cert.subject == ""
        assert cert.issuer == ""
        assert cert.key_size == 0
        assert cert.self_signed is False

    def test_create_with_values(self):
        """Test creating Certificate with values."""
        cert = Certificate(
            cert_id="cert-001",
            cert_type=CertificateType.CA,
            subject="CN=Example CA",
            issuer="CN=Root CA",
            not_before="2024-01-01T00:00:00Z",
            not_after="2025-01-01T00:00:00Z",
            serial_number="1234567890",
            key_size=4096,
            key_type="RSA",
            self_signed=True,
        )
        assert cert.cert_id == "cert-001"
        assert cert.cert_type == CertificateType.CA
        assert cert.key_size == 4096
        assert cert.self_signed is True


class TestCertConfig:
    """Tests for CertConfig model."""

    def test_create_with_defaults(self):
        """Test creating CertConfig with defaults."""
        config = CertConfig()
        assert config.certificates == []
        assert config.ca_certificates == []
        assert config.active_certificate is None
        assert config.https_enabled is True
        assert config.https_only is False

    def test_create_with_certificates(self):
        """Test creating CertConfig with certificates."""
        server_cert = Certificate(cert_id="server-1", cert_type=CertificateType.SERVER)
        ca_cert = Certificate(cert_id="ca-1", cert_type=CertificateType.CA)
        config = CertConfig(
            certificates=[server_cert],
            ca_certificates=[ca_cert],
            active_certificate=server_cert,
            https_only=True,
        )
        assert len(config.certificates) == 1
        assert len(config.ca_certificates) == 1
        assert config.active_certificate == server_cert
        assert config.https_only is True


class TestNtpServer:
    """Tests for NtpServer model."""

    def test_create_with_defaults(self):
        """Test creating NtpServer with defaults."""
        server = NtpServer()
        assert server.address == ""
        assert server.enabled is True
        assert server.prefer is False
        assert server.source == "static"

    def test_create_with_values(self):
        """Test creating NtpServer with values."""
        server = NtpServer(
            address="pool.ntp.org",
            enabled=True,
            prefer=True,
            source="static",
        )
        assert server.address == "pool.ntp.org"
        assert server.prefer is True


class TestNtpSyncStatus:
    """Tests for NtpSyncStatus model."""

    def test_create_with_defaults(self):
        """Test creating NtpSyncStatus with defaults."""
        status = NtpSyncStatus()
        assert status.synchronized is False
        assert status.current_server == ""
        assert status.stratum == 0
        assert status.offset_ms == 0.0
        assert status.last_sync == ""

    def test_create_with_values(self):
        """Test creating NtpSyncStatus with values."""
        status = NtpSyncStatus(
            synchronized=True,
            current_server="pool.ntp.org",
            stratum=2,
            offset_ms=15.5,
            last_sync="2024-01-15T12:00:00Z",
        )
        assert status.synchronized is True
        assert status.stratum == 2
        assert status.offset_ms == 15.5


class TestNtpConfig:
    """Tests for NtpConfig model."""

    def test_create_with_defaults(self):
        """Test creating NtpConfig with defaults."""
        config = NtpConfig()
        assert config.enabled is False
        assert config.servers == []
        assert config.sync_status.synchronized is False
        assert config.use_dhcp_servers is False
        assert config.fallback_enabled is False

    def test_create_with_servers(self):
        """Test creating NtpConfig with servers."""
        servers = [
            NtpServer(address="pool.ntp.org", prefer=True),
            NtpServer(address="time.google.com"),
        ]
        config = NtpConfig(
            enabled=True,
            servers=servers,
            sync_status=NtpSyncStatus(synchronized=True, stratum=2),
            use_dhcp_servers=True,
        )
        assert config.enabled is True
        assert len(config.servers) == 2
        assert config.sync_status.synchronized is True


# =============================================================================
# Action Rules Models Tests
# =============================================================================


class TestActionRule:
    """Tests for ActionRule model."""

    def test_create_with_defaults(self):
        """Test creating ActionRule with defaults."""
        rule = ActionRule()
        assert rule.id == ""
        assert rule.name == ""
        assert rule.enabled is False
        assert rule.primary_condition == ""
        assert rule.conditions == []
        assert rule.actions == []

    def test_create_with_values(self):
        """Test creating ActionRule with values."""
        rule = ActionRule(
            id="rule1",
            name="Motion Detection Rule",
            enabled=True,
            primary_condition="motion",
            conditions=["time_schedule", "tamper"],
            actions=["send_notification", "start_recording"],
        )
        assert rule.id == "rule1"
        assert rule.name == "Motion Detection Rule"
        assert rule.enabled is True
        assert len(rule.conditions) == 2
        assert len(rule.actions) == 2


class TestActionTemplate:
    """Tests for ActionTemplate model."""

    def test_create_with_defaults(self):
        """Test creating ActionTemplate with defaults."""
        template = ActionTemplate()
        assert template.id == ""
        assert template.name == ""
        assert template.template_type == ""
        assert template.parameters == {}

    def test_create_with_values(self):
        """Test creating ActionTemplate with values."""
        template = ActionTemplate(
            id="template1",
            name="Email Notification",
            template_type="notification",
            parameters={"recipient": "admin@example.com", "subject": "Alert"},
        )
        assert template.id == "template1"
        assert template.template_type == "notification"
        assert "recipient" in template.parameters


class TestActionConfig:
    """Tests for ActionConfig model."""

    def test_create_with_defaults(self):
        """Test creating ActionConfig with defaults."""
        config = ActionConfig()
        assert config.rules == []
        assert config.templates == []

    def test_create_with_rules(self):
        """Test creating ActionConfig with rules."""
        rules = [ActionRule(id="rule1", name="Test Rule", enabled=True)]
        templates = [ActionTemplate(id="tmpl1", name="Test Template")]
        config = ActionConfig(rules=rules, templates=templates)
        assert len(config.rules) == 1
        assert len(config.templates) == 1


# =============================================================================
# MQTT Bridge Models Tests
# =============================================================================


class TestMqttClient:
    """Tests for MqttClient model."""

    def test_create_with_defaults(self):
        """Test creating MqttClient with defaults."""
        client = MqttClient()
        assert client.id == ""
        assert client.host == ""
        assert client.port == 1883
        assert client.protocol == "tcp"
        assert client.username == ""
        assert client.client_id == ""
        assert client.keep_alive == 60
        assert client.clean_session is True
        assert client.use_tls is False

    def test_create_with_values(self):
        """Test creating MqttClient with values."""
        client = MqttClient(
            id="mqtt1",
            host="mqtt.example.com",
            port=8883,
            protocol="ssl",
            username="axis_user",
            client_id="axis-camera-001",
            keep_alive=30,
            clean_session=False,
            use_tls=True,
        )
        assert client.host == "mqtt.example.com"
        assert client.port == 8883
        assert client.use_tls is True


class TestMqttEventFilter:
    """Tests for MqttEventFilter model."""

    def test_create_with_defaults(self):
        """Test creating MqttEventFilter with defaults."""
        filter = MqttEventFilter()
        assert filter.id == ""
        assert filter.name == ""
        assert filter.enabled is True
        assert filter.topic == ""
        assert filter.event_types == []
        assert filter.qos == 0
        assert filter.retain is False

    def test_create_with_values(self):
        """Test creating MqttEventFilter with values."""
        filter = MqttEventFilter(
            id="filter1",
            name="Motion Events",
            enabled=True,
            topic="axis/events/motion",
            event_types=["motion", "tamper"],
            qos=1,
            retain=True,
        )
        assert filter.topic == "axis/events/motion"
        assert filter.qos == 1
        assert len(filter.event_types) == 2

    def test_qos_validation(self):
        """Test QoS field validation."""
        # Valid QoS values
        for qos_val in [0, 1, 2]:
            filter = MqttEventFilter(qos=qos_val)
            assert filter.qos == qos_val

        # Invalid QoS value
        with pytest.raises(ValueError):
            MqttEventFilter(qos=3)


class TestMqttBridgeConfig:
    """Tests for MqttBridgeConfig model."""

    def test_create_with_defaults(self):
        """Test creating MqttBridgeConfig with defaults."""
        config = MqttBridgeConfig()
        assert config.enabled is False
        assert config.connected is False
        assert config.clients == []
        assert config.event_filters == []

    def test_create_with_values(self):
        """Test creating MqttBridgeConfig with values."""
        clients = [MqttClient(id="c1", host="mqtt.example.com")]
        filters = [MqttEventFilter(id="f1", topic="events")]
        config = MqttBridgeConfig(
            enabled=True,
            connected=True,
            clients=clients,
            event_filters=filters,
        )
        assert config.enabled is True
        assert config.connected is True
        assert len(config.clients) == 1
        assert len(config.event_filters) == 1


# =============================================================================
# Recording Models Tests
# =============================================================================


class TestRecordingProfile:
    """Tests for RecordingProfile model."""

    def test_create_with_defaults(self):
        """Test creating RecordingProfile with defaults."""
        profile = RecordingProfile()
        assert profile.id == ""
        assert profile.name == ""
        assert profile.format == "mkv"
        assert profile.video_codec == "h264"
        assert profile.audio_enabled is False
        assert profile.resolution == ""
        assert profile.framerate == 0
        assert profile.bitrate == 0

    def test_create_with_values(self):
        """Test creating RecordingProfile with values."""
        profile = RecordingProfile(
            id="profile1",
            name="High Quality",
            format="mp4",
            video_codec="h265",
            audio_enabled=True,
            resolution="1920x1080",
            framerate=30,
            bitrate=8000,
        )
        assert profile.format == "mp4"
        assert profile.video_codec == "h265"
        assert profile.audio_enabled is True
        assert profile.bitrate == 8000


class TestRecordingGroup:
    """Tests for RecordingGroup model."""

    def test_create_with_defaults(self):
        """Test creating RecordingGroup with defaults."""
        group = RecordingGroup()
        assert group.id == ""
        assert group.name == ""
        assert group.description == ""
        assert group.storage_id == ""
        assert group.retention_days == 0
        assert group.max_size_mb == 0
        assert group.profile_id == ""

    def test_create_with_values(self):
        """Test creating RecordingGroup with values."""
        group = RecordingGroup(
            id="group1",
            name="Continuous Recording",
            description="24/7 recording group",
            storage_id="storage1",
            retention_days=30,
            max_size_mb=100000,
            profile_id="profile1",
        )
        assert group.name == "Continuous Recording"
        assert group.retention_days == 30
        assert group.max_size_mb == 100000


class TestRecordingConfig:
    """Tests for RecordingConfig model."""

    def test_create_with_defaults(self):
        """Test creating RecordingConfig with defaults."""
        config = RecordingConfig()
        assert config.groups == []
        assert config.profiles == []

    def test_create_with_groups_and_profiles(self):
        """Test creating RecordingConfig with groups and profiles."""
        groups = [RecordingGroup(id="g1", name="Group 1")]
        profiles = [RecordingProfile(id="p1", name="Profile 1")]
        config = RecordingConfig(groups=groups, profiles=profiles)
        assert len(config.groups) == 1
        assert len(config.profiles) == 1


# =============================================================================
# Remote Storage Models Tests
# =============================================================================


class TestStorageType:
    """Tests for StorageType enum."""

    def test_storage_type_values(self):
        """Test StorageType enum values."""
        assert StorageType.S3.value == "s3"
        assert StorageType.AZURE.value == "azure"
        assert StorageType.GCS.value == "gcs"
        assert StorageType.SFTP.value == "sftp"
        assert StorageType.FTP.value == "ftp"
        assert StorageType.SMB.value == "smb"
        assert StorageType.NFS.value == "nfs"


class TestStorageDestination:
    """Tests for StorageDestination model."""

    def test_create_with_defaults(self):
        """Test creating StorageDestination with defaults."""
        dest = StorageDestination()
        assert dest.id == ""
        assert dest.name == ""
        assert dest.storage_type == StorageType.S3
        assert dest.endpoint == ""
        assert dest.bucket == ""
        assert dest.region == ""
        assert dest.access_key_id == ""
        assert dest.prefix == ""
        assert dest.enabled is False

    def test_create_with_values(self):
        """Test creating StorageDestination with values."""
        dest = StorageDestination(
            id="dest1",
            name="AWS S3 Bucket",
            storage_type=StorageType.S3,
            endpoint="s3.amazonaws.com",
            bucket="camera-recordings",
            region="us-east-1",
            access_key_id="AKIAXXXXXXXX",
            prefix="cameras/office/",
            enabled=True,
        )
        assert dest.name == "AWS S3 Bucket"
        assert dest.storage_type == StorageType.S3
        assert dest.bucket == "camera-recordings"
        assert dest.enabled is True

    def test_create_azure_storage(self):
        """Test creating Azure storage destination."""
        dest = StorageDestination(
            id="azure1",
            name="Azure Blob",
            storage_type=StorageType.AZURE,
            bucket="camera-container",
        )
        assert dest.storage_type == StorageType.AZURE


class TestRemoteStorageConfig:
    """Tests for RemoteStorageConfig model."""

    def test_create_with_defaults(self):
        """Test creating RemoteStorageConfig with defaults."""
        config = RemoteStorageConfig()
        assert config.destinations == []

    def test_create_with_destinations(self):
        """Test creating RemoteStorageConfig with destinations."""
        destinations = [
            StorageDestination(id="d1", name="Primary"),
            StorageDestination(id="d2", name="Backup"),
        ]
        config = RemoteStorageConfig(destinations=destinations)
        assert len(config.destinations) == 2


# =============================================================================
# Geolocation Models Tests
# =============================================================================


class TestGeolocationConfig:
    """Tests for GeolocationConfig model."""

    def test_create_with_defaults(self):
        """Test creating GeolocationConfig with defaults."""
        geo = GeolocationConfig()
        assert geo.latitude is None
        assert geo.longitude is None
        assert geo.altitude is None
        assert geo.direction is None
        assert geo.horizontal_accuracy is None
        assert geo.vertical_accuracy is None
        assert geo.heading is None
        assert geo.speed is None
        assert geo.timestamp is None

    def test_create_with_values(self):
        """Test creating GeolocationConfig with values."""
        geo = GeolocationConfig(
            latitude=37.7749,
            longitude=-122.4194,
            altitude=50.0,
            direction=180.0,
            horizontal_accuracy=5.0,
            vertical_accuracy=10.0,
            heading=90.0,
            speed=0.0,
            timestamp="2024-01-15T12:00:00Z",
        )
        assert geo.latitude == 37.7749
        assert geo.longitude == -122.4194
        assert geo.altitude == 50.0
        assert geo.direction == 180.0

    def test_direction_validation(self):
        """Test direction field validation (0-360)."""
        # Valid values
        geo = GeolocationConfig(direction=0.0)
        assert geo.direction == 0.0
        geo = GeolocationConfig(direction=360.0)
        assert geo.direction == 360.0

        # Invalid value - above 360
        with pytest.raises(ValueError):
            GeolocationConfig(direction=361.0)

    def test_heading_validation(self):
        """Test heading field validation (0-360)."""
        # Valid values
        geo = GeolocationConfig(heading=0.0)
        assert geo.heading == 0.0
        geo = GeolocationConfig(heading=180.0)
        assert geo.heading == 180.0

        # Invalid value
        with pytest.raises(ValueError):
            GeolocationConfig(heading=-1.0)

    def test_speed_validation(self):
        """Test speed field validation (>= 0)."""
        # Valid values
        geo = GeolocationConfig(speed=0.0)
        assert geo.speed == 0.0
        geo = GeolocationConfig(speed=100.0)
        assert geo.speed == 100.0

        # Invalid value - negative
        with pytest.raises(ValueError):
            GeolocationConfig(speed=-1.0)


# =============================================================================
# Video Analytics Models Tests
# =============================================================================


class TestObjectClass:
    """Tests for ObjectClass model."""

    def test_create_with_defaults(self):
        """Test creating ObjectClass with defaults."""
        obj_class = ObjectClass()
        assert obj_class.id == ""
        assert obj_class.name == ""
        assert obj_class.enabled is True
        assert obj_class.confidence_threshold == 50
        assert obj_class.color == ""

    def test_create_with_values(self):
        """Test creating ObjectClass with values."""
        obj_class = ObjectClass(
            id="human",
            name="Human",
            enabled=True,
            confidence_threshold=75,
            color="#FF0000",
        )
        assert obj_class.id == "human"
        assert obj_class.name == "Human"
        assert obj_class.confidence_threshold == 75

    def test_confidence_threshold_validation(self):
        """Test confidence_threshold field validation (0-100)."""
        # Valid values
        obj_class = ObjectClass(confidence_threshold=0)
        assert obj_class.confidence_threshold == 0
        obj_class = ObjectClass(confidence_threshold=100)
        assert obj_class.confidence_threshold == 100

        # Invalid values
        with pytest.raises(ValueError):
            ObjectClass(confidence_threshold=-1)
        with pytest.raises(ValueError):
            ObjectClass(confidence_threshold=101)


class TestAnalyticsScenario:
    """Tests for AnalyticsScenario model."""

    def test_create_with_defaults(self):
        """Test creating AnalyticsScenario with defaults."""
        scenario = AnalyticsScenario()
        assert scenario.id == ""
        assert scenario.name == ""
        assert scenario.scenario_type == ""
        assert scenario.enabled is False
        assert scenario.object_classes == []
        assert scenario.trigger_on_enter is True
        assert scenario.trigger_on_exit is False
        assert scenario.trigger_on_presence is False
        assert scenario.dwell_time == 0
        assert scenario.region == {}

    def test_create_with_values(self):
        """Test creating AnalyticsScenario with values."""
        scenario = AnalyticsScenario(
            id="scenario1",
            name="Entry Zone",
            scenario_type="intrusion",
            enabled=True,
            object_classes=["human", "vehicle"],
            trigger_on_enter=True,
            trigger_on_exit=True,
            dwell_time=5,
            region={"type": "polygon", "points": [[0, 0], [100, 0], [100, 100]]},
        )
        assert scenario.name == "Entry Zone"
        assert scenario.scenario_type == "intrusion"
        assert len(scenario.object_classes) == 2
        assert scenario.dwell_time == 5

    def test_dwell_time_validation(self):
        """Test dwell_time field validation (>= 0)."""
        # Valid value
        scenario = AnalyticsScenario(dwell_time=0)
        assert scenario.dwell_time == 0

        # Invalid value
        with pytest.raises(ValueError):
            AnalyticsScenario(dwell_time=-1)


class TestAnalyticsProfile:
    """Tests for AnalyticsProfile model."""

    def test_create_with_defaults(self):
        """Test creating AnalyticsProfile with defaults."""
        profile = AnalyticsProfile()
        assert profile.id == ""
        assert profile.name == ""
        assert profile.enabled is False
        assert profile.camera_id == ""
        assert profile.scenarios == []
        assert profile.sensitivity == 50
        assert profile.min_object_size == 0
        assert profile.max_object_size == 100

    def test_create_with_values(self):
        """Test creating AnalyticsProfile with values."""
        profile = AnalyticsProfile(
            id="profile1",
            name="Main Entrance Analytics",
            enabled=True,
            camera_id="camera1",
            scenarios=["scenario1", "scenario2"],
            sensitivity=70,
            min_object_size=5,
            max_object_size=95,
        )
        assert profile.name == "Main Entrance Analytics"
        assert profile.sensitivity == 70
        assert len(profile.scenarios) == 2

    def test_sensitivity_validation(self):
        """Test sensitivity field validation (0-100)."""
        # Valid values
        profile = AnalyticsProfile(sensitivity=0)
        assert profile.sensitivity == 0
        profile = AnalyticsProfile(sensitivity=100)
        assert profile.sensitivity == 100

        # Invalid values
        with pytest.raises(ValueError):
            AnalyticsProfile(sensitivity=-1)
        with pytest.raises(ValueError):
            AnalyticsProfile(sensitivity=101)

    def test_object_size_validation(self):
        """Test min/max object size validation (0-100)."""
        # Valid values
        profile = AnalyticsProfile(min_object_size=0, max_object_size=100)
        assert profile.min_object_size == 0
        assert profile.max_object_size == 100

        # Invalid values
        with pytest.raises(ValueError):
            AnalyticsProfile(min_object_size=-1)
        with pytest.raises(ValueError):
            AnalyticsProfile(max_object_size=101)


class TestAnalyticsConfig:
    """Tests for AnalyticsConfig model."""

    def test_create_with_defaults(self):
        """Test creating AnalyticsConfig with defaults."""
        config = AnalyticsConfig()
        assert config.enabled is False
        assert config.profiles == []
        assert config.scenarios == []
        assert config.object_classes == []
        assert config.metadata_enabled is False
        assert config.overlay_enabled is False

    def test_create_with_values(self):
        """Test creating AnalyticsConfig with values."""
        profiles = [AnalyticsProfile(id="p1", name="Profile 1")]
        scenarios = [AnalyticsScenario(id="s1", name="Scenario 1")]
        object_classes = [ObjectClass(id="human", name="Human")]

        config = AnalyticsConfig(
            enabled=True,
            profiles=profiles,
            scenarios=scenarios,
            object_classes=object_classes,
            metadata_enabled=True,
            overlay_enabled=True,
        )
        assert config.enabled is True
        assert len(config.profiles) == 1
        assert len(config.scenarios) == 1
        assert len(config.object_classes) == 1
        assert config.metadata_enabled is True


# =============================================================================
# Best Snapshot Models Tests
# =============================================================================


class TestSnapshotProfile:
    """Tests for SnapshotProfile model."""

    def test_create_with_defaults(self):
        """Test creating SnapshotProfile with defaults."""
        profile = SnapshotProfile()
        assert profile.id == ""
        assert profile.name == ""
        assert profile.enabled is True
        assert profile.resolution == ""
        assert profile.compression == 25
        assert profile.rotation == 0
        assert profile.mirror is False
        assert profile.overlay_enabled is False
        assert profile.timestamp_enabled is True

    def test_create_with_values(self):
        """Test creating SnapshotProfile with values."""
        profile = SnapshotProfile(
            id="profile1",
            name="High Quality Snapshot",
            enabled=True,
            resolution="1920x1080",
            compression=10,
            rotation=90,
            mirror=True,
            overlay_enabled=True,
        )
        assert profile.name == "High Quality Snapshot"
        assert profile.resolution == "1920x1080"
        assert profile.compression == 10
        assert profile.rotation == 90

    def test_compression_validation(self):
        """Test compression field validation (0-100)."""
        # Valid values
        profile = SnapshotProfile(compression=0)
        assert profile.compression == 0
        profile = SnapshotProfile(compression=100)
        assert profile.compression == 100

        # Invalid values
        with pytest.raises(ValueError):
            SnapshotProfile(compression=-1)
        with pytest.raises(ValueError):
            SnapshotProfile(compression=101)

    def test_rotation_validation(self):
        """Test rotation field validation (0-360)."""
        # Valid values
        profile = SnapshotProfile(rotation=0)
        assert profile.rotation == 0
        profile = SnapshotProfile(rotation=360)
        assert profile.rotation == 360

        # Invalid values
        with pytest.raises(ValueError):
            SnapshotProfile(rotation=-1)
        with pytest.raises(ValueError):
            SnapshotProfile(rotation=361)


class TestSnapshotTrigger:
    """Tests for SnapshotTrigger model."""

    def test_create_with_defaults(self):
        """Test creating SnapshotTrigger with defaults."""
        trigger = SnapshotTrigger()
        assert trigger.id == ""
        assert trigger.name == ""
        assert trigger.enabled is True
        assert trigger.trigger_type == ""
        assert trigger.profile_id == ""
        assert trigger.pre_trigger_time == 0
        assert trigger.post_trigger_time == 0
        assert trigger.event_filter == ""

    def test_create_with_values(self):
        """Test creating SnapshotTrigger with values."""
        trigger = SnapshotTrigger(
            id="trigger1",
            name="Motion Snapshot",
            enabled=True,
            trigger_type="motion",
            profile_id="profile1",
            pre_trigger_time=2,
            post_trigger_time=5,
            event_filter="area=zone1",
        )
        assert trigger.name == "Motion Snapshot"
        assert trigger.trigger_type == "motion"
        assert trigger.pre_trigger_time == 2
        assert trigger.post_trigger_time == 5

    def test_trigger_time_validation(self):
        """Test pre/post trigger time validation (>= 0)."""
        # Valid values
        trigger = SnapshotTrigger(pre_trigger_time=0, post_trigger_time=0)
        assert trigger.pre_trigger_time == 0
        assert trigger.post_trigger_time == 0

        # Invalid values
        with pytest.raises(ValueError):
            SnapshotTrigger(pre_trigger_time=-1)
        with pytest.raises(ValueError):
            SnapshotTrigger(post_trigger_time=-1)


class TestBestSnapshotConfig:
    """Tests for BestSnapshotConfig model."""

    def test_create_with_defaults(self):
        """Test creating BestSnapshotConfig with defaults."""
        config = BestSnapshotConfig()
        assert config.enabled is True
        assert config.profiles == []
        assert config.triggers == []
        assert config.default_resolution == ""
        assert config.default_compression == 25
        assert config.max_snapshots_per_event == 1

    def test_create_with_values(self):
        """Test creating BestSnapshotConfig with values."""
        profiles = [SnapshotProfile(id="p1", name="Profile 1")]
        triggers = [SnapshotTrigger(id="t1", name="Trigger 1")]

        config = BestSnapshotConfig(
            enabled=True,
            profiles=profiles,
            triggers=triggers,
            default_resolution="1280x720",
            default_compression=50,
            max_snapshots_per_event=5,
        )
        assert len(config.profiles) == 1
        assert len(config.triggers) == 1
        assert config.default_resolution == "1280x720"
        assert config.max_snapshots_per_event == 5

    def test_max_snapshots_validation(self):
        """Test max_snapshots_per_event validation (>= 1)."""
        # Valid value
        config = BestSnapshotConfig(max_snapshots_per_event=1)
        assert config.max_snapshots_per_event == 1

        # Invalid value
        with pytest.raises(ValueError):
            BestSnapshotConfig(max_snapshots_per_event=0)


# =============================================================================
# Analytics MQTT Models Tests
# =============================================================================


class TestAnalyticsMqttBroker:
    """Tests for AnalyticsMqttBroker model."""

    def test_create_with_defaults(self):
        """Test creating AnalyticsMqttBroker with defaults."""
        broker = AnalyticsMqttBroker()
        assert broker.host == ""
        assert broker.port == 1883
        assert broker.protocol == "tcp"
        assert broker.username == ""
        assert broker.client_id == ""
        assert broker.use_tls is False
        assert broker.ca_certificate == ""
        assert broker.validate_server_cert is True

    def test_create_with_values(self):
        """Test creating AnalyticsMqttBroker with values."""
        broker = AnalyticsMqttBroker(
            host="mqtt.example.com",
            port=8883,
            protocol="ssl",
            username="analytics_user",
            client_id="axis-analytics-001",
            use_tls=True,
            validate_server_cert=True,
        )
        assert broker.host == "mqtt.example.com"
        assert broker.port == 8883
        assert broker.use_tls is True


class TestAnalyticsMqttSubscription:
    """Tests for AnalyticsMqttSubscription model."""

    def test_create_with_defaults(self):
        """Test creating AnalyticsMqttSubscription with defaults."""
        sub = AnalyticsMqttSubscription()
        assert sub.id == ""
        assert sub.name == ""
        assert sub.enabled is True
        assert sub.topic == ""
        assert sub.qos == 0
        assert sub.retain is False
        assert sub.analytics_types == []
        assert sub.object_classes == []
        assert sub.include_image is False
        assert sub.image_resolution == ""

    def test_create_with_values(self):
        """Test creating AnalyticsMqttSubscription with values."""
        sub = AnalyticsMqttSubscription(
            id="sub1",
            name="Object Detection Events",
            enabled=True,
            topic="axis/analytics/objects",
            qos=1,
            retain=True,
            analytics_types=["object_detection", "loitering"],
            object_classes=["human", "vehicle"],
            include_image=True,
            image_resolution="640x480",
        )
        assert sub.name == "Object Detection Events"
        assert sub.topic == "axis/analytics/objects"
        assert sub.qos == 1
        assert len(sub.analytics_types) == 2
        assert sub.include_image is True

    def test_qos_validation(self):
        """Test QoS field validation (0-2)."""
        # Valid values
        for qos_val in [0, 1, 2]:
            sub = AnalyticsMqttSubscription(qos=qos_val)
            assert sub.qos == qos_val

        # Invalid value
        with pytest.raises(ValueError):
            AnalyticsMqttSubscription(qos=3)


class TestAnalyticsMqttConfig:
    """Tests for AnalyticsMqttConfig model."""

    def test_create_with_defaults(self):
        """Test creating AnalyticsMqttConfig with defaults."""
        config = AnalyticsMqttConfig()
        assert config.enabled is False
        assert config.connected is False
        assert config.broker is None
        assert config.subscriptions == []
        assert config.include_timestamps is True
        assert config.include_coordinates is True

    def test_create_with_values(self):
        """Test creating AnalyticsMqttConfig with values."""
        broker = AnalyticsMqttBroker(host="mqtt.example.com")
        subscriptions = [AnalyticsMqttSubscription(id="sub1", topic="axis/events")]

        config = AnalyticsMqttConfig(
            enabled=True,
            connected=True,
            broker=broker,
            subscriptions=subscriptions,
            include_timestamps=True,
            include_coordinates=False,
        )
        assert config.enabled is True
        assert config.connected is True
        assert config.broker.host == "mqtt.example.com"
        assert len(config.subscriptions) == 1
        assert config.include_coordinates is False


# =============================================================================
# Audio Multicast Models Tests
# =============================================================================


class TestAudioStream:
    """Tests for AudioStream model."""

    def test_create_with_defaults(self):
        """Test creating AudioStream with defaults."""
        stream = AudioStream()
        assert stream.id == ""
        assert stream.name == ""
        assert stream.enabled is False
        assert stream.codec == ""
        assert stream.sample_rate == 16000
        assert stream.bitrate == 64000
        assert stream.channels == 1
        assert stream.source == ""

    def test_create_with_values(self):
        """Test creating AudioStream with values."""
        stream = AudioStream(
            id="stream1",
            name="Main Audio",
            enabled=True,
            codec="aac",
            sample_rate=48000,
            bitrate=128000,
            channels=2,
            source="mic1",
        )
        assert stream.name == "Main Audio"
        assert stream.codec == "aac"
        assert stream.sample_rate == 48000
        assert stream.channels == 2

    def test_sample_rate_validation(self):
        """Test sample_rate field validation (>= 8000)."""
        # Valid value
        stream = AudioStream(sample_rate=8000)
        assert stream.sample_rate == 8000

        # Invalid value
        with pytest.raises(ValueError):
            AudioStream(sample_rate=7999)

    def test_bitrate_validation(self):
        """Test bitrate field validation (>= 8000)."""
        # Valid value
        stream = AudioStream(bitrate=8000)
        assert stream.bitrate == 8000

        # Invalid value
        with pytest.raises(ValueError):
            AudioStream(bitrate=7999)

    def test_channels_validation(self):
        """Test channels field validation (1-8)."""
        # Valid values
        stream = AudioStream(channels=1)
        assert stream.channels == 1
        stream = AudioStream(channels=8)
        assert stream.channels == 8

        # Invalid values
        with pytest.raises(ValueError):
            AudioStream(channels=0)
        with pytest.raises(ValueError):
            AudioStream(channels=9)


class TestMulticastGroup:
    """Tests for MulticastGroup model."""

    def test_create_with_defaults(self):
        """Test creating MulticastGroup with defaults."""
        group = MulticastGroup()
        assert group.id == ""
        assert group.name == ""
        assert group.enabled is False
        assert group.address == ""
        assert group.port == 0
        assert group.ttl == 64
        assert group.stream_id == ""

    def test_create_with_values(self):
        """Test creating MulticastGroup with values."""
        group = MulticastGroup(
            id="group1",
            name="Audio Broadcast",
            enabled=True,
            address="239.0.0.1",
            port=5004,
            ttl=128,
            stream_id="stream1",
        )
        assert group.name == "Audio Broadcast"
        assert group.address == "239.0.0.1"
        assert group.port == 5004
        assert group.ttl == 128

    def test_port_validation(self):
        """Test port field validation (0-65535)."""
        # Valid values
        group = MulticastGroup(port=0)
        assert group.port == 0
        group = MulticastGroup(port=65535)
        assert group.port == 65535

        # Invalid values
        with pytest.raises(ValueError):
            MulticastGroup(port=-1)
        with pytest.raises(ValueError):
            MulticastGroup(port=65536)

    def test_ttl_validation(self):
        """Test TTL field validation (1-255)."""
        # Valid values
        group = MulticastGroup(ttl=1)
        assert group.ttl == 1
        group = MulticastGroup(ttl=255)
        assert group.ttl == 255

        # Invalid values
        with pytest.raises(ValueError):
            MulticastGroup(ttl=0)
        with pytest.raises(ValueError):
            MulticastGroup(ttl=256)


class TestAudioMulticastConfig:
    """Tests for AudioMulticastConfig model."""

    def test_create_with_defaults(self):
        """Test creating AudioMulticastConfig with defaults."""
        config = AudioMulticastConfig()
        assert config.enabled is False
        assert config.groups == []
        assert config.streams == []
        assert config.default_ttl == 64
        assert config.audio_source == ""

    def test_create_with_values(self):
        """Test creating AudioMulticastConfig with values."""
        groups = [MulticastGroup(id="g1", name="Group 1", address="239.0.0.1")]
        streams = [AudioStream(id="s1", name="Stream 1", codec="aac")]

        config = AudioMulticastConfig(
            enabled=True,
            groups=groups,
            streams=streams,
            default_ttl=128,
            audio_source="mic1",
        )
        assert config.enabled is True
        assert len(config.groups) == 1
        assert len(config.streams) == 1
        assert config.default_ttl == 128
        assert config.audio_source == "mic1"

    def test_default_ttl_validation(self):
        """Test default_ttl field validation (1-255)."""
        # Valid values
        config = AudioMulticastConfig(default_ttl=1)
        assert config.default_ttl == 1
        config = AudioMulticastConfig(default_ttl=255)
        assert config.default_ttl == 255

        # Invalid values
        with pytest.raises(ValueError):
            AudioMulticastConfig(default_ttl=0)
        with pytest.raises(ValueError):
            AudioMulticastConfig(default_ttl=256)


# =============================================================================
# Server Report Models Tests
# =============================================================================


class TestServerReportFormat:
    """Tests for ServerReportFormat enum."""

    def test_values(self):
        """Test ServerReportFormat enum values."""
        assert ServerReportFormat.ZIP_WITH_IMAGE.value == "zip_with_image"
        assert ServerReportFormat.ZIP.value == "zip"
        assert ServerReportFormat.TEXT.value == "text"
        assert ServerReportFormat.DEBUG_TGZ.value == "debug_tgz"

    def test_string_enum(self):
        """Test that ServerReportFormat is a string enum."""
        assert isinstance(ServerReportFormat.ZIP_WITH_IMAGE, str)
        assert ServerReportFormat.ZIP.value == "zip"
        # String enum can be compared directly to strings
        assert ServerReportFormat.ZIP == "zip"


class TestServerReport:
    """Tests for ServerReport model."""

    def test_create_with_defaults(self):
        """Test creating ServerReport with defaults."""
        report = ServerReport()
        assert report.content == b""
        assert report.format == ServerReportFormat.ZIP_WITH_IMAGE
        assert report.size_bytes == 0
        assert report.filename == ""
        assert report.error is None
        assert report.success is False

    def test_create_with_values(self):
        """Test creating ServerReport with values."""
        content = b"test content"
        report = ServerReport(
            content=content,
            format=ServerReportFormat.ZIP,
            size_bytes=len(content),
            filename="test.zip",
        )
        assert report.content == content
        assert report.format == ServerReportFormat.ZIP
        assert report.size_bytes == len(content)
        assert report.filename == "test.zip"
        assert report.error is None
        assert report.success is True

    def test_create_with_error(self):
        """Test creating ServerReport with error."""
        report = ServerReport(
            content=b"",
            format=ServerReportFormat.TEXT,
            size_bytes=0,
            filename="",
            error="Connection timeout",
        )
        assert report.error == "Connection timeout"
        assert report.success is False

    def test_success_property(self):
        """Test success property logic."""
        # Empty report is not successful
        report = ServerReport(content=b"", size_bytes=0)
        assert report.success is False

        # Report with content but zero size is not successful
        report = ServerReport(content=b"data", size_bytes=0)
        assert report.success is False

        # Report with size but no content is successful (bytes are there)
        report = ServerReport(content=b"", size_bytes=10)
        assert report.success is True

        # Report with error is not successful
        report = ServerReport(content=b"data", size_bytes=4, error="Error")
        assert report.success is False

        # Report with content and size is successful
        report = ServerReport(content=b"data", size_bytes=4)
        assert report.success is True

    def test_size_bytes_validation(self):
        """Test size_bytes field validation (ge=0)."""
        # Valid value
        report = ServerReport(size_bytes=0)
        assert report.size_bytes == 0

        report = ServerReport(size_bytes=1000000)
        assert report.size_bytes == 1000000

        # Invalid value
        with pytest.raises(ValueError):
            ServerReport(size_bytes=-1)

    def test_debug_tgz_format(self):
        """Test creating ServerReport with debug_tgz format."""
        report = ServerReport(
            content=b"debug archive content",
            format=ServerReportFormat.DEBUG_TGZ,
            size_bytes=21,
            filename="debug.tgz",
        )
        assert report.format == ServerReportFormat.DEBUG_TGZ
        assert report.filename == "debug.tgz"
        assert report.success is True
