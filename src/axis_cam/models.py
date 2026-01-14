"""Pydantic models for AXIS Camera Manager.

This module contains all data models used throughout the application,
providing validation, serialization, and type safety for AXIS device data.

Models are organized by domain:
    - Device Information: BasicDeviceInfo, DeviceCapabilities
    - Time: TimeInfo, TimeZoneInfo
    - Network: NetworkSettings, NetworkInterface
    - Logs: LogEntry, LogReport
    - Parameters: DeviceParameter, ParameterGroup
"""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

# =============================================================================
# Enumerations
# =============================================================================


class DeviceType(str, Enum):
    """Types of AXIS devices."""

    CAMERA = "camera"
    RECORDER = "recorder"
    INTERCOM = "intercom"
    SPEAKER = "speaker"
    UNKNOWN = "unknown"


class LogLevel(str, Enum):
    """Log severity levels per RFC5424."""

    EMERGENCY = "emergency"
    ALERT = "alert"
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    NOTICE = "notice"
    INFO = "info"
    DEBUG = "debug"


class LogType(str, Enum):
    """Types of logs available from AXIS devices."""

    SYSTEM = "system"
    ACCESS = "access"
    AUDIT = "audit"
    ALL = "all"


class TimeZoneSource(str, Enum):
    """Source of timezone configuration."""

    DHCP = "dhcp"
    IANA = "iana"
    POSIX = "posix"


class AuthState(str, Enum):
    """Network port authentication state."""

    UNKNOWN = "unknown"
    AUTHENTICATED = "authenticated"
    AUTHENTICATING = "authenticating"
    STOPPED = "stopped"
    FAILED = "failed"


class ServerReportFormat(str, Enum):
    """Format options for server reports."""

    ZIP_WITH_IMAGE = "zip_with_image"
    ZIP = "zip"
    TEXT = "text"
    DEBUG_TGZ = "debug_tgz"


# =============================================================================
# Device Information Models
# =============================================================================


class BasicDeviceInfo(BaseModel):
    """Basic device information from AXIS device.

    Attributes:
        product_full_name: Full product name including variant.
        product_number: AXIS product number (e.g., M3216-LVE).
        product_short_name: Short product name.
        product_type: Product category (e.g., Network Camera).
        product_variant: Product variant or configuration.
        serial_number: Device serial number.
        firmware_version: Current firmware version string.
        hardware_id: Hardware identifier.
        architecture: CPU architecture (e.g., aarch64).
        soc: System-on-chip identifier.
        soc_serial_number: SoC serial number.
        brand: Device brand (typically "AXIS").
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    product_full_name: str = Field(default="", alias="ProdFullName")
    product_number: str = Field(default="", alias="ProdNbr")
    product_short_name: str = Field(default="", alias="ProdShortName")
    product_type: str = Field(default="", alias="ProdType")
    product_variant: str = Field(default="", alias="ProdVariant")
    serial_number: str = Field(default="", alias="SerialNumber")
    firmware_version: str = Field(default="", alias="Version")
    hardware_id: str = Field(default="", alias="HardwareID")
    architecture: str = Field(default="", alias="Architecture")
    soc: str = Field(default="", alias="Soc")
    soc_serial_number: str = Field(default="", alias="SocSerialNumber")
    brand: str = Field(default="AXIS", alias="Brand")


class DeviceProperties(BaseModel):
    """Extended device properties from param.cgi.

    Attributes:
        friendly_name: User-assigned device name.
        location: Physical location description.
        firmware_build_date: Firmware build date.
        uptime: Device uptime in seconds.
        web_url: Device web interface URL.
    """

    model_config = ConfigDict(frozen=True)

    friendly_name: str = ""
    location: str = ""
    firmware_build_date: str = ""
    uptime: int = 0
    web_url: str = ""


# =============================================================================
# Time Models
# =============================================================================


class TimeInfo(BaseModel):
    """Device time information.

    Attributes:
        utc_time: Current UTC time.
        local_time: Current local time.
        timezone: Active timezone identifier.
        timezone_source: How timezone is configured.
        posix_timezone: POSIX timezone string.
        dst_enabled: Whether DST is enabled.
        max_supported_year: Maximum year device can handle.
    """

    model_config = ConfigDict(frozen=True)

    utc_time: datetime
    local_time: datetime | None = None
    timezone: str = ""
    timezone_source: TimeZoneSource = TimeZoneSource.IANA
    posix_timezone: str = ""
    dst_enabled: bool = True
    max_supported_year: int = 2037


class NtpStatus(BaseModel):
    """NTP synchronization status.

    Attributes:
        enabled: Whether NTP is enabled.
        server: NTP server address.
        synchronized: Whether time is synchronized.
        last_sync: Last synchronization time.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    server: str = ""
    synchronized: bool = False
    last_sync: datetime | None = None


# =============================================================================
# Network Models
# =============================================================================


class NetworkInterface(BaseModel):
    """Network interface configuration.

    Attributes:
        name: Interface name (e.g., eth0).
        mac_address: MAC address.
        ip_address: IPv4 address.
        subnet_mask: Network subnet mask.
        gateway: Default gateway.
        dhcp_enabled: Whether DHCP is enabled.
        ipv6_address: IPv6 address if configured.
        mtu: Maximum transmission unit.
        link_speed: Link speed (e.g., "1000Mbps").
        link_status: Link status (e.g., "up", "down", "unknown").
    """

    model_config = ConfigDict(frozen=True)

    name: str
    mac_address: str = ""
    ip_address: str = ""
    subnet_mask: str = ""
    gateway: str = ""
    dhcp_enabled: bool = True
    ipv6_address: str = ""
    mtu: int = 1500
    link_speed: str = ""
    link_status: str = "unknown"


class DnsSettings(BaseModel):
    """DNS configuration.

    Attributes:
        primary: Primary DNS server.
        secondary: Secondary DNS server.
        domain: DNS search domain.
    """

    model_config = ConfigDict(frozen=True)

    primary: str = ""
    secondary: str = ""
    domain: str = ""


class NetworkSettings(BaseModel):
    """Complete network settings.

    Attributes:
        hostname: Device hostname.
        interfaces: List of network interfaces.
        dns: DNS configuration.
        bonjour_enabled: Whether Bonjour/mDNS is enabled.
        upnp_enabled: Whether UPnP is enabled.
    """

    model_config = ConfigDict(frozen=True)

    hostname: str = ""
    interfaces: list[NetworkInterface] = Field(default_factory=list)
    dns: DnsSettings = Field(default_factory=DnsSettings)
    bonjour_enabled: bool = True
    upnp_enabled: bool = False


