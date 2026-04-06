# axis-cam: Class Diagrams and Application Flow

This document contains Mermaid `classDiagram` diagrams and sequence diagrams capturing
the full class hierarchy, API module structure, configuration models, exception hierarchy,
key data models, and runtime interaction flows.

---

## Section 1: Class Hierarchy Diagrams

### 1a. Device Hierarchy

All four concrete device types inherit from the abstract `AxisDevice` base class.
`AxisDevice` holds 27 API module compositions as instance attributes and exposes
high-level async façade methods that delegate to those modules.

```mermaid
classDiagram
    class AxisDevice {
        <<abstract>>
        +device_type: DeviceType
        +device_info: BasicDeviceInfoAPI
        +params: ParamAPI
        +time: TimeAPI
        +logs: LogsAPI
        +lldp: LldpAPI
        +network: NetworkSettingsAPI
        +firewall: FirewallAPI
        +ssh: SshAPI
        +snmp: SnmpAPI
        +cert: CertAPI
        +ntp: NtpAPI
        +action: ActionAPI
        +mqtt: MqttBridgeAPI
        +recording: RecordingAPI
        +storage: RemoteStorageAPI
        +geolocation: GeolocationAPI
        +analytics: VideoAnalyticsAPI
        +snapshot: BestSnapshotAPI
        +analytics_mqtt: AnalyticsMqttAPI
        +audio_multicast: AudioMulticastAPI
        +serverreport: ServerReportAPI
        +oidc: OidcAPI
        +oauth: OAuthAPI
        +virtualhost: VirtualHostAPI
        +crypto_policy: CryptoPolicyAPI
        +networkpairing: NetworkPairingAPI
        +stream: StreamAPI
        -_host: str
        -_client: VapixClient
        -_capabilities: DeviceCapabilities|None
        -_device_info_cache: BasicDeviceInfo|None
        +host() str
        +client() VapixClient
        +__init__(host, username, password, port, ssl_verify, timeout, use_digest_auth)
        +__aenter__() Self
        +__aexit__(exc_type, exc_val, exc_tb) None
        +connect() None
        +disconnect() None
        +get_info() BasicDeviceInfo
        +get_status() DeviceStatus
        +get_capabilities() DeviceCapabilities
        +check_connectivity() bool
        +get_time_info() TimeInfo
        +get_logs(log_type, max_entries) LogReport
        +get_friendly_name() str
        +get_location() str
        +get_lldp_info() LldpInfo
        +get_network_config() NetworkConfig
        +get_firewall_config() FirewallConfig
        +get_ssh_config() SshConfig
        +get_snmp_config() SnmpConfig
        +get_cert_config() CertConfig
        +get_ntp_config() NtpConfig
        +get_action_config() ActionConfig
        +get_mqtt_config() MqttBridgeConfig
        +get_recording_config() RecordingConfig
        +get_storage_config() RemoteStorageConfig
        +get_geolocation_config() GeolocationConfig
        +get_analytics_config() AnalyticsConfig
        +get_snapshot_config() BestSnapshotConfig
        +get_analytics_mqtt_config() AnalyticsMqttConfig
        +get_audio_multicast_config() AudioMulticastConfig
        +capture_snapshot(resolution, compression, camera) bytes
        +download_server_report(format, timeout) ServerReport
        +download_debug_archive(timeout) ServerReport
        +get_oidc_config() OidcConfig
        +get_oauth_config() OAuthConfig
        +get_virtualhost_config() VirtualHostConfig
        +get_crypto_policy_config() CryptoPolicyConfig
        +get_networkpairing_config() NetworkPairingConfig
        +get_stream_diagnostics(device_name) StreamDiagnostics
        +get_device_specific_info()* dict
    }

    class AxisCamera {
        +device_type: DeviceType = CAMERA
        +get_device_specific_info() dict
        +get_snapshot(resolution) bytes
        +get_snapshot_url(resolution) str
        +get_video_stream_url(profile, codec) str
        +has_ptz() bool
        +has_audio() bool
        +has_analytics() bool
        +get_video_sources() list[dict]
        +get_stream_profiles() list[dict]
    }

    class AxisRecorder {
        +device_type: DeviceType = RECORDER
        +RECORDING_GROUP_PATH: str
        +REMOTE_STORAGE_PATH: str
        +get_device_specific_info() dict
        +get_recording_groups() list[dict]
        +get_recording_group(group_id) dict|None
        +get_storage_info() dict
        +get_disk_status() list[dict]
        +get_remote_storage_config() dict|None
        +get_connected_cameras() list[dict]
        +has_remote_storage() bool
    }

    class AxisIntercom {
        +device_type: DeviceType = INTERCOM
        +AUDIO_MULTICAST_PATH: str
        +get_device_specific_info() dict
        +get_audio_status() dict
        +get_audio_device_info() dict
        +get_audio_multicast_config() AudioMulticastConfig
        +get_sip_config() dict
        +has_video() bool
        +has_sip() bool
        +get_snapshot(resolution) bytes
        +get_snapshot_url(resolution) str
    }

    class AxisSpeaker {
        +device_type: DeviceType = SPEAKER
        +AUDIO_MULTICAST_PATH: str
        +get_device_specific_info() dict
        +get_audio_config() dict
        +get_audio_multicast_config() AudioMulticastConfig
        +get_audio_status() dict
        +get_audio_device_info() dict
        +get_volume() int|None
        +has_multicast() bool
        +get_audio_clips() list[dict]
    }

    class VapixClient {
        +host: str
        +username: str
        +password: str
        +port: int
        +use_https: bool
        +timeout: float
        +verify_ssl: bool
        +use_digest_auth: bool
        -_client: httpx.AsyncClient|None
        +base_url() str
        +connect() None
        +disconnect() None
        +get(path, params) httpx.Response
        +post(path, data, json) httpx.Response
        +get_json(path, params) dict
        +post_json(path, data, json_data) dict
        +get_raw(path, params) bytes
        +check_connectivity() bool
        +discover_apis() dict
    }

    AxisDevice <|-- AxisCamera : inherits
    AxisDevice <|-- AxisRecorder : inherits
    AxisDevice <|-- AxisIntercom : inherits
    AxisDevice <|-- AxisSpeaker : inherits
    AxisDevice *-- VapixClient : composes
```

