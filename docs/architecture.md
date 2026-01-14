# AXIS Camera Manager Architecture

This document provides a comprehensive overview of the `axis_cam` package architecture, including module relationships, data flows, and design patterns.

## Table of Contents

- [High-Level Overview](#high-level-overview)
- [Package Structure](#package-structure)
- [Core Components](#core-components)
- [Design Patterns](#design-patterns)
- [Data Flow](#data-flow)
- [Module Relationships](#module-relationships)

---

## High-Level Overview

The AXIS Camera Manager (`axis_cam`) is a Python library and CLI tool for managing AXIS network devices via the VAPIX REST API. The architecture follows a layered design with clear separation of concerns.

```mermaid
flowchart TB
    subgraph "User Interface Layer"
        CLI[CLI - Typer]
    end

    subgraph "Device Layer"
        Camera[AxisCamera]
        Recorder[AxisRecorder]
        Intercom[AxisIntercom]
        Speaker[AxisSpeaker]
    end

    subgraph "API Layer"
        DeviceInfo[DeviceInfoAPI]
        Param[ParamAPI]
        Stream[StreamAPI]
        Logs[LogsAPI]
        Network[NetworkAPI]
        Security[SecurityAPIs]
        More[... 23 more APIs]
    end

    subgraph "Transport Layer"
        Client[VapixClient]
    end

    subgraph "External"
        Device[AXIS Device]
    end

    CLI --> Camera
    CLI --> Recorder
    CLI --> Intercom
    CLI --> Speaker

    Camera --> DeviceInfo
    Camera --> Param
    Camera --> Stream
    Camera --> Logs
    Camera --> Network
    Camera --> Security
    Camera --> More

    DeviceInfo --> Client
    Param --> Client
    Stream --> Client
    Logs --> Client
    Network --> Client
    Security --> Client
    More --> Client

    Client -->|HTTP/HTTPS| Device
```

## Package Structure

```
axis_cam/
├── __init__.py          # Package exports
├── cli.py               # Typer CLI (~2600 lines)
├── client.py            # VapixClient HTTP client
├── config.py            # Configuration management
├── models.py            # Pydantic models (~2000 lines)
├── exceptions.py        # Exception hierarchy
├── api/                 # VAPIX API modules (29 modules)
│   ├── __init__.py
│   ├── base.py          # BaseAPI abstract class
│   ├── device_info.py   # Basic device information
│   ├── param.py         # Device parameters
│   ├── stream.py        # Stream diagnostics
│   ├── logs.py          # Log retrieval
│   ├── network.py       # Network settings
│   ├── firewall.py      # Firewall rules
│   ├── ssh.py           # SSH configuration
│   ├── snmp.py          # SNMP configuration
│   ├── cert.py          # Certificate management
│   ├── ntp.py           # NTP synchronization
│   ├── action.py        # Action rules
│   ├── mqtt.py          # MQTT event bridge
│   ├── recording.py     # Recording profiles
│   ├── storage.py       # Remote storage
│   ├── geolocation.py   # GPS/location
│   ├── analytics.py     # Video analytics
│   ├── snapshot.py      # Best snapshot
│   ├── serverreport.py  # Server reports & debug
│   ├── oidc.py          # OpenID Connect
│   ├── oauth.py         # OAuth 2.0
│   ├── virtualhost.py   # Virtual hosts
│   ├── crypto_policy.py # TLS/cipher settings
│   └── networkpairing.py # Device pairing
└── devices/             # Device type implementations
    ├── __init__.py
    ├── base.py          # AxisDevice abstract base
    ├── camera.py        # AxisCamera
    ├── recorder.py      # AxisRecorder
    ├── intercom.py      # AxisIntercom
    └── speaker.py       # AxisSpeaker
```

## Core Components

### 1. VapixClient (`client.py`)

The `VapixClient` is the foundation of all device communication. It handles:

- HTTP/HTTPS connections using `httpx`
- Basic and Digest authentication
- Request formatting and response parsing
- Connection management via async context managers

```mermaid
classDiagram
    class VapixClient {
        +host: str
        +username: str
        +password: str
        +port: int
        +use_https: bool
        +timeout: float
        +verify_ssl: bool
        +use_digest_auth: bool
        -_client: httpx.AsyncClient
        +base_url: str
        +__aenter__() VapixClient
        +__aexit__() None
        +get(path, params) Response
        +post(path, data, json) Response
        +get_json(path, params) dict
        +post_json(path, data, json) dict
        +get_raw(path, params) bytes
        +get_binary(path, params, timeout) bytes
        +discover_apis() dict
        +check_connectivity() bool
    }
```

**Key Features:**
- Async context manager for proper resource cleanup
- Automatic HTTP to HTTPS based on port (443 = HTTPS)
- Support for both JSON and binary responses
- Custom timeout support for long-running operations

### 2. BaseAPI (`api/base.py`)

Abstract base class providing common functionality for all API modules.

```mermaid
classDiagram
    class BaseAPI {
        <<abstract>>
        -_client: VapixClient
        +__init__(client: VapixClient)
        #_get(path, params) Any
        #_post(path, data, json_data) Any
        #_get_raw(path, params) bytes
    }

    class BasicDeviceInfoAPI {
        +CGI_PATH: str
        +REST_PATH: str
        +get_info() BasicDeviceInfo
        +get_property(name) str
        +get_properties() DeviceProperties
        +is_axis_device() bool
        +get_firmware_version() str
        +get_serial_number() str
        +get_model() str
    }

    class ParamAPI {
        +get_params(group) dict
        +set_param(name, value) bool
        +get_friendly_name() str
        +get_location() str
    }

    class StreamAPI {
        +get_rtsp_config() RtspConfig
        +get_rtp_config() RtpConfig
        +get_stream_profiles() list
        +get_diagnostics(name) StreamDiagnostics
    }

    BaseAPI <|-- BasicDeviceInfoAPI
    BaseAPI <|-- ParamAPI
    BaseAPI <|-- StreamAPI
```

### 3. AxisDevice (`devices/base.py`)

Abstract base class that composes API modules to provide a unified device interface.

```mermaid
classDiagram
    class AxisDevice {
        <<abstract>>
        +device_type: DeviceType
        -_host: str
        -_client: VapixClient
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
        +serverreport: ServerReportAPI
        +oidc: OidcAPI
        +oauth: OAuthAPI
        +virtualhost: VirtualHostAPI
        +crypto_policy: CryptoPolicyAPI
        +networkpairing: NetworkPairingAPI
        +stream: StreamAPI
        +host: str
        +client: VapixClient
        +__aenter__() AxisDevice
        +__aexit__() None
        +get_info() BasicDeviceInfo
        +get_status() DeviceStatus
        +get_capabilities() DeviceCapabilities
        +get_device_specific_info()* dict
    }

    class AxisCamera {
        +device_type = CAMERA
        +get_device_specific_info() dict
        +get_snapshot_url(resolution) str
        +get_snapshot(resolution) bytes
        +get_video_stream_url(profile, codec) str
        +has_ptz() bool
        +has_audio() bool
        +has_analytics() bool
    }

    class AxisRecorder {
        +device_type = RECORDER
        +get_device_specific_info() dict
    }

    class AxisIntercom {
        +device_type = INTERCOM
        +get_device_specific_info() dict
    }

    class AxisSpeaker {
        +device_type = SPEAKER
        +get_device_specific_info() dict
    }

    AxisDevice <|-- AxisCamera
    AxisDevice <|-- AxisRecorder
    AxisDevice <|-- AxisIntercom
    AxisDevice <|-- AxisSpeaker
```

### 4. Configuration (`config.py`)

Configuration management with support for:

- YAML configuration files
- Environment variable interpolation (`${VAR_NAME}` syntax)
- XDG Base Directory specification
- Legacy path migration
- Multiple device definitions

```mermaid
flowchart LR
    subgraph "Configuration Sources"
        ENV[Environment Variables]
        DOTENV[.env File]
        YAML[config.yaml]
        CLI_ARGS[CLI Arguments]
    end

    subgraph "Configuration System"
        LOADER[Config Loader]
        INTERPOLATOR[Env Interpolator]
        VALIDATOR[Pydantic Validator]
    end

    subgraph "Output"
        APP_CONFIG[AppConfig]
        DEVICE_CONFIG[DeviceConfig]
    end

    ENV --> LOADER
    DOTENV --> LOADER
    YAML --> LOADER
    CLI_ARGS --> LOADER

    LOADER --> INTERPOLATOR
    INTERPOLATOR --> VALIDATOR
    VALIDATOR --> APP_CONFIG
    APP_CONFIG --> DEVICE_CONFIG
```

### 5. Exception Hierarchy (`exceptions.py`)

```mermaid
classDiagram
    class AxisError {
        <<base>>
    }

    class AxisConnectionError {
        Network/connectivity issues
    }

    class AxisAuthenticationError {
        401/403 errors
    }

    class AxisDeviceError {
        Device-side errors
    }

    class AxisConfigError {
        Configuration issues
    }

    class AxisApiNotSupportedError {
        API not available
    }

    AxisError <|-- AxisConnectionError
    AxisError <|-- AxisAuthenticationError
    AxisError <|-- AxisDeviceError
    AxisError <|-- AxisConfigError
    AxisError <|-- AxisApiNotSupportedError
```

## Design Patterns

### 1. Composition over Inheritance

API modules are composed into device classes rather than inherited:

```python
class AxisDevice:
    def __init__(self, ...):
        self._client = VapixClient(...)
        # Compose API modules
        self.device_info = BasicDeviceInfoAPI(self._client)
        self.params = ParamAPI(self._client)
        self.stream = StreamAPI(self._client)
        # ... 25+ more API modules
```

**Benefits:**
- Easy to add/remove API modules
- Clear dependency relationships
- Testable in isolation

### 2. Async Context Manager

All device and client classes support async context management:

```python
async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
    info = await camera.get_info()
    # Connection automatically closed on exit
```

**Benefits:**
- Proper resource cleanup
- Exception-safe connection handling
- Pythonic API

### 3. Factory Pattern

The CLI uses a factory pattern for device creation:

```mermaid
flowchart TD
    CLI[CLI Command] --> RESOLVE[resolve_device_config]
    RESOLVE --> GET_CLASS[get_device_class]
    GET_CLASS --> |camera| CAMERA[AxisCamera]
    GET_CLASS --> |recorder| RECORDER[AxisRecorder]
    GET_CLASS --> |intercom| INTERCOM[AxisIntercom]
    GET_CLASS --> |speaker| SPEAKER[AxisSpeaker]
```

### 4. Strategy Pattern

Authentication method selection:

```mermaid
flowchart LR
    CLIENT[VapixClient] --> |use_digest_auth=true| DIGEST[Digest Auth]
    CLIENT --> |use_digest_auth=false| BASIC[Basic Auth]
    DIGEST --> HTTPX[httpx.DigestAuth]
    BASIC --> HTTPX2[httpx.BasicAuth]
```

### 5. Template Method Pattern

API modules define template methods for common operations:

```python
class BaseAPI:
    async def _get(self, path, params):
        return await self._client.get_json(path, params)

    async def _post(self, path, data, json_data):
        return await self._client.post_json(path, data, json_data)
```

Subclasses implement specific API logic using these template methods.

## Data Flow

### Request Flow

```mermaid
sequenceDiagram
    participant CLI as CLI Command
    participant Device as AxisDevice
    participant API as API Module
    participant Client as VapixClient
    participant AXIS as AXIS Device

    CLI->>Device: get_info()
    Device->>API: device_info.get_info()
    API->>Client: _get("/axis-cgi/basicdeviceinfo.cgi")
    Client->>Client: Build URL + Auth
    Client->>AXIS: HTTP GET (Digest Auth)
    AXIS-->>Client: JSON Response
    Client-->>API: Parsed JSON
    API->>API: Parse to Model
    API-->>Device: BasicDeviceInfo
    Device-->>CLI: BasicDeviceInfo
```

### Configuration Flow

```mermaid
sequenceDiagram
    participant User as User
    participant CLI as CLI
    participant Config as ConfigLoader
    participant ENV as Environment
    participant YAML as YAML File

    User->>CLI: axiscam info --device front_camera
    CLI->>Config: load_config()
    Config->>ENV: load_env_file()
    ENV-->>Config: Environment loaded
    Config->>YAML: load_yaml_config()
    YAML-->>Config: Raw config
    Config->>Config: interpolate_env_vars()
    Config->>Config: normalize_devices_format()
    Config-->>CLI: AppConfig
    CLI->>CLI: get_device_config("front_camera")
    CLI->>CLI: Create device instance
```

### Report Generation Flow

```mermaid
sequenceDiagram
    participant CLI as CLI
    participant Device as AxisDevice
    participant APIs as API Modules
    participant Model as Pydantic Models
    participant Output as JSON/YAML

    CLI->>Device: Generate Report

    par Parallel API Calls
        Device->>APIs: get_info()
        Device->>APIs: get_time_info()
        Device->>APIs: get_lldp_info()
        Device->>APIs: get_stream_diagnostics()
        Device->>APIs: get_security_config()
        Device->>APIs: get_ntp_config()
    end

    APIs-->>Device: Individual results
    Device->>Model: Combine into report
    Model->>Output: Serialize
    Output-->>CLI: JSON/YAML string
```

## Module Relationships

### API Module Categories

```mermaid
mindmap
    root((API Modules))
        Device Identity
            BasicDeviceInfoAPI
            ParamAPI
            TimeAPI
        Network
            NetworkSettingsAPI
            LldpAPI
            FirewallAPI
        Security
            SshAPI
            SnmpAPI
            CertAPI
            OidcAPI
            OAuthAPI
            CryptoPolicyAPI
        Streaming
            StreamAPI
            AudioMulticastAPI
        Recording
            RecordingAPI
            RemoteStorageAPI
            BestSnapshotAPI
        Analytics
            VideoAnalyticsAPI
            AnalyticsMqttAPI
        Integration
            ActionAPI
            MqttBridgeAPI
            NetworkPairingAPI
            VirtualHostAPI
        Diagnostics
            LogsAPI
            ServerReportAPI
            NtpAPI
            GeolocationAPI
```

### Import Dependencies

```mermaid
flowchart BT
    subgraph "External Dependencies"
        httpx
        pydantic
        typer
        yaml
    end

    subgraph "Core"
        exceptions[exceptions.py]
        client[client.py]
        models[models.py]
        config[config.py]
    end

    subgraph "API Layer"
        base[api/base.py]
        api_modules[api/*.py]
    end

    subgraph "Device Layer"
        device_base[devices/base.py]
        devices[devices/*.py]
    end

    subgraph "CLI"
        cli[cli.py]
    end

    client --> httpx
    client --> exceptions

    models --> pydantic

    config --> yaml
    config --> pydantic

    base --> client
    api_modules --> base
    api_modules --> models

    device_base --> client
    device_base --> api_modules
    device_base --> models

    devices --> device_base

    cli --> typer
    cli --> devices
    cli --> config
    cli --> models
```

---

## See Also

- [API Modules Reference](./api-modules.md) - Detailed API module documentation
- [Device Classes](./device-classes.md) - Device type implementations
- [CLI Reference](./cli-reference.md) - Command-line interface documentation
- [Configuration Guide](./configuration.md) - Configuration system details