# =============================================================================
# Log Models
# =============================================================================


def _normalize_log_level(v: Any) -> LogLevel:
    """Normalize log level string to enum.

    Args:
        v: Input value for level field.

    Returns:
        Normalized LogLevel enum value.
    """
    if isinstance(v, LogLevel):
        return v
    if isinstance(v, str):
        level_map = {
            "emerg": LogLevel.EMERGENCY,
            "alert": LogLevel.ALERT,
            "crit": LogLevel.CRITICAL,
            "err": LogLevel.ERROR,
            "error": LogLevel.ERROR,
            "warn": LogLevel.WARNING,
            "warning": LogLevel.WARNING,
            "notice": LogLevel.NOTICE,
            "info": LogLevel.INFO,
            "debug": LogLevel.DEBUG,
        }
        return level_map.get(v.lower(), LogLevel.INFO)
    return LogLevel.INFO


# Type alias for LogLevel that accepts strings and normalizes them
NormalizedLogLevel = Annotated[LogLevel, BeforeValidator(_normalize_log_level)]


class LogEntry(BaseModel):
    """A single log entry from AXIS device.

    Attributes:
        timestamp: Log entry timestamp.
        hostname: Device hostname.
        level: Log severity level (accepts string shortcuts like 'err', 'warn').
        process: Process name that generated the log.
        pid: Process ID.
        message: Log message content.
        raw: Original raw log line.
    """

    timestamp: datetime
    hostname: str = ""
    level: NormalizedLogLevel = LogLevel.INFO
    process: str = ""
    pid: int | None = None
    message: str
    raw: str = ""


class LogReport(BaseModel):
    """Collection of log entries with metadata.

    Attributes:
        device_name: Name of the device.
        device_address: IP address of the device.
        log_type: Type of logs retrieved.
        entries: List of log entries.
        retrieved_at: When the logs were retrieved.
        total_entries: Total number of entries.
    """

    device_name: str
    device_address: str
    log_type: LogType
    entries: list[LogEntry] = Field(default_factory=list)
    retrieved_at: datetime = Field(default_factory=datetime.now)
    total_entries: int = 0

    def model_post_init(self, __context: Any) -> None:
        """Update total_entries after initialization."""
        if not self.total_entries:
            object.__setattr__(self, "total_entries", len(self.entries))


class ServerReport(BaseModel):
    """Server report downloaded from an AXIS device.

    Attributes:
        content: Raw binary content of the report.
        format: Format of the report (zip, text, debug_tgz).
        size_bytes: Size of the content in bytes.
        filename: Suggested filename for the report.
        error: Error message if download failed.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    content: bytes = Field(default=b"", description="Raw binary content")
    format: ServerReportFormat = Field(
        default=ServerReportFormat.ZIP_WITH_IMAGE,
        description="Report format",
    )
    size_bytes: int = Field(default=0, ge=0, description="Content size in bytes")
    filename: str = Field(default="", description="Suggested filename")
    error: str | None = Field(default=None, description="Error message if failed")

    @property
    def success(self) -> bool:
        """Check if the report was downloaded successfully."""
        return self.error is None and self.size_bytes > 0


# =============================================================================
# Parameter Models
# =============================================================================


class DeviceParameter(BaseModel):
    """A single device parameter.

    Attributes:
        name: Parameter name (e.g., "Audio.MaxListeners").
        value: Parameter value as string.
        group: Parameter group (e.g., "Audio").
        writable: Whether parameter can be modified.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    value: str
    group: str = ""
    writable: bool = False


class ParameterGroup(BaseModel):
    """A group of related parameters.

    Attributes:
        name: Group name (e.g., "Audio").
        parameters: List of parameters in this group.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    parameters: list[DeviceParameter] = Field(default_factory=list)


# =============================================================================
# API Response Models
# =============================================================================


class ApiResponse(BaseModel):
    """Generic AXIS API response wrapper.

    Attributes:
        status: Response status ("success" or "error").
        data: Response data payload.
        error_code: Error code if status is error.
        error_message: Error message if status is error.
    """

    status: str = "success"
    data: Any = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def is_success(self) -> bool:
        """Check if response indicates success."""
        return self.status == "success"


# =============================================================================
# Device Status Models
# =============================================================================


class DeviceStatus(BaseModel):
    """Overall device status summary.

    Attributes:
        host: Device IP address or hostname.
        reachable: Whether device is reachable.
        device_type: Type of device (camera, recorder, etc.).
        model: Device model.
        serial_number: Device serial number.
        firmware_version: Firmware version.
        uptime_seconds: Device uptime in seconds (optional).
        current_time: Current device time.
    """

    host: str = ""
    reachable: bool = False
    device_type: DeviceType = DeviceType.UNKNOWN
    model: str = ""
    serial_number: str = ""
    firmware_version: str = ""
    uptime_seconds: int | None = None
    current_time: datetime | None = None


# =============================================================================
# Capabilities Models
# =============================================================================


class DeviceCapabilities(BaseModel):
    """Device capabilities and features.

    Attributes:
        has_ptz: Device supports PTZ control.
        has_audio: Device supports audio.
        has_speaker: Device has speaker output.
        has_microphone: Device has microphone input.
        has_io_ports: Device has I/O ports.
        has_sd_card: Device has SD card slot.
        has_analytics: Device supports video analytics.
        supported_apis: List of supported API names.
    """

    has_ptz: bool = False
    has_audio: bool = False
    has_speaker: bool = False
    has_microphone: bool = False
    has_io_ports: bool = False
    has_sd_card: bool = False
    has_analytics: bool = False
    supported_apis: list[str] = Field(default_factory=list)
    available_apis: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# LLDP Models
# =============================================================================


class ChassisIDSubType(str, Enum):
    """Type of identifier used for LLDP chassis ID."""

    CHASSIS_COMPONENT = "ChassisComponent"
    INTERFACE_ALIAS = "InterfaceAlias"
    PORT_COMPONENT = "PortComponent"
    MAC_ADDRESS = "MACAddress"
    NETWORK_ADDRESS = "NetworkAddress"
    INTERFACE_NAME = "InterfaceName"
    LOCALLY_ASSIGNED = "LocallyAssigned"


class PortIDSubType(str, Enum):
    """Type of identifier used for LLDP port ID."""

    INTERFACE_ALIAS = "InterfaceAlias"
    PORT_COMPONENT = "PortComponent"
    MAC_ADDRESS = "MACAddress"
    NETWORK_ADDRESS = "NetworkAddress"
    INTERFACE_NAME = "InterfaceName"
    AGENT_CIRCUIT_ID = "AgentCircuitID"
    LOCALLY_ASSIGNED = "LocallyAssigned"


class LldpChassisID(BaseModel):
    """LLDP Chassis identifier.

    Attributes:
        sub_type: Type of chassis identifier.
        value: Chassis ID value (MAC address, name, etc.).
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    sub_type: ChassisIDSubType = Field(alias="subType")
    value: str