---

### 1b. API Module Hierarchy

All 27 API modules inherit from `BaseAPI`, which owns the `VapixClient` reference and
exposes protected `_get()`, `_post()`, and `_get_raw()` helpers.

```mermaid
classDiagram
    class BaseAPI {
        <<abstract>>
        -_client: VapixClient
        +__init__(client)
        +_get(path, params) Any
        +_post(path, data, json_data) Any
        +_get_raw(path, params) bytes
    }

    %% ── Device Information ──────────────────────────────────────
    class BasicDeviceInfoAPI {
        +CGI_PATH: str
        +REST_PATH: str
        +get_info() BasicDeviceInfo
        +get_property(property_name) str|None
        +get_properties() DeviceProperties
        +is_axis_device() bool
        +get_firmware_version() str
        +get_serial_number() str
        +get_model() str
    }

    class ParamAPI {
        +get(param_name) str|None
        +get_group(group_name) ParameterGroup
        +get_all() list[ParameterGroup]
        +get_many(param_names) dict[str, str|None]
        +search(pattern) list[DeviceParameter]
        +export() dict
        +get_friendly_name() str
        +get_location() str
        +get_ip_address() str
        +get_mac_address() str
    }

    class TimeAPI {
        +get_info() TimeInfo
        +get_utc_time() datetime
        +get_local_time() datetime|None
        +get_timezone() str
        +get_ntp_status() NtpStatus
        +get_available_timezones() list[str]
    }

    %% ── Logging & Reports ───────────────────────────────────────
    class LogsAPI {
        +CGI_PATH: str
        +REST_PATH: str
        -_device_name: str
        +get_server_report(mode) bytes
        +get_log_files() dict[str, str]
        +get_logs(log_type, max_entries) LogReport
        +get_system_logs(max_entries) LogReport
        +get_access_logs(max_entries) LogReport
        +get_audit_logs(max_entries) LogReport
        +get_all_logs(max_entries) LogReport
        +stream_logs(log_type) AsyncIterator[LogEntry]
        +get_persistent_logging_enabled() bool
        +search_logs(pattern, log_type, max_entries) LogReport
        +get_log_summary(log_type) dict[str, int]
    }

    class ServerReportAPI {
        +download_report(format, timeout) ServerReport
        +save_report(path, format, timeout) ServerReport
        +get_debug_archive(timeout) ServerReport
        +save_debug_archive(path, timeout) ServerReport
    }

    %% ── Network ─────────────────────────────────────────────────
    class LldpAPI {
        +get_info() LldpInfo
        +get_neighbors() list[LldpNeighbor]
        +is_enabled() bool
    }

    class NetworkSettingsAPI {
        +get_config() NetworkConfig
        +get_interfaces() list[NetworkInterface]
        +get_dns() DnsSettings
        +get_hostname() str
        +get_global_proxy() ProxySettings|None
    }

    class NtpAPI {
        +get_config() NtpConfig
        +is_enabled() bool
        +get_servers() list[NtpServer]
        +get_sync_status() NtpSyncStatus
        +is_synchronized() bool
    }

    class NetworkPairingAPI {
        +get_config() NetworkPairingConfig
        +is_enabled() bool
        +get_mode() PairingMode
        +get_paired_devices() list[PairedDevice]
        +get_online_devices() list[PairedDevice]
        +get_pending_requests() list[PairingRequest]
        +discovery_enabled() bool
        +get_pairing_token() str
    }

    %% ── Security ────────────────────────────────────────────────
    class FirewallAPI {
        +get_config() FirewallConfig
        +is_enabled() bool
        +get_ipv4_rules() list[FirewallRule]
        +get_ipv6_rules() list[FirewallRule]
        +get_default_policy() FirewallAction
    }

    class SshAPI {
        +get_config() SshConfig
        +is_enabled() bool
        +get_port() int
        +get_authorized_keys() list[SshKey]
        +root_login_allowed() bool
    }

    class SnmpAPI {
        +get_config() SnmpConfig
        +is_enabled() bool
        +get_version() SnmpVersion
        +get_trap_receivers() list[SnmpTrapReceiver]
    }

    class CertAPI {
        +get_config() CertConfig
        +get_certificates() list[Certificate]
        +get_ca_certificates() list[Certificate]
        +get_active_certificate() Certificate|None
    }

    class CryptoPolicyAPI {
        +get_config() CryptoPolicyConfig
        +get_tls_version_range() tuple[TlsVersion, TlsVersion]
        +get_cipher_suites() list[CipherSuite]
        +get_enabled_ciphers() list[CipherSuite]
        +weak_ciphers_enabled() bool
        +hsts_enabled() bool
    }

    %% ── Identity & Access ───────────────────────────────────────
    class OidcAPI {
        +get_config() OidcConfig
        +is_enabled() bool
        +get_provider() OidcProviderConfig|None
        +get_claim_mappings() list[OidcClaimMapping]
        +local_auth_allowed() bool
    }

    class OAuthAPI {
        +get_config() OAuthConfig
        +is_enabled() bool
        +get_credentials() list[OAuthCredentialConfig]
        +get_token_statuses() list[OAuthTokenStatus]
        +get_default_credential() OAuthCredentialConfig|None
    }

    %% ── Events & Automation ─────────────────────────────────────
    class ActionAPI {
        +get_config() ActionConfig
        +get_rules() list[ActionRule]
        +get_templates() list[ActionTemplate]
        +get_rule(rule_id) ActionRule|None
    }

    class MqttBridgeAPI {
        +get_config() MqttBridgeConfig
        +get_clients() list[MqttClient]
        +get_event_filters() list[MqttEventFilter]
        +is_connected() bool
    }

    class AnalyticsMqttAPI {
        +get_config() AnalyticsMqttConfig
        +get_subscriptions() list[AnalyticsMqttSubscription]
        +get_broker() AnalyticsMqttBroker|None
        +get_subscription(subscription_id) AnalyticsMqttSubscription|None
    }

    %% ── Video & Audio ────────────────────────────────────────────
    class VideoAnalyticsAPI {
        +get_config() AnalyticsConfig
        +get_profiles() list[AnalyticsProfile]
        +get_scenarios() list[AnalyticsScenario]
        +get_object_classes() list[ObjectClass]
        +get_profile(profile_id) AnalyticsProfile|None
    }

    class BestSnapshotAPI {
        +get_config() BestSnapshotConfig
        +get_profiles() list[SnapshotProfile]
        +get_triggers() list[SnapshotTrigger]
        +get_profile(profile_id) SnapshotProfile|None
        +capture(resolution, compression, camera) bytes
    }

    class AudioMulticastAPI {
        +get_config() AudioMulticastConfig
        +get_groups() list[MulticastGroup]
        +get_streams() list[AudioStream]
        +get_group(group_id) MulticastGroup|None
        +get_stream(stream_id) AudioStream|None
    }

    class StreamAPI {
        +REST_PATH: str
        +get_rtsp_config() RTSPConfig
        +get_rtp_config() RTPConfig
        +get_stream_profiles() list[StreamProfile]
        +get_network_config() NetworkDiagnostics
        +get_image_config() dict
        +get_stream_cache() dict
        +get_qos_config() dict
        +get_diagnostics(device_name) StreamDiagnostics
    }

    %% ── Storage & Recording ─────────────────────────────────────
    class RecordingAPI {
        +get_config() RecordingConfig
        +get_groups() list[RecordingGroup]
        +get_profiles() list[RecordingProfile]
        +get_group(group_id) RecordingGroup|None
    }

    class RemoteStorageAPI {
        +get_config() RemoteStorageConfig
        +get_destinations() list[StorageDestination]
        +get_destination(dest_id) StorageDestination|None
    }

    %% ── Geography & Infrastructure ───────────────────────────────
    class GeolocationAPI {
        +get_config() GeolocationConfig
        +get_coordinates() tuple[float|None, float|None]
        +get_altitude() float|None
    }

    class VirtualHostAPI {
        +get_config() VirtualHostConfig
        +is_enabled() bool
        +get_hosts() list[VirtualHost]
        +get_default_host() VirtualHost|None
        +get_host_by_name(hostname) VirtualHost|None
    }

    BaseAPI <|-- BasicDeviceInfoAPI
    BaseAPI <|-- ParamAPI
    BaseAPI <|-- TimeAPI
    BaseAPI <|-- LogsAPI
    BaseAPI <|-- ServerReportAPI
    BaseAPI <|-- LldpAPI
    BaseAPI <|-- NetworkSettingsAPI
    BaseAPI <|-- NtpAPI
    BaseAPI <|-- NetworkPairingAPI
    BaseAPI <|-- FirewallAPI
    BaseAPI <|-- SshAPI
    BaseAPI <|-- SnmpAPI
    BaseAPI <|-- CertAPI
    BaseAPI <|-- CryptoPolicyAPI
    BaseAPI <|-- OidcAPI
    BaseAPI <|-- OAuthAPI
    BaseAPI <|-- ActionAPI
    BaseAPI <|-- MqttBridgeAPI
    BaseAPI <|-- AnalyticsMqttAPI
    BaseAPI <|-- VideoAnalyticsAPI
    BaseAPI <|-- BestSnapshotAPI
    BaseAPI <|-- AudioMulticastAPI
    BaseAPI <|-- StreamAPI
    BaseAPI <|-- RecordingAPI
    BaseAPI <|-- RemoteStorageAPI
    BaseAPI <|-- GeolocationAPI
    BaseAPI <|-- VirtualHostAPI
```

