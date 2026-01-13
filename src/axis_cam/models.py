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
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    """

    model_config = ConfigDict(frozen=True)

    name: str
    mac_address: str = ""
    ip_address: str = ""
    subnet_mask: str = ""
    gateway: str = ""
    dhcp_enabled: bool = True
    ipv6_address: str = ""


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


class LogEntry(BaseModel):
    """A single log entry from AXIS device.

    Attributes:
        timestamp: Log entry timestamp.
        hostname: Device hostname.
        level: Log severity level.
        process: Process name that generated the log.
        pid: Process ID.
        message: Log message content.
        raw: Original raw log line.
    """

    timestamp: datetime
    hostname: str = ""
    level: LogLevel = LogLevel.INFO
    process: str = ""
    pid: int | None = None
    message: str
    raw: str = ""

    @field_validator("level", mode="before")
    @classmethod
    def normalize_level(cls, v: Any) -> LogLevel:
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