class LldpPortID(BaseModel):
    """LLDP Port identifier.

    Attributes:
        sub_type: Type of port identifier.
        value: Port ID value.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    sub_type: PortIDSubType = Field(alias="subType")
    value: str


class LldpNeighbor(BaseModel):
    """LLDP neighbor information.

    Represents a device discovered via LLDP on the network.

    Attributes:
        chassis_id: Chassis identifier of the neighbor.
        port_id: Port identifier on the neighbor.
        port_descr: Port description.
        sys_name: System name of the neighbor.
        sys_descr: System description (often includes model).
        if_name: Local interface name (e.g., eth0).
        mgmt_ip: Management IP address of neighbor.
        ttl: Time-to-live in seconds.
        age: Age of the LLDP entry.
        protocol: Discovery protocol (LLDP, CDP, etc.).
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    chassis_id: LldpChassisID = Field(alias="chassisID")
    port_id: LldpPortID = Field(alias="portID")
    port_descr: str = Field(default="", alias="portDescr")
    sys_name: str = Field(default="", alias="sysName")
    sys_descr: str = Field(default="", alias="sysDescr")
    if_name: str = Field(default="", alias="ifName")
    mgmt_ip: str | None = Field(default=None, alias="mgmtIP")
    ttl: int = Field(default=0, alias="TTL")
    age: int = 0
    protocol: str = "LLDP"


class LldpInfo(BaseModel):
    """LLDP configuration and neighbor information.

    Attributes:
        activated: Whether LLDP is enabled on the device.
        neighbors: List of discovered LLDP neighbors.
    """

    model_config = ConfigDict(frozen=True)

    activated: bool = False
    neighbors: list[LldpNeighbor] = Field(default_factory=list)


# =============================================================================
# Network Settings Models (Extended)
# =============================================================================


class ProxySettings(BaseModel):
    """Proxy configuration settings.

    Attributes:
        enabled: Whether proxy is enabled.
        host: Proxy server address (alias: server).
        port: Proxy server port.
        username: Proxy authentication username.
        exceptions: List of addresses that bypass proxy.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    enabled: bool = False
    host: str = Field(default="", alias="server")
    port: int = 8080
    username: str = ""
    exceptions: list[str] = Field(default_factory=list)

    @property
    def server(self) -> str:
        """Get proxy server address (alias for host)."""
        return self.host


class NetworkConfig(BaseModel):
    """Extended network configuration from network-settings API.

    Attributes:
        hostname: Device hostname.
        interfaces: List of network interfaces.
        dns: DNS configuration.
        global_proxy: Global proxy settings.
        bonjour_enabled: Whether Bonjour/mDNS is enabled.
        upnp_enabled: Whether UPnP is enabled.
        websocket_enabled: Whether WebSocket is enabled.
    """

    model_config = ConfigDict(frozen=True)

    hostname: str = ""
    interfaces: list[NetworkInterface] = Field(default_factory=list)
    dns: DnsSettings = Field(default_factory=DnsSettings)
    global_proxy: ProxySettings | None = None
    bonjour_enabled: bool = True
    upnp_enabled: bool = False
    websocket_enabled: bool = True


# =============================================================================
# Firewall Models
# =============================================================================


class FirewallAction(str, Enum):
    """Firewall rule actions."""

    ALLOW = "allow"
    DENY = "deny"
    DROP = "drop"
    REJECT = "reject"


class FirewallProtocol(str, Enum):
    """Network protocols for firewall rules."""

    ANY = "any"
    TCP = "tcp"
    UDP = "udp"
    ICMP = "icmp"
    ICMPV6 = "icmpv6"


class FirewallRule(BaseModel):
    """A single firewall rule.

    Attributes:
        action: Rule action (allow, deny, drop, reject).
        protocol: Network protocol.
        source: Source IP address/network.
        source_port: Source port or range.
        destination: Destination IP address/network.
        dest_port: Destination port or range.
        description: Rule description.
        enabled: Whether rule is active.
        priority: Rule priority (lower = higher priority).
    """

    model_config = ConfigDict(frozen=True)

    action: FirewallAction = FirewallAction.ALLOW
    protocol: FirewallProtocol = FirewallProtocol.ANY
    source: str = ""
    source_port: str = ""
    destination: str = ""
    dest_port: str = ""
    description: str = ""
    enabled: bool = True
    priority: int = 0

    @property
    def name(self) -> str:
        """Get rule name (alias for description)."""
        return self.description

    @property
    def source_address(self) -> str:
        """Get source address (alias for source)."""
        return self.source

    @property
    def destination_port(self) -> str:
        """Get destination port (alias for dest_port)."""
        return self.dest_port


class FirewallConfig(BaseModel):
    """Firewall configuration.

    Attributes:
        enabled: Whether firewall is enabled.
        ipv4_rules: List of IPv4 firewall rules.
        ipv6_rules: List of IPv6 firewall rules.
        default_policy: Default action for unmatched traffic.
        icmp_allowed: Whether ICMP traffic is allowed.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    ipv4_rules: list[FirewallRule] = Field(default_factory=list)
    ipv6_rules: list[FirewallRule] = Field(default_factory=list)
    default_policy: FirewallAction = FirewallAction.ALLOW
    icmp_allowed: bool = True

    @property
    def rules(self) -> list[FirewallRule]:
        """Get all firewall rules (IPv4 + IPv6 combined)."""
        return self.ipv4_rules + self.ipv6_rules


# =============================================================================
# SSH Models
# =============================================================================


class SshKey(BaseModel):
    """SSH authorized key.

    Attributes:
        key_type: Key type (e.g., ssh-rsa, ssh-ed25519).
        key: Public key data.
        comment: Key comment/identifier.
        fingerprint: Key fingerprint.
    """

    model_config = ConfigDict(frozen=True)

    key_type: str = ""
    key: str = ""
    comment: str = ""
    fingerprint: str = ""

    @property
    def name(self) -> str:
        """Get the key name (alias for comment)."""
        return self.comment