---

### 1c. Configuration Classes

Both configuration models are Pydantic `BaseModel` instances. `AppConfig` is a root object
returned by `load_config()` (cached via `@lru_cache`). `DeviceConfig` uses field aliases
to accept legacy YAML keys (`address` → `host`, `type` → `device_type`).

```mermaid
classDiagram
    class BaseModel {
        <<pydantic>>
    }

    class AppConfig {
        +model_config: frozen=True
        +default_device: str|None
        +timeout: float = 30.0
        +devices: dict[str, DeviceConfig]
    }

    class DeviceConfig {
        +model_config: frozen=True, populate_by_name=True
        +host: str  [alias: address]
        +username: str
        +password: SecretStr
        +port: int = 443
        +ssl_verify: bool = False
        +device_type: str = "camera"  [alias: type]
        +name: str|None = None
        +vendor: str = "axis"
        +model: str|None = None
        +validate_host(v)$ str
        +validate_device_type(v)$ str
        +validate_vendor(v)$ str
    }

    BaseModel <|-- AppConfig
    BaseModel <|-- DeviceConfig
    AppConfig "1" *-- "0..*" DeviceConfig : devices dict
```

Configuration loading precedence (highest → lowest):

1. Command-line arguments (CLI layer)
2. Environment variables (`AXIS_*`)
3. `.env` file in config directory
4. `~/.config/axiscam/config.yaml`
5. `~/.config/axis/config.yaml` (legacy, with warning)
6. System defaults