class SshConfig(BaseModel):
    """SSH configuration.

    Attributes:
        enabled: Whether SSH is enabled.
        port: SSH port number.
        root_login_allowed: Whether root login is permitted.
        password_auth_enabled: Whether password authentication is enabled.
        authorized_keys: List of authorized SSH keys.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    port: int = 22
    root_login_allowed: bool = False
    password_auth_enabled: bool = True
    authorized_keys: list[SshKey] = Field(default_factory=list)

    @property
    def root_login_enabled(self) -> bool:
        """Get root login status (alias for root_login_allowed)."""
        return self.root_login_allowed


# =============================================================================
# SNMP Models
# =============================================================================


class SnmpVersion(str, Enum):
    """SNMP protocol versions."""

    V1 = "v1"
    V2C = "v2c"
    V3 = "v3"


class SnmpTrapReceiver(BaseModel):
    """SNMP trap receiver configuration.

    Attributes:
        address: Trap receiver IP address or hostname.
        port: Trap receiver port.
        community: SNMP community string.
        enabled: Whether this receiver is active.
    """

    model_config = ConfigDict(frozen=True)

    address: str = ""
    port: int = 162
    community: str = ""
    enabled: bool = True
    version: str = "v2c"  # SNMP version for this trap receiver


class SnmpConfig(BaseModel):
    """SNMP configuration.

    Attributes:
        enabled: Whether SNMP is enabled.
        version: SNMP protocol version.
        read_community: Read-only community string.
        write_community: Read-write community string.
        system_contact: System contact information.
        system_location: System location information.
        trap_receivers: List of trap receivers.
        v3_enabled: Whether SNMPv3 is enabled.
        v3_username: SNMPv3 username.
        v3_auth_protocol: SNMPv3 authentication protocol.
        v3_priv_protocol: SNMPv3 privacy protocol.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    version: SnmpVersion = SnmpVersion.V2C
    read_community: str = "public"
    write_community: str = ""
    system_contact: str = ""
    system_location: str = ""
    trap_receivers: list[SnmpTrapReceiver] = Field(default_factory=list)
    v3_enabled: bool = False
    v3_username: str = ""
    v3_auth_protocol: str = ""
    v3_priv_protocol: str = ""

    @property
    def location(self) -> str:
        """Get system location (alias for system_location)."""
        return self.system_location

    @property
    def contact(self) -> str:
        """Get system contact (alias for system_contact)."""
        return self.system_contact


# =============================================================================
# Certificate Models
# =============================================================================


class CertificateType(str, Enum):
    """Types of SSL/TLS certificates."""

    SERVER = "server"
    CLIENT = "client"
    CA = "ca"


class Certificate(BaseModel):
    """SSL/TLS certificate information.

    Attributes:
        cert_id: Certificate identifier.
        cert_type: Type of certificate.
        subject: Certificate subject (CN, O, etc.).
        issuer: Certificate issuer.
        not_before: Validity start date.
        not_after: Validity end date.
        serial_number: Certificate serial number.
        fingerprint_sha256: SHA-256 fingerprint.
        fingerprint_sha1: SHA-1 fingerprint.
        key_size: Key size in bits.
        key_type: Key algorithm type.
        self_signed: Whether certificate is self-signed.
    """

    model_config = ConfigDict(frozen=True)

    cert_id: str = ""
    cert_type: CertificateType = CertificateType.SERVER
    subject: str = ""
    issuer: str = ""
    not_before: str = ""
    not_after: str = ""
    serial_number: str = ""
    fingerprint_sha256: str = ""
    fingerprint_sha1: str = ""
    key_size: int = 0
    key_type: str = ""
    self_signed: bool = False

    @property
    def id(self) -> str:
        """Get certificate ID (alias for cert_id)."""
        return self.cert_id

    @property
    def valid_from(self) -> str:
        """Get validity start date (alias for not_before)."""
        return self.not_before

    @property
    def valid_to(self) -> str:
        """Get validity end date (alias for not_after)."""
        return self.not_after

    @property
    def is_valid(self) -> bool:
        """Check if certificate is currently valid (simplified check)."""
        # This is a simplified check - real implementation would compare dates
        return bool(self.not_before and self.not_after)


class CertConfig(BaseModel):
    """Certificate configuration.

    Attributes:
        certificates: List of installed certificates.
        ca_certificates: List of CA certificates.
        active_certificate: Currently active HTTPS certificate.
        https_enabled: Whether HTTPS is enabled.
        https_only: Whether only HTTPS is allowed.
    """

    model_config = ConfigDict(frozen=True)

    certificates: list[Certificate] = Field(default_factory=list)
    ca_certificates: list[Certificate] = Field(default_factory=list)
    active_certificate: Certificate | None = None
    https_enabled: bool = True
    https_only: bool = False

    @property
    def https_cert_id(self) -> str:
        """Get the HTTPS certificate ID."""
        if self.active_certificate:
            return self.active_certificate.cert_id
        return ""

    @property
    def client_cert_enabled(self) -> bool:
        """Check if client certificate authentication is enabled."""
        # Returns True if there are any client certificates installed
        return any(c.cert_type == CertificateType.CLIENT for c in self.certificates)


# =============================================================================
# NTP Models
# =============================================================================


class NtpServer(BaseModel):
    """NTP server configuration.

    Attributes:
        address: NTP server address.
        enabled: Whether this server is active.
        prefer: Whether this is the preferred server.
        source: Server source (static, dhcp).
        iburst: Whether to use iburst mode for faster initial sync.
    """

    model_config = ConfigDict(frozen=True)

    address: str = ""
    enabled: bool = True
    prefer: bool = False
    source: str = "static"
    iburst: bool = False


class NtpSyncStatus(BaseModel):
    """NTP synchronization status.

    Attributes:
        synchronized: Whether time is synchronized.
        current_server: Server currently being used.
        stratum: NTP stratum level.
        offset_ms: Time offset in milliseconds.
        last_sync: Last synchronization timestamp.
    """

    model_config = ConfigDict(frozen=True)

    synchronized: bool = False
    current_server: str = ""
    stratum: int = 0
    offset_ms: float = 0.0
    last_sync: str = ""

    @property
    def delay_ms(self) -> float:
        """Get delay in milliseconds (alias for offset_ms)."""
        return self.offset_ms


class NtpConfig(BaseModel):
    """NTP configuration.

    Attributes:
        enabled: Whether NTP is enabled.
        servers: List of NTP servers.
        sync_status: Current synchronization status.
        use_dhcp_servers: Whether to use DHCP-provided servers.
        fallback_enabled: Whether fallback servers are enabled.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    servers: list[NtpServer] = Field(default_factory=list)
    sync_status: NtpSyncStatus = Field(default_factory=NtpSyncStatus)
    use_dhcp_servers: bool = False
    fallback_enabled: bool = False


# =============================================================================
# Action Rules Models
# =============================================================================


class ActionRule(BaseModel):
    """Action rule configuration.

    Attributes:
        id: Rule identifier.
        name: Rule name.
        enabled: Whether rule is active.
        primary_condition: Primary triggering condition.
        conditions: List of additional conditions.
        actions: List of actions to perform.
    """

    model_config = ConfigDict(frozen=True)

    id: str = ""
    name: str = ""
    enabled: bool = False
    primary_condition: str = ""
    conditions: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)


class ActionTemplate(BaseModel):
    """Action template definition.

    Attributes:
        id: Template identifier.
        name: Template name.
        template_type: Type of action template.
        parameters: Template parameters.
    """

    model_config = ConfigDict(frozen=True)

    id: str = ""
    name: str = ""
    template_type: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class ActionConfig(BaseModel):
    """Action rules configuration.

    Attributes:
        rules: List of action rules.
        templates: List of action templates.
    """

    model_config = ConfigDict(frozen=True)

    rules: list[ActionRule] = Field(default_factory=list)
    templates: list[ActionTemplate] = Field(default_factory=list)


# =============================================================================
# MQTT Bridge Models
# =============================================================================


class MqttClient(BaseModel):
    """MQTT client configuration.

    Attributes:
        id: Client identifier.
        host: MQTT broker hostname or IP.
        port: MQTT broker port.
        protocol: Connection protocol (tcp, ssl, ws, wss).
        username: Authentication username.
        client_id: MQTT client identifier.
        keep_alive: Keep-alive interval in seconds.
        clean_session: Whether to use clean sessions.
        use_tls: Whether to use TLS encryption.
    """

    model_config = ConfigDict(frozen=True)

    id: str = ""
    host: str = ""
    port: int = 1883
    protocol: str = "tcp"
    username: str = ""
    client_id: str = ""
    keep_alive: int = 60
    clean_session: bool = True
    use_tls: bool = False


class MqttEventFilter(BaseModel):
    """MQTT event filter configuration.

    Attributes:
        id: Filter identifier.
        name: Filter name.
        enabled: Whether filter is active.
        topic: MQTT topic to publish to.
        event_types: List of event types to publish.
        qos: Quality of Service level (0, 1, 2).
        retain: Whether to retain messages.
    """

    model_config = ConfigDict(frozen=True)

    id: str = ""
    name: str = ""
    enabled: bool = True
    topic: str = ""
    event_types: list[str] = Field(default_factory=list)
    qos: int = Field(default=0, ge=0, le=2)
    retain: bool = False


class MqttBridgeConfig(BaseModel):
    """MQTT event bridge configuration.

    Attributes:
        enabled: Whether MQTT bridge is enabled.
        connected: Whether broker connection is active.
        clients: List of MQTT clients.
        event_filters: List of event filters.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    connected: bool = False
    clients: list[MqttClient] = Field(default_factory=list)
    event_filters: list[MqttEventFilter] = Field(default_factory=list)


# =============================================================================
# Recording Models
# =============================================================================


class RecordingProfile(BaseModel):
    """Recording profile configuration.

    Attributes:
        id: Profile identifier.
        name: Profile name.
        format: Recording format (e.g., mkv, mp4).
        video_codec: Video codec (e.g., h264, h265).
        audio_enabled: Whether audio is recorded.
        resolution: Video resolution.
        framerate: Video framerate.
        bitrate: Video bitrate in kbps.
    """

    model_config = ConfigDict(frozen=True)

    id: str = ""
    name: str = ""
    format: str = "mkv"
    video_codec: str = "h264"
    audio_enabled: bool = False
    resolution: str = ""
    framerate: int = 0
    bitrate: int = 0


class RecordingGroup(BaseModel):
    """Recording group configuration.

    Attributes:
        id: Group identifier.
        name: Group name.
        description: Group description.
        storage_id: Associated storage destination ID.
        retention_days: Recording retention in days.
        max_size_mb: Maximum storage size in MB.
        profile_id: Associated recording profile ID.
    """

    model_config = ConfigDict(frozen=True)

    id: str = ""
    name: str = ""
    description: str = ""
    storage_id: str = ""
    retention_days: int = 0
    max_size_mb: int = 0
    profile_id: str = ""


class RecordingConfig(BaseModel):
    """Recording configuration.

    Attributes:
        groups: List of recording groups.
        profiles: List of recording profiles.
    """

    model_config = ConfigDict(frozen=True)

    groups: list[RecordingGroup] = Field(default_factory=list)
    profiles: list[RecordingProfile] = Field(default_factory=list)


# =============================================================================
# Remote Storage Models
# =============================================================================


class StorageType(str, Enum):
    """Types of remote storage destinations."""

    S3 = "s3"
    AZURE = "azure"
    GCS = "gcs"
    SFTP = "sftp"
    FTP = "ftp"
    SMB = "smb"
    NFS = "nfs"


class StorageDestination(BaseModel):
    """Remote storage destination configuration.

    Attributes:
        id: Destination identifier.
        name: Destination name.
        storage_type: Type of storage (s3, azure, etc.).
        endpoint: Storage endpoint URL.
        bucket: Bucket or container name.
        region: Cloud region.
        access_key_id: Access key ID.
        prefix: Object key prefix/path.
        enabled: Whether destination is active.
    """

    model_config = ConfigDict(frozen=True)

    id: str = ""
    name: str = ""
    storage_type: StorageType = StorageType.S3
    endpoint: str = ""
    bucket: str = ""
    region: str = ""
    access_key_id: str = ""
    prefix: str = ""
    enabled: bool = False


class RemoteStorageConfig(BaseModel):
    """Remote storage configuration.

    Attributes:
        destinations: List of storage destinations.
    """

    model_config = ConfigDict(frozen=True)

    destinations: list[StorageDestination] = Field(default_factory=list)


# =============================================================================
# Geolocation Models
# =============================================================================


class GeolocationConfig(BaseModel):
    """Device geolocation configuration.

    Attributes:
        latitude: GPS latitude in decimal degrees.
        longitude: GPS longitude in decimal degrees.
        altitude: Altitude in meters.
        direction: Heading/direction in degrees (0-360).
        horizontal_accuracy: Horizontal accuracy in meters.
        vertical_accuracy: Vertical accuracy in meters.
        heading: Device heading in degrees.
        speed: Speed in meters per second.
        timestamp: Last location update timestamp.
    """

    model_config = ConfigDict(frozen=True)

    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    direction: float | None = Field(default=None, ge=0, le=360)
    horizontal_accuracy: float | None = None
    vertical_accuracy: float | None = None
    heading: float | None = Field(default=None, ge=0, le=360)
    speed: float | None = Field(default=None, ge=0)
    timestamp: str | None = None