---

### 1d. Exception Hierarchy

```mermaid
classDiagram
    class Exception {
        <<builtin>>
    }

    class AxisError {
        Catch-all for all axis_cam errors.
        Use when you do not need to distinguish type.
    }

    class AxisConnectionError {
        Network unreachable, connection refused,
        timeout, DNS failure.
    }

    class AxisAuthenticationError {
        HTTP 401 / 403 - bad credentials
        or insufficient permissions.
    }

    class AxisDeviceError {
        HTTP 4xx/5xx (non-auth), invalid API
        response, device-side failure.
    }

    class AxisConfigError {
        Missing config file, invalid YAML,
        missing required fields, validation error.
    }

    class AxisApiNotSupportedError {
        Requested API not available on this
        device type or firmware version.
    }

    Exception <|-- AxisError
    AxisError <|-- AxisConnectionError
    AxisError <|-- AxisAuthenticationError
    AxisError <|-- AxisDeviceError
    AxisError <|-- AxisConfigError
    AxisError <|-- AxisApiNotSupportedError
```

---

### 1e. Key Model Classes

#### Device Information & Status

```mermaid
classDiagram
    class BaseModel {
        <<pydantic>>
    }

    class BasicDeviceInfo {
        +product_full_name: str  [alias: ProdFullName]
        +product_number: str  [alias: ProdNbr]
        +product_short_name: str  [alias: ProdShortName]
        +product_type: str  [alias: ProdType]
        +product_variant: str  [alias: ProdVariant]
        +serial_number: str  [alias: SerialNumber]
        +firmware_version: str  [alias: Version]
        +hardware_id: str  [alias: HardwareID]
        +architecture: str  [alias: Architecture]
        +soc: str  [alias: Soc]
        +soc_serial_number: str  [alias: SocSerialNumber]
        +brand: str  [alias: Brand]
    }

    class DeviceStatus {
        +host: str
        +reachable: bool
        +device_type: DeviceType
        +model: str
        +serial_number: str
        +firmware_version: str
        +uptime_seconds: int|None
        +current_time: datetime|None
    }

    class DeviceCapabilities {
        +has_ptz: bool
        +has_audio: bool
        +has_speaker: bool
        +has_microphone: bool
        +has_io_ports: bool
        +has_sd_card: bool
        +has_analytics: bool
        +supported_apis: list[str]
        +available_apis: dict[str, Any]
    }

    BaseModel <|-- BasicDeviceInfo
    BaseModel <|-- DeviceStatus
    BaseModel <|-- DeviceCapabilities
```

#### Stream Diagnostics Models

```mermaid
classDiagram
    class BaseModel {
        <<pydantic>>
    }

    class StreamDiagnostics {
        +device_name: str
        +rtsp: RTSPConfig
        +rtp: RTPConfig
        +profiles: list[StreamProfile]
        +network: NetworkDiagnostics
        +errors: list[str]
    }

    class RTSPConfig {
        +enabled: bool = True
        +port: int = 554
        +authentication: str = "digest"
        +timeout: int = 60
        +allow_path_arguments: bool = True
    }

    class RTPConfig {
        +start_port: int = 50000
        +end_port: int = 50999
        +multicast_enabled: bool = False
        +multicast_address: str
    }

    class StreamProfile {
        +name: str
        +description: str
        +video_codec: str = "H.264"
        +resolution: str
        +fps: int = 30
        +bitrate: int = 0
        +gop_length: int = 32
        +compression: int = 30
        +parameters: dict[str, Any]
    }

    class NetworkDiagnostics {
        +hostname: str
        +dhcp_enabled: bool
        +ip_address: str
        +subnet_mask: str
        +gateway: str
        +dns_servers: list[str]
        +mtu: int = 1500
        +ipv6_enabled: bool
    }

    BaseModel <|-- StreamDiagnostics
    BaseModel <|-- RTSPConfig
    BaseModel <|-- RTPConfig
    BaseModel <|-- StreamProfile
    BaseModel <|-- NetworkDiagnostics
    StreamDiagnostics *-- RTSPConfig
    StreamDiagnostics *-- RTPConfig
    StreamDiagnostics "1" *-- "0..*" StreamProfile
    StreamDiagnostics *-- NetworkDiagnostics
```

#### Log Models

```mermaid
classDiagram
    class BaseModel {
        <<pydantic>>
    }

    class LogEntry {
        +timestamp: datetime
        +hostname: str
        +level: NormalizedLogLevel
        +process: str
        +pid: int|None
        +message: str
        +raw: str
    }

    class LogReport {
        +device_name: str
        +device_address: str
        +log_type: LogType
        +entries: list[LogEntry]
        +retrieved_at: datetime
        +total_entries: int
        +model_post_init(__context) None
    }

    BaseModel <|-- LogEntry
    BaseModel <|-- LogReport
    LogReport "1" *-- "0..*" LogEntry
```

#### Firewall Models

```mermaid
classDiagram
    class BaseModel {
        <<pydantic>>
    }

    class FirewallConfig {
        +enabled: bool
        +ipv4_rules: list[FirewallRule]
        +ipv6_rules: list[FirewallRule]
        +default_policy: FirewallAction
        +icmp_allowed: bool
        +rules() list[FirewallRule]
    }

    class FirewallRule {
        +action: FirewallAction
        +protocol: FirewallProtocol
        +source: str
        +source_port: str
        +destination: str
        +dest_port: str
        +description: str
        +enabled: bool
        +priority: int
        +name() str
        +source_address() str
        +destination_port() str
    }

    BaseModel <|-- FirewallConfig
    BaseModel <|-- FirewallRule
    FirewallConfig "1" *-- "0..*" FirewallRule : ipv4_rules + ipv6_rules
```