# =============================================================================
# Video Analytics Models
# =============================================================================


class ObjectClass(BaseModel):
    """Object detection class configuration.

    Attributes:
        id: Class identifier.
        name: Class name (e.g., human, vehicle, animal).
        enabled: Whether class detection is active.
        confidence_threshold: Minimum confidence for detection (0-100).
        color: Display color for bounding boxes.
    """

    model_config = ConfigDict(frozen=True)

    id: str = ""
    name: str = ""
    enabled: bool = True
    confidence_threshold: int = Field(default=50, ge=0, le=100)
    color: str = ""


class AnalyticsScenario(BaseModel):
    """Analytics scenario configuration.

    Attributes:
        id: Scenario identifier.
        name: Scenario name.
        scenario_type: Type of scenario (e.g., crossline, area).
        enabled: Whether scenario is active.
        object_classes: List of object classes to detect.
        trigger_on_enter: Trigger when objects enter region.
        trigger_on_exit: Trigger when objects exit region.
        trigger_on_presence: Trigger on continued presence.
        dwell_time: Time in seconds before presence trigger.
        region: Region/zone definition as coordinates.
    """

    model_config = ConfigDict(frozen=True)

    id: str = ""
    name: str = ""
    scenario_type: str = ""
    enabled: bool = False
    object_classes: list[str] = Field(default_factory=list)
    trigger_on_enter: bool = True
    trigger_on_exit: bool = False
    trigger_on_presence: bool = False
    dwell_time: int = Field(default=0, ge=0)
    region: dict[str, Any] = Field(default_factory=dict)


class AnalyticsProfile(BaseModel):
    """Analytics profile configuration.

    Attributes:
        id: Profile identifier.
        name: Profile name.
        enabled: Whether profile is active.
        camera_id: Associated camera/video source.
        scenarios: List of scenario IDs in this profile.
        sensitivity: Detection sensitivity (0-100).
        min_object_size: Minimum object size percentage.
        max_object_size: Maximum object size percentage.
    """

    model_config = ConfigDict(frozen=True)

    id: str = ""
    name: str = ""
    enabled: bool = False
    camera_id: str = ""
    scenarios: list[str] = Field(default_factory=list)
    sensitivity: int = Field(default=50, ge=0, le=100)
    min_object_size: int = Field(default=0, ge=0, le=100)
    max_object_size: int = Field(default=100, ge=0, le=100)


class AnalyticsConfig(BaseModel):
    """Video analytics configuration.

    Attributes:
        enabled: Whether video analytics is enabled.
        profiles: List of analytics profiles.
        scenarios: List of analytics scenarios.
        object_classes: List of object detection classes.
        metadata_enabled: Whether metadata output is enabled.
        overlay_enabled: Whether overlay display is enabled.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    profiles: list[AnalyticsProfile] = Field(default_factory=list)
    scenarios: list[AnalyticsScenario] = Field(default_factory=list)
    object_classes: list[ObjectClass] = Field(default_factory=list)
    metadata_enabled: bool = False
    overlay_enabled: bool = False


# =============================================================================
# Best Snapshot Models
# =============================================================================


class SnapshotProfile(BaseModel):
    """Snapshot profile configuration.

    Attributes:
        id: Profile identifier.
        name: Profile name.
        enabled: Whether profile is active.
        resolution: Image resolution (e.g., 1920x1080).
        compression: JPEG compression level (0-100).
        rotation: Image rotation in degrees.
        mirror: Whether to mirror image.
        overlay_enabled: Whether to include overlays.
        timestamp_enabled: Whether to include timestamp.
    """

    model_config = ConfigDict(frozen=True)

    id: str = ""
    name: str = ""
    enabled: bool = True
    resolution: str = ""
    compression: int = Field(default=25, ge=0, le=100)
    rotation: int = Field(default=0, ge=0, le=360)
    mirror: bool = False
    overlay_enabled: bool = False
    timestamp_enabled: bool = True


class SnapshotTrigger(BaseModel):
    """Snapshot trigger configuration.

    Attributes:
        id: Trigger identifier.
        name: Trigger name.
        enabled: Whether trigger is active.
        trigger_type: Type of trigger (e.g., motion, event).
        profile_id: Associated snapshot profile.
        pre_trigger_time: Pre-trigger buffer in seconds.
        post_trigger_time: Post-trigger buffer in seconds.
        event_filter: Event filter expression.
    """

    model_config = ConfigDict(frozen=True)

    id: str = ""
    name: str = ""
    enabled: bool = True
    trigger_type: str = ""
    profile_id: str = ""
    pre_trigger_time: int = Field(default=0, ge=0)
    post_trigger_time: int = Field(default=0, ge=0)
    event_filter: str = ""


class BestSnapshotConfig(BaseModel):
    """Best snapshot configuration.

    Attributes:
        enabled: Whether best snapshot is enabled.
        profiles: List of snapshot profiles.
        triggers: List of snapshot triggers.
        default_resolution: Default image resolution.
        default_compression: Default JPEG compression.
        max_snapshots_per_event: Maximum snapshots per trigger event.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    profiles: list[SnapshotProfile] = Field(default_factory=list)
    triggers: list[SnapshotTrigger] = Field(default_factory=list)
    default_resolution: str = ""
    default_compression: int = Field(default=25, ge=0, le=100)
    max_snapshots_per_event: int = Field(default=1, ge=1)


# =============================================================================
# Analytics MQTT Models
# =============================================================================


class AnalyticsMqttBroker(BaseModel):
    """Analytics MQTT broker configuration.

    Attributes:
        host: MQTT broker hostname or IP.
        port: MQTT broker port.
        protocol: Connection protocol (tcp, ssl, ws, wss).
        username: Authentication username.
        client_id: MQTT client identifier.
        use_tls: Whether to use TLS encryption.
        ca_certificate: CA certificate for TLS.
        validate_server_cert: Whether to validate server certificate.
    """

    model_config = ConfigDict(frozen=True)

    host: str = ""
    port: int = 1883
    protocol: str = "tcp"
    username: str = ""
    client_id: str = ""
    use_tls: bool = False
    ca_certificate: str = ""
    validate_server_cert: bool = True