#### LLDP Models

```mermaid
classDiagram
    class BaseModel {
        <<pydantic>>
    }

    class LldpInfo {
        +activated: bool
        +neighbors: list[LldpNeighbor]
    }

    class LldpNeighbor {
        +chassis_id: LldpChassisID  [alias: chassisID]
        +port_id: LldpPortID  [alias: portID]
        +port_descr: str  [alias: portDescr]
        +sys_name: str  [alias: sysName]
        +sys_descr: str  [alias: sysDescr]
        +if_name: str  [alias: ifName]
        +mgmt_ip: str|None  [alias: mgmtIP]
        +ttl: int  [alias: TTL]
        +age: int
        +protocol: str = "LLDP"
    }

    class LldpChassisID {
        +sub_type: ChassisIDSubType  [alias: subType]
        +value: str
    }

    class LldpPortID {
        +sub_type: PortIDSubType  [alias: subType]
        +value: str
    }

    BaseModel <|-- LldpInfo
    BaseModel <|-- LldpNeighbor
    BaseModel <|-- LldpChassisID
    BaseModel <|-- LldpPortID
    LldpInfo "1" *-- "0..*" LldpNeighbor
    LldpNeighbor *-- LldpChassisID
    LldpNeighbor *-- LldpPortID
```

#### ServerReport Model

```mermaid
classDiagram
    class BaseModel {
        <<pydantic>>
    }

    class ServerReport {
        +content: bytes
        +format: ServerReportFormat
        +size_bytes: int
        +filename: str
        +error: str|None
        +success() bool
    }

    BaseModel <|-- ServerReport
```

---

## Section 2: Interaction Diagrams

### 2a. `axiscam info --device front_camera`

This traces the full object lifecycle from CLI invocation through config loading,
device instantiation, API calls, and Rich console output.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI as cli.py (Typer)
    participant Config as config.py
    participant AppCfg as AppConfig
    participant DevCfg as DeviceConfig
    participant Device as AxisCamera
    participant Client as VapixClient
    participant DevInfoAPI as BasicDeviceInfoAPI
    participant TimeAPI as TimeAPI

    User->>CLI: axiscam info --device front_camera

    CLI->>Config: load_config() [lru_cache]
    Config->>Config: load_env_file()
    Config->>Config: load_yaml_config(~/.config/axiscam/config.yaml)
    Config->>AppCfg: AppConfig.model_validate(config_data)
    AppCfg->>DevCfg: DeviceConfig.model_validate(device_dict)
    DevCfg-->>AppCfg: validated DeviceConfig
    AppCfg-->>Config: AppConfig instance
    Config-->>CLI: AppConfig

    CLI->>Config: get_device_config("front_camera")
    Config-->>CLI: DeviceConfig(host, username, password, port, device_type)

    CLI->>Device: AxisCamera(host, username, password, port=443, ssl_verify=False)
    Device->>Client: VapixClient(host, username, password, port=443, use_https=True)
    Device->>DevInfoAPI: BasicDeviceInfoAPI(client)
    Device->>TimeAPI: TimeAPI(client)
    Note over Device: 27 API modules initialised

    CLI->>Device: async with device (context manager)
    Device->>Client: __aenter__() → httpx.AsyncClient created

    CLI->>Device: get_status()
    Device->>Device: get_info()  [cache miss]
    Device->>DevInfoAPI: get_info()
    DevInfoAPI->>Client: _get(REST_PATH)
    Client->>Client: GET https://host/config/rest/basic-device-info/v2beta
    Client-->>DevInfoAPI: JSON response
    DevInfoAPI->>DevInfoAPI: _parse_rest_response(data)
    DevInfoAPI-->>Device: BasicDeviceInfo

    Device->>TimeAPI: get_info()
    TimeAPI->>Client: _get(time endpoint)
    Client-->>TimeAPI: JSON response
    TimeAPI-->>Device: TimeInfo

    Device->>Device: DeviceStatus(host, reachable=True, ...)
    Device-->>CLI: DeviceStatus

    CLI->>Device: get_lldp_info()
    Device->>Device: lldp.get_info()
    Device-->>CLI: LldpInfo

    CLI->>Device: get_network_config()
    Device-->>CLI: NetworkConfig

    CLI->>Device: __aexit__()
    Device->>Client: aclose()

    CLI->>User: Rich panel with device info table
```

---

### 2b. Report Generation — `axiscam report --full`

During a full report, the device is opened once and multiple API modules are called
to collect configuration data. Each API call is independent and could be parallelised
(the current implementation is sequential; the diagram shows the logical flow).

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI as cli.py
    participant Device as AxisDevice (e.g. AxisCamera)
    participant Client as VapixClient
    participant DevInfo as BasicDeviceInfoAPI
    participant Logs as LogsAPI
    participant Lldp as LldpAPI
    participant Net as NetworkSettingsAPI
    participant FW as FirewallAPI
    participant SSH as SshAPI
    participant SNMP as SnmpAPI
    participant Cert as CertAPI
    participant NTP as NtpAPI
    participant Stream as StreamAPI

    User->>CLI: axiscam report --full --device front_camera

    CLI->>Device: async with AxisCamera(...) as device
    Device->>Client: httpx.AsyncClient created

    Note over CLI, Stream: All calls share the same VapixClient session

    CLI->>Device: get_info()
    Device->>DevInfo: get_info()
    DevInfo->>Client: GET /config/rest/basic-device-info/v2beta
    Client-->>DevInfo: BasicDeviceInfo

    CLI->>Device: get_status()
    Device-->>CLI: DeviceStatus

    CLI->>Device: get_logs(LogType.SYSTEM)
    Device->>Logs: get_logs(SYSTEM)
    Logs->>Client: GET /axis-cgi/serverreport.cgi?mode=tar_all
    Client-->>Logs: tar bytes
    Logs->>Logs: parse_log_content(content)
    Logs-->>CLI: LogReport

    CLI->>Device: get_lldp_info()
    Device->>Lldp: get_info()
    Lldp->>Client: GET /config/rest/lldp/v1beta
    Client-->>Lldp: JSON
    Lldp-->>CLI: LldpInfo

    CLI->>Device: get_network_config()
    Device->>Net: get_config()
    Net->>Client: GET /config/rest/network-settings/v1
    Client-->>Net: JSON
    Net-->>CLI: NetworkConfig

    CLI->>Device: get_firewall_config()
    Device->>FW: get_config()
    FW->>Client: GET /config/rest/firewall/v1
    Client-->>FW: JSON
    FW-->>CLI: FirewallConfig

    CLI->>Device: get_ssh_config()
    Device->>SSH: get_config()
    SSH->>Client: GET /config/rest/ssh/v1
    Client-->>SSH: JSON
    SSH-->>CLI: SshConfig

    CLI->>Device: get_snmp_config()
    Device->>SNMP: get_config()
    SNMP->>Client: GET /config/rest/snmp/v1
    Client-->>SNMP: JSON
    SNMP-->>CLI: SnmpConfig

    CLI->>Device: get_cert_config()
    Device->>Cert: get_config()
    Cert->>Client: GET /config/rest/cert/v1
    Client-->>Cert: JSON
    Cert-->>CLI: CertConfig

    CLI->>Device: get_ntp_config()
    Device->>NTP: get_config()
    NTP->>Client: GET /config/rest/ntp/v1
    Client-->>NTP: JSON
    NTP-->>CLI: NtpConfig

    CLI->>Device: get_stream_diagnostics()
    Device->>Stream: get_diagnostics(host)
    Stream->>Client: GET /config/rest/param/v2beta/Network/RTSP
    Stream->>Client: GET /config/rest/param/v2beta/Network/RTP
    Stream->>Client: GET /config/rest/param/v2beta/StreamProfile
    Stream->>Client: GET /config/rest/param/v2beta/Network
    Client-->>Stream: JSON responses
    Stream-->>CLI: StreamDiagnostics

    CLI->>Device: __aexit__()
    Device->>Client: aclose()

    CLI->>User: Rich report rendered to console / file
```

---

### 2c. Configuration Object Lifecycle

How `AppConfig` and `DeviceConfig` are created, validated, and consumed end-to-end.