class AnalyticsMqttSubscription(BaseModel):
    """Analytics MQTT subscription configuration.

    Attributes:
        id: Subscription identifier.
        name: Subscription name.
        enabled: Whether subscription is active.
        topic: MQTT topic to publish to.
        qos: Quality of Service level (0, 1, 2).
        retain: Whether to retain messages.
        analytics_types: List of analytics data types to publish.
        object_classes: Object classes to include.
        include_image: Whether to include snapshot image.
        image_resolution: Resolution for included images.
    """

    model_config = ConfigDict(frozen=True)

    id: str = ""
    name: str = ""
    enabled: bool = True
    topic: str = ""
    qos: int = Field(default=0, ge=0, le=2)
    retain: bool = False
    analytics_types: list[str] = Field(default_factory=list)
    object_classes: list[str] = Field(default_factory=list)
    include_image: bool = False
    image_resolution: str = ""


class AnalyticsMqttConfig(BaseModel):
    """Analytics MQTT configuration.

    Attributes:
        enabled: Whether analytics MQTT is enabled.
        connected: Whether broker connection is active.
        broker: MQTT broker configuration.
        subscriptions: List of analytics subscriptions.
        include_timestamps: Whether to include timestamps in data.
        include_coordinates: Whether to include coordinates in data.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    connected: bool = False
    broker: AnalyticsMqttBroker | None = None
    subscriptions: list[AnalyticsMqttSubscription] = Field(default_factory=list)
    include_timestamps: bool = True
    include_coordinates: bool = True


# =============================================================================
# Audio Multicast Models
# =============================================================================


class AudioStream(BaseModel):
    """Audio stream configuration.

    Attributes:
        id: Stream identifier.
        name: Stream name.
        enabled: Whether stream is active.
        codec: Audio codec (e.g., g711, aac, opus).
        sample_rate: Sample rate in Hz.
        bitrate: Bitrate in bps.
        channels: Number of audio channels.
        source: Audio source identifier.
    """

    model_config = ConfigDict(frozen=True)

    id: str = ""
    name: str = ""
    enabled: bool = False
    codec: str = ""
    sample_rate: int = Field(default=16000, ge=8000)
    bitrate: int = Field(default=64000, ge=8000)
    channels: int = Field(default=1, ge=1, le=8)
    source: str = ""


class MulticastGroup(BaseModel):
    """Multicast group configuration.

    Attributes:
        id: Group identifier.
        name: Group name.
        enabled: Whether group is active.
        address: Multicast IP address.
        port: Multicast port number.
        ttl: Time-to-live for packets.
        stream_id: Associated audio stream ID.
    """

    model_config = ConfigDict(frozen=True)

    id: str = ""
    name: str = ""
    enabled: bool = False
    address: str = ""
    port: int = Field(default=0, ge=0, le=65535)
    ttl: int = Field(default=64, ge=1, le=255)
    stream_id: str = ""


class AudioMulticastConfig(BaseModel):
    """Audio multicast configuration.

    Attributes:
        enabled: Whether audio multicast is enabled.
        groups: List of multicast groups.
        streams: List of audio streams.
        default_ttl: Default TTL for packets.
        audio_source: Default audio source.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    groups: list[MulticastGroup] = Field(default_factory=list)
    streams: list[AudioStream] = Field(default_factory=list)
    default_ttl: int = Field(default=64, ge=1, le=255)
    audio_source: str = ""


# =============================================================================
# OIDC Setup Models (OpenID Connect)
# =============================================================================


class OidcProviderConfig(BaseModel):
    """OpenID Connect provider configuration.

    Attributes:
        issuer_uri: OIDC provider issuer URI.
        client_id: Client ID for the OIDC application.
        authorization_endpoint: Authorization endpoint URL.
        token_endpoint: Token endpoint URL.
        userinfo_endpoint: UserInfo endpoint URL.
        jwks_uri: JSON Web Key Set URI.
        scopes: List of requested scopes.
        response_type: OAuth response type.
    """

    model_config = ConfigDict(frozen=True)

    issuer_uri: str = ""
    client_id: str = ""
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    userinfo_endpoint: str = ""
    jwks_uri: str = ""
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile"])
    response_type: str = "code"


class OidcClaimMapping(BaseModel):
    """Mapping between OIDC claims and device attributes.

    Attributes:
        claim_name: Name of the OIDC claim.
        device_attribute: Device attribute to map to.
        required: Whether the claim is required.
    """

    model_config = ConfigDict(frozen=True)

    claim_name: str = ""
    device_attribute: str = ""
    required: bool = False


class OidcConfig(BaseModel):
    """OpenID Connect configuration.

    Attributes:
        enabled: Whether OIDC authentication is enabled.
        provider: OIDC provider configuration.
        redirect_uri: Redirect URI for OIDC flow.
        logout_uri: Logout redirect URI.
        claim_mappings: List of claim-to-attribute mappings.
        admin_claim: Claim that grants admin access.
        admin_claim_value: Value of admin claim for access grant.
        session_timeout: Session timeout in seconds.
        allow_local_auth: Whether to allow local authentication as fallback.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    provider: OidcProviderConfig | None = None
    redirect_uri: str = ""
    logout_uri: str = ""
    claim_mappings: list[OidcClaimMapping] = Field(default_factory=list)
    admin_claim: str = ""
    admin_claim_value: str = ""
    session_timeout: int = Field(default=3600, ge=60)
    allow_local_auth: bool = True


# =============================================================================
# OAuth Client Credentials Grant Models
# =============================================================================


class OAuthCredentialConfig(BaseModel):
    """OAuth 2.0 client credentials configuration.

    Attributes:
        credential_id: Unique identifier for the credential set.
        name: Friendly name for the credential.
        token_endpoint: OAuth token endpoint URL.
        client_id: OAuth client ID.
        scope: Requested OAuth scopes.
        enabled: Whether this credential is active.
        grant_type: OAuth grant type (typically client_credentials).
        token_refresh_margin: Seconds before expiry to refresh token.
    """

    model_config = ConfigDict(frozen=True)

    credential_id: str = ""
    name: str = ""
    token_endpoint: str = ""
    client_id: str = ""
    scope: str = ""
    enabled: bool = False
    grant_type: str = "client_credentials"
    token_refresh_margin: int = Field(default=60, ge=0)


class OAuthTokenStatus(BaseModel):
    """OAuth token status information.

    Attributes:
        credential_id: Associated credential ID.
        valid: Whether the current token is valid.
        expires_at: Token expiration timestamp.
        scope: Granted scope.
        error: Last error message if any.
    """

    model_config = ConfigDict(frozen=True)

    credential_id: str = ""
    valid: bool = False
    expires_at: str = ""
    scope: str = ""
    error: str = ""


class OAuthConfig(BaseModel):
    """OAuth 2.0 Client Credentials Grant configuration.

    Attributes:
        enabled: Whether OAuth client credentials is enabled.
        credentials: List of configured credentials.
        token_statuses: Status of each credential's token.
        default_credential: Default credential ID to use.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    credentials: list[OAuthCredentialConfig] = Field(default_factory=list)
    token_statuses: list[OAuthTokenStatus] = Field(default_factory=list)
    default_credential: str = ""