```mermaid
sequenceDiagram
    autonumber
    participant Env as OS Environment
    participant EnvFile as .env file
    participant YamlFile as config.yaml
    participant Config as config.py
    participant AppCfg as AppConfig (Pydantic)
    participant DevCfg as DeviceConfig (Pydantic)
    participant Cache as lru_cache
    participant CLI as CLI / Library Caller
    participant Device as AxisDevice subclass

    Note over Config, Cache: load_config() is decorated with @lru_cache(maxsize=1)

    CLI->>Config: load_config(config_path=None)
    Config->>Cache: cache miss on first call

    Config->>EnvFile: load_env_file() → populate os.environ
    Config->>YamlFile: load_yaml_config(~/.config/axiscam/config.yaml)
    YamlFile-->>Config: raw dict

    Config->>Config: interpolate_env_vars(raw_dict)
    Note over Config: ${AXIS_ROOT_USER_PASSWORD} → actual value

    Config->>Config: normalize_devices_format(config)
    Note over Config: list format → dict format (legacy compat)

    Config->>Env: load_env_config() → check AXIS_HOST, AXIS_USERNAME, etc.
    Env-->>Config: env_config dict (may be empty)

    Config->>AppCfg: AppConfig.model_validate(merged_data)
    AppCfg->>DevCfg: DeviceConfig.model_validate(device_dict) per device
    DevCfg->>DevCfg: validate_host(v) → strip whitespace
    DevCfg->>DevCfg: validate_device_type(v) → normalize to camera/recorder/intercom/speaker
    DevCfg->>DevCfg: validate_vendor(v) → lowercase
    DevCfg-->>AppCfg: validated frozen DeviceConfig
    AppCfg-->>Config: frozen AppConfig

    Config->>Cache: store result
    Config-->>CLI: AppConfig

    CLI->>Config: get_device_config("front_camera")
    Config->>Cache: cache hit → AppConfig
    Config->>AppCfg: devices["front_camera"]
    AppCfg-->>CLI: DeviceConfig

    CLI->>Device: AxisCamera(host=cfg.host, username=cfg.username, password=cfg.password.get_secret_value(), ...)
    Note over Device: SecretStr.get_secret_value() unwraps password at instantiation

    Device-->>CLI: AxisDevice instance ready
```

---

## Section 3: Package Diagram

Dependency relationships between `axis_cam` subpackages. Arrows indicate
`imports from` direction (dependency flows in arrow direction).

```mermaid
classDiagram
    class `axis_cam` {
        <<package root>>
        __init__.py
        exports: AxisCamera, AxisRecorder,
                 AxisIntercom, AxisSpeaker,
                 AxisError, load_config
    }

    class `axis_cam.cli` {
        <<entry point>>
        cli.py
        Typer app + subcommand groups:
        logs, network, security,
        services, download
    }

    class `axis_cam.devices` {
        <<subpackage>>
        base.py  → AxisDevice (ABC)
        camera.py → AxisCamera
        recorder.py → AxisRecorder
        intercom.py → AxisIntercom
        speaker.py → AxisSpeaker
    }

    class `axis_cam.api` {
        <<subpackage>>
        base.py → BaseAPI (ABC)
        27 domain API modules
    }

    class `axis_cam.client` {
        <<module>>
        client.py → VapixClient
        httpx async HTTP transport
    }

    class `axis_cam.models` {
        <<module>>
        models.py
        All Pydantic data models,
        enums, type aliases
    }

    class `axis_cam.config` {
        <<module>>
        config.py
        AppConfig, DeviceConfig,
        load_config(), get_device_config()
    }

    class `axis_cam.exceptions` {
        <<module>>
        exceptions.py
        AxisError hierarchy
    }

    `axis_cam.cli` --> `axis_cam.devices` : imports device classes
    `axis_cam.cli` --> `axis_cam.config` : load_config, get_device_config
    `axis_cam.cli` --> `axis_cam.models` : LogType, ServerReportFormat
    `axis_cam.cli` --> `axis_cam.exceptions` : error handling

    `axis_cam.devices` --> `axis_cam.api` : composes 27 API modules
    `axis_cam.devices` --> `axis_cam.client` : passes VapixClient to APIs
    `axis_cam.devices` --> `axis_cam.models` : return types + enums
    `axis_cam.devices` --> `axis_cam.exceptions` : raises AxisError subclasses

    `axis_cam.api` --> `axis_cam.client` : _client: VapixClient
    `axis_cam.api` --> `axis_cam.models` : return types
    `axis_cam.api` --> `axis_cam.exceptions` : raises on error

    `axis_cam.client` --> `axis_cam.exceptions` : raises on HTTP errors

    `axis_cam.config` --> `axis_cam.models` : DeviceType used in mapping
    `axis_cam.config` --> `axis_cam.exceptions` : AxisConfigError

    `axis_cam` --> `axis_cam.devices` : re-exports public API
    `axis_cam` --> `axis_cam.config` : re-exports load_config
    `axis_cam` --> `axis_cam.exceptions` : re-exports AxisError
```