# =============================================================================
# Virtual Host Models
# =============================================================================


class VirtualHost(BaseModel):
    """Virtual host configuration.

    Attributes:
        host_id: Unique identifier for the virtual host.
        hostname: Hostname/domain for this virtual host.
        enabled: Whether this virtual host is active.
        certificate_id: SSL certificate ID for HTTPS.
        redirect_http_to_https: Whether to redirect HTTP to HTTPS.
        default_host: Whether this is the default host.
        allowed_methods: List of allowed HTTP methods.
    """

    model_config = ConfigDict(frozen=True)

    host_id: str = ""
    hostname: str = ""
    enabled: bool = True
    certificate_id: str = ""
    redirect_http_to_https: bool = True
    default_host: bool = False
    allowed_methods: list[str] = Field(default_factory=lambda: ["GET", "POST", "PUT", "DELETE"])


class VirtualHostConfig(BaseModel):
    """Virtual host configuration.

    Attributes:
        enabled: Whether virtual hosting is enabled.
        hosts: List of configured virtual hosts.
        default_certificate: Default SSL certificate ID.
        strict_host_checking: Whether to enforce strict host header checking.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    hosts: list[VirtualHost] = Field(default_factory=list)
    default_certificate: str = ""
    strict_host_checking: bool = True


# =============================================================================
# Cryptographic Policy Models
# =============================================================================


class TlsVersion(str, Enum):
    """TLS protocol versions."""

    TLS_1_0 = "1.0"
    TLS_1_1 = "1.1"
    TLS_1_2 = "1.2"
    TLS_1_3 = "1.3"


class CipherSuite(BaseModel):
    """TLS cipher suite configuration.

    Attributes:
        name: Cipher suite name.
        enabled: Whether this cipher is enabled.
        strength: Cipher strength classification.
        key_exchange: Key exchange algorithm.
        authentication: Authentication algorithm.
        encryption: Encryption algorithm.
        mac: MAC algorithm.
    """

    model_config = ConfigDict(frozen=True)

    name: str = ""
    enabled: bool = True
    strength: str = ""  # "strong", "medium", "weak"
    key_exchange: str = ""
    authentication: str = ""
    encryption: str = ""
    mac: str = ""


class CryptoPolicyConfig(BaseModel):
    """Cryptographic policy configuration.

    Attributes:
        tls_min_version: Minimum TLS version allowed.
        tls_max_version: Maximum TLS version allowed.
        cipher_suites: List of cipher suite configurations.
        weak_ciphers_enabled: Whether weak ciphers are allowed.
        prefer_server_ciphers: Whether to prefer server cipher order.
        session_tickets_enabled: Whether TLS session tickets are enabled.
        ocsp_stapling_enabled: Whether OCSP stapling is enabled.
        hsts_enabled: Whether HTTP Strict Transport Security is enabled.
        hsts_max_age: HSTS max-age in seconds.
        hsts_include_subdomains: Whether HSTS includes subdomains.
    """

    model_config = ConfigDict(frozen=True)

    tls_min_version: TlsVersion = TlsVersion.TLS_1_2
    tls_max_version: TlsVersion = TlsVersion.TLS_1_3
    cipher_suites: list[CipherSuite] = Field(default_factory=list)
    weak_ciphers_enabled: bool = False
    prefer_server_ciphers: bool = True
    session_tickets_enabled: bool = True
    ocsp_stapling_enabled: bool = False
    hsts_enabled: bool = False
    hsts_max_age: int = Field(default=31536000, ge=0)  # 1 year default
    hsts_include_subdomains: bool = False


# =============================================================================
# Network Pairing Models
# =============================================================================


class PairingMode(str, Enum):
    """Network pairing modes."""

    DISABLED = "disabled"
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    DISCOVERY = "discovery"


class PairedDevice(BaseModel):
    """Information about a paired device.

    Attributes:
        device_id: Unique identifier of the paired device.
        name: Friendly name of the paired device.
        address: IP address or hostname.
        device_type: Type of paired device.
        paired_at: Timestamp when pairing was established.
        last_seen: Timestamp of last communication.
        online: Whether the device is currently online.
        trust_level: Trust level (e.g., "full", "limited").
    """

    model_config = ConfigDict(frozen=True)

    device_id: str = ""
    name: str = ""
    address: str = ""
    device_type: str = ""
    paired_at: str = ""
    last_seen: str = ""
    online: bool = False
    trust_level: str = "full"


class PairingRequest(BaseModel):
    """Pending pairing request information.

    Attributes:
        request_id: Unique identifier for the request.
        device_name: Name of the requesting device.
        device_address: Address of the requesting device.
        device_type: Type of the requesting device.
        requested_at: Timestamp when request was received.
        expires_at: Timestamp when request expires.
    """

    model_config = ConfigDict(frozen=True)

    request_id: str = ""
    device_name: str = ""
    device_address: str = ""
    device_type: str = ""
    requested_at: str = ""
    expires_at: str = ""


class NetworkPairingConfig(BaseModel):
    """Network pairing configuration.

    Attributes:
        enabled: Whether network pairing is enabled.
        mode: Pairing mode (disabled, manual, automatic, discovery).
        discovery_enabled: Whether device discovery is active.
        pairing_token: Current pairing token (if in pairing mode).
        token_expiry: Token expiration timestamp.
        paired_devices: List of currently paired devices.
        pending_requests: List of pending pairing requests.
        max_paired_devices: Maximum number of devices that can be paired.
        auto_approve_same_network: Auto-approve devices on same network.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    mode: PairingMode = PairingMode.DISABLED
    discovery_enabled: bool = False
    pairing_token: str = ""
    token_expiry: str = ""
    paired_devices: list[PairedDevice] = Field(default_factory=list)
    pending_requests: list[PairingRequest] = Field(default_factory=list)
    max_paired_devices: int = Field(default=10, ge=1)
    auto_approve_same_network: bool = False
