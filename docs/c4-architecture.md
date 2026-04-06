# C4 Architecture: axis-cam

> **C4 Model** — Context, Containers, Components, Code  
> A hierarchical set of diagrams that describe software architecture at different levels of abstraction.

---

## Contents

1. [Level 1 — System Context](#level-1--system-context)
2. [Level 2 — Container Diagram](#level-2--container-diagram)
3. [Level 3 — Component Diagrams](#level-3--component-diagrams)
   - [CLI Application](#31-cli-application)
   - [Device Layer](#32-device-layer)
   - [API Layer](#33-api-layer)
   - [Transport Layer](#34-transport-layer)
   - [Configuration Manager](#35-configuration-manager)
4. [Level 4 — Code Level](#level-4--code-level)
   - [VapixClient class](#41-vapixclient)
   - [BaseAPI class](#42-baseapi)
   - [AxisDevice hierarchy](#43-axisdevice-hierarchy)
   - [Exception hierarchy](#44-exception-hierarchy)
   - [Configuration models](#45-configuration-models)
5. [Deployment View](#deployment-view)
6. [Request Lifecycle — Data Flow](#request-lifecycle--data-flow)
7. [Technology Choices](#technology-choices)

---

## Level 1 — System Context

The outermost view. Shows who uses `axis-cam` and what external systems it depends on.

```mermaid
C4Context
    title System Context — axis-cam

    Person(netAdmin, "Network Administrator", "Configures, monitors, and troubleshoots AXIS devices on a network.")
    Person(integrator, "Systems Integrator", "Automates device provisioning and configuration via scripting.")

    System(axiscam, "axis-cam", "Python CLI tool and library for managing AXIS network cameras, recorders, intercoms, and speakers via the VAPIX REST API.")

    System_Ext(axisDevices, "AXIS Device Fleet", "Physical AXIS network devices: cameras (M/P/Q series), recorders (S-series NVRs), intercoms (I-series), speakers (C-series). Expose VAPIX REST and CGI APIs over HTTP/HTTPS.")

    System_Ext(filesystem, "Local Filesystem", "Stores YAML device configuration at XDG-compliant paths (~/.config/axiscam/) and .env credential files.")

    Rel(netAdmin, axiscam, "Uses CLI commands", "Terminal / Shell")
    Rel(integrator, axiscam, "Imports as Python library", "Python API")
    Rel(axiscam, axisDevices, "Sends VAPIX REST and CGI requests", "HTTP/HTTPS, Basic/Digest Auth")
    Rel(axiscam, filesystem, "Reads device config and credentials", "YAML / .env")
```

**Key relationships:**

| Actor / System | Interaction | Protocol |
|---|---|---|
| Network Administrator | Runs CLI commands (e.g., `axiscam info`, `axiscam logs system`) | Terminal |
| Systems Integrator | Imports `axis_cam` package directly in Python scripts | Python import |
| AXIS Device Fleet | Bidirectional: axiscam sends requests, devices return data | HTTP/HTTPS + VAPIX |
| Local Filesystem | Read-only: config loading at startup | File I/O |

---

## Level 2 — Container Diagram

Zooms into the `axis-cam` system, showing its internal containers (deployable / runnable units).

```mermaid
C4Container
    title Container Diagram — axis-cam

    Person(user, "User", "Network admin or integrator")
    System_Ext(axisDevices, "AXIS Device Fleet", "Cameras, Recorders, Intercoms, Speakers")
    System_Ext(filesystem, "Filesystem", "~/.config/axiscam/config.yaml, .env")

    Container_Boundary(axiscam, "axis-cam Python Package") {
        Container(cli, "CLI Application", "Python / Typer + Rich", "Entry point axiscam. Provides sub-command groups: info, logs, network, security, services, download. Handles user I/O and output formatting.")

        Container(deviceLayer, "Device Layer", "Python / ABC + Composition", "Abstract AxisDevice base plus four concrete types: AxisCamera, AxisRecorder, AxisIntercom, AxisSpeaker. Orchestrates API modules.")

        Container(apiLayer, "API Layer", "Python / Async", "27 domain-specific API modules all extending BaseAPI. Each encapsulates a VAPIX API domain (device_info, network, security, streaming, etc.).")

        Container(transport, "Transport Layer", "Python / httpx", "VapixClient: async HTTP client wrapping httpx.AsyncClient. Handles Basic/Digest auth, request formatting, response validation, and error mapping.")

        Container(config, "Configuration Manager", "Python / Pydantic + PyYAML", "Loads and merges config from .env files, YAML files (XDG paths), and environment variables. Validates with Pydantic models.")

        Container(models, "Domain Models", "Python / Pydantic v2", "~2000 lines of typed Pydantic models for all VAPIX domains. Provides validation, serialisation, and type safety.")
    }

    Rel(user, cli, "Invokes CLI commands", "Terminal / axiscam entry point")
    Rel(user, deviceLayer, "Imports library directly", "Python API")
    Rel(cli, config, "Loads device configs", "Function calls")
    Rel(cli, deviceLayer, "Instantiates device objects via factory", "get_device_class()")
    Rel(deviceLayer, apiLayer, "Composes API modules", "Composition at __init__")
    Rel(apiLayer, transport, "Delegates HTTP calls", "_get() / _post() / _get_raw()")
    Rel(transport, axisDevices, "VAPIX REST/CGI requests", "HTTP/HTTPS")
    Rel(config, filesystem, "Reads config files", "File I/O")
```

---

## Level 3 — Component Diagrams

### 3.1 CLI Application

The `cli.py` module is a single-file Typer application with named sub-apps for each command group.

```mermaid
graph TD
    subgraph CLI["CLI Application (cli.py)"]
        main["main() — Entry Point<br/>axiscam script"]

        subgraph apps["Typer Sub-Apps"]
            appRoot["app<br/>Root Typer"]
            logsApp["logs_app<br/>log commands"]
            netApp["network_app<br/>network commands"]
            secApp["security_app<br/>firewall/SSH/cert"]
            svcApp["services_app<br/>SNMP/NTP"]
            dlApp["download_app<br/>reports/archives"]
        end

        subgraph helpers["CLI Helpers"]
            resolve["resolve_device_config()<br/>Config or host lookup"]
            factory["get_device_class()<br/>Type → Class factory"]
            runAsync["run_async()<br/>asyncio.run() bridge"]
        end

        subgraph commands["Commands (sample)"]
            cmdInfo["info command"]
            cmdLogs["logs system/access/audit/all"]
            cmdNet["network show/lldp"]
            cmdSec["security firewall/ssh/cert"]
            cmdSvc["services snmp/ntp"]
            cmdDl["download report/debug"]
        end
    end

    main --> appRoot
    appRoot --> logsApp
    appRoot --> netApp
    appRoot --> secApp
    appRoot --> svcApp
    appRoot --> dlApp

    cmdInfo --> resolve
    cmdInfo --> factory
    cmdInfo --> runAsync

    resolve --> configMgr[("Config Manager")]
    factory --> deviceLayer[("Device Layer")]
```

**CLI option type aliases used across all commands:**

| Alias | Flag | Purpose |
|---|---|---|
| `DeviceOption` | `--device / -d` | Named device from config |
| `HostOption` | `--host / -H` | Direct IP/hostname override |
| `UsernameOption` | `--username / -u` | Credential override |
| `PasswordOption` | `--password / -p` | Credential override |
| `PortOption` | `--port / -P` | HTTPS port (default 443) |
| `DigestOption` | `--digest / --no-digest` | Auth method (default Digest) |
| `JsonOption` | `--json / -j` | Machine-readable output |

---

### 3.2 Device Layer

The device hierarchy uses the Template Method pattern: `AxisDevice` provides all common operations; subclasses implement `get_device_specific_info()` and add device-type-specific methods.

```mermaid
graph TD
    subgraph DeviceLayer["Device Layer (devices/)"]
        base["AxisDevice (ABC)<br/>devices/base.py<br/>─────────────────<br/>Composes all 27 API modules<br/>get_info() | get_status()<br/>get_capabilities() | get_logs()<br/>capture_snapshot()<br/>get_stream_diagnostics()<br/>+ 20 more get_*() delegates<br/>─────────────────<br/>«abstract»<br/>get_device_specific_info()"]

        camera["AxisCamera<br/>devices/camera.py<br/>─────────────────<br/>device_type = CAMERA<br/>get_snapshot(resolution)<br/>get_video_stream_url()<br/>get_stream_profiles()<br/>has_ptz() | has_audio()<br/>has_analytics()"]

        recorder["AxisRecorder<br/>devices/recorder.py<br/>─────────────────<br/>device_type = RECORDER<br/>get_recording_groups()<br/>get_storage_info()<br/>get_disk_status()<br/>get_connected_cameras()<br/>has_remote_storage()"]

        intercom["AxisIntercom<br/>devices/intercom.py<br/>─────────────────<br/>device_type = INTERCOM<br/>get_audio_status()<br/>get_sip_config()<br/>get_snapshot(resolution)<br/>has_video() | has_sip()"]

        speaker["AxisSpeaker<br/>devices/speaker.py<br/>─────────────────<br/>device_type = SPEAKER<br/>get_audio_config()<br/>get_audio_clips()<br/>get_volume()<br/>has_multicast()"]
    end

    base -->|inherits| camera
    base -->|inherits| recorder
    base -->|inherits| intercom
    base -->|inherits| speaker

    base -.->|composes| apiModules[("27 API Modules<br/>in api/")]
    base -.->|creates| vapix[("VapixClient<br/>client.py")]
```

**Device type auto-detection from port:**

```
port == 443  →  use_https = True
port != 443  →  use_https = False
```

---

### 3.3 API Layer

All 27 API modules extend `BaseAPI`. Grouped by functional domain:

```mermaid
graph TD
    subgraph APILayer["API Layer (api/)"]
        baseAPI["BaseAPI (ABC)<br/>api/base.py<br/>─────────────<br/>_client: VapixClient<br/>_get(path, params)<br/>_post(path, data, json)<br/>_get_raw(path, params)"]

        subgraph core["Core Domain"]
            devInfo["BasicDeviceInfoAPI<br/>/axis-cgi/basicdeviceinfo.cgi"]
            paramAPI["ParamAPI<br/>/axis-cgi/param.cgi"]
            timeAPI["TimeAPI<br/>/axis-cgi/time.cgi"]
            logsAPI["LogsAPI<br/>/axis-cgi/systemlog.cgi"]
        end

        subgraph network["Network Domain"]
            lldpAPI["LldpAPI<br/>/axis-cgi/lldp/getall.cgi"]
            netAPI["NetworkSettingsAPI<br/>/config/rest/network/"]
        end

        subgraph security["Security Domain"]
            fwAPI["FirewallAPI<br/>/config/rest/firewall/"]
            sshAPI["SshAPI<br/>/config/rest/ssh/"]
            snmpAPI["SnmpAPI<br/>/axis-cgi/snmp.cgi"]
            certAPI["CertAPI<br/>/config/rest/certificate/"]
            ntpAPI["NtpAPI<br/>/config/rest/ntp/"]
            cryptoAPI["CryptoPolicyAPI<br/>/config/rest/crypto-policy/"]
        end

        subgraph streaming["Streaming Domain"]
            snapshotAPI["BestSnapshotAPI<br/>/axis-cgi/jpg/image.cgi"]
            streamAPI["StreamAPI<br/>RTSP/RTP diagnostics"]
        end

        subgraph recording["Recording Domain"]
            recAPI["RecordingAPI<br/>/config/rest/recording-group/"]
            storageAPI["RemoteStorageAPI<br/>/config/rest/remote-object-storage/"]
        end

        subgraph analytics["Analytics Domain"]
            analyticsAPI["VideoAnalyticsAPI<br/>/config/rest/analytics/"]
            analyticsMqttAPI["AnalyticsMqttAPI<br/>/config/rest/analytics-mqtt/"]
        end

        subgraph integration["Integration Domain"]
            mqttAPI["MqttBridgeAPI<br/>/config/rest/mqtt/"]
            actionAPI["ActionAPI<br/>/config/rest/action/"]
            geoAPI["GeolocationAPI<br/>/config/rest/geolocation/"]
            audioMCAPI["AudioMulticastAPI<br/>/config/rest/audio-multicast-ctrl/"]
        end

        subgraph auth["Auth Domain"]
            oidcAPI["OidcAPI<br/>/config/rest/oidc/"]
            oauthAPI["OAuthAPI<br/>/config/rest/oauth/"]
        end

        subgraph infra["Infrastructure Domain"]
            srAPI["ServerReportAPI<br/>/axis-cgi/serverreport.cgi"]
            vhostAPI["VirtualHostAPI<br/>/config/rest/virtualhost/"]
            npAPI["NetworkPairingAPI<br/>/config/rest/network-pairing/"]
        end
    end

    baseAPI --> core
    baseAPI --> network
    baseAPI --> security
    baseAPI --> streaming
    baseAPI --> recording
    baseAPI --> analytics
    baseAPI --> integration
    baseAPI --> auth
    baseAPI --> infra
```

**Complete API module inventory:**

| Module | Class | VAPIX Endpoint | Domain |
|---|---|---|---|
| `device_info` | `BasicDeviceInfoAPI` | `/axis-cgi/basicdeviceinfo.cgi` | Core |
| `param` | `ParamAPI` | `/axis-cgi/param.cgi` | Core |
| `time` | `TimeAPI` | `/axis-cgi/time.cgi` | Core |
| `logs` | `LogsAPI` | `/axis-cgi/systemlog.cgi` | Core |
| `lldp` | `LldpAPI` | `/axis-cgi/lldp/getall.cgi` | Network |
| `network` | `NetworkSettingsAPI` | `/config/rest/network/v1` | Network |
| `firewall` | `FirewallAPI` | `/config/rest/firewall/v1` | Security |
| `ssh` | `SshAPI` | `/config/rest/ssh/v1` | Security |
| `snmp` | `SnmpAPI` | `/axis-cgi/snmp.cgi` | Security |
| `cert` | `CertAPI` | `/config/rest/certificate/v1` | Security |
| `ntp` | `NtpAPI` | `/config/rest/ntp/v1` | Security |
| `crypto_policy` | `CryptoPolicyAPI` | `/config/rest/crypto-policy/v1` | Security |
| `snapshot` | `BestSnapshotAPI` | `/axis-cgi/jpg/image.cgi` | Streaming |
| `stream` | `StreamAPI` + `StreamDiagnostics` | RTSP/RTP params | Streaming |
| `recording` | `RecordingAPI` | `/config/rest/recording-group/v2` | Recording |
| `storage` | `RemoteStorageAPI` | `/config/rest/remote-object-storage/v1` | Recording |
| `analytics` | `VideoAnalyticsAPI` | `/config/rest/analytics/v1` | Analytics |
| `analytics_mqtt` | `AnalyticsMqttAPI` | `/config/rest/analytics-mqtt/v1` | Analytics |
| `mqtt` | `MqttBridgeAPI` | `/config/rest/mqtt/v1` | Integration |
| `action` | `ActionAPI` | `/config/rest/action/v1` | Integration |
| `geolocation` | `GeolocationAPI` | `/config/rest/geolocation/v1` | Integration |
| `audio_multicast` | `AudioMulticastAPI` | `/config/rest/audio-multicast-ctrl/v1beta` | Integration |
| `oidc` | `OidcAPI` | `/config/rest/oidc/v1` | Auth |
| `oauth` | `OAuthAPI` | `/config/rest/oauth/v1` | Auth |
| `serverreport` | `ServerReportAPI` | `/axis-cgi/serverreport.cgi` | Diagnostics |
| `virtualhost` | `VirtualHostAPI` | `/config/rest/virtualhost/v1` | Infrastructure |
| `networkpairing` | `NetworkPairingAPI` | `/config/rest/network-pairing/v1` | Infrastructure |

---

### 3.4 Transport Layer

`VapixClient` is the sole HTTP transport, wrapping `httpx.AsyncClient`. Designed exclusively as an async context manager.

```mermaid
graph TD
    subgraph Transport["Transport Layer (client.py)"]
        vc["VapixClient<br/>─────────────────────────<br/>host, username, password<br/>port: int = 80<br/>use_https: bool = False<br/>timeout: float = 30.0<br/>verify_ssl: bool = False<br/>use_digest_auth: bool = False<br/>_client: httpx.AsyncClient | None"]

        subgraph lifecycle["Connection Lifecycle"]
            enter["__aenter__()<br/>Creates httpx.AsyncClient<br/>Selects BasicAuth or DigestAuth"]
            exit["__aexit__()<br/>Calls aclose() on inner client"]
            ensure["_ensure_connected()<br/>Guards all request methods"]
        end

        subgraph methods["Request Methods"]
            get["get(path, params)<br/>→ httpx.Response"]
            post["post(path, data, json)<br/>→ httpx.Response"]
            getJson["get_json(path, params)<br/>→ dict[str, Any]"]
            postJson["post_json(path, data, json_data)<br/>→ dict[str, Any]"]
            getRaw["get_raw(path, params)<br/>→ bytes"]
            getBinary["get_binary(path, params, timeout)<br/>→ bytes (custom timeout)"]
        end

        subgraph errorHandling["Error Mapping"]
            check["_check_response(response)<br/>401 → AxisAuthenticationError<br/>403 → AxisAuthenticationError<br/>≥400 → AxisDeviceError"]
            connErr["httpx.ConnectError<br/>→ AxisConnectionError"]
            timeoutErr["httpx.TimeoutException<br/>→ AxisConnectionError"]
        end

        subgraph discovery["Discovery"]
            discoverAPIs["discover_apis()<br/>/config/discover/apis.json"]
            checkConn["check_connectivity()<br/>/axis-cgi/basicdeviceinfo.cgi"]
        end
    end

    vc --> lifecycle
    vc --> methods
    methods --> errorHandling
    vc --> discovery
```

**Authentication strategy selection:**

```
use_digest_auth = True   →   httpx.DigestAuth(username, password)
use_digest_auth = False  →   httpx.BasicAuth(username, password)
```

---

### 3.5 Configuration Manager

`config.py` implements a layered config loading pipeline with Pydantic validation at the boundary.

```mermaid
graph TD
    subgraph ConfigMgr["Configuration Manager (config.py)"]
        subgraph sources["Config Sources (precedence: high → low)"]
            cli_args["1. CLI flags<br/>--host / --username / --password"]
            env_vars["2. Environment Variables<br/>AXIS_HOST, AXIS_USERNAME,<br/>AXIS_PASSWORD, AXIS_PORT"]
            env_file["3. .env File<br/>~/.config/axiscam/.env"]
            yaml_file["4. YAML Config File<br/>~/.config/axiscam/config.yaml"]
            legacy["5. Legacy Path<br/>~/.config/axis/config.yaml<br/>(with deprecation warning)"]
            defaults["6. System Defaults<br/>port=443, ssl_verify=False,<br/>timeout=30.0, type=camera"]
        end

        subgraph pipeline["Load Pipeline"]
            loadEnv["load_env_file()<br/>Reads .env → os.environ<br/>Never overwrites existing vars"]
            loadYaml["load_yaml_config(path)<br/>yaml.safe_load()<br/>+ interpolate_env_vars()<br/>+ normalize_devices_format()"]
            loadEnvCfg["load_env_config()<br/>AXIS_* vars → dict"]
            loadCfg["load_config() @lru_cache<br/>Merges all sources<br/>→ AppConfig.model_validate()"]
        end

        subgraph models_cfg["Pydantic Models"]
            devCfg["DeviceConfig<br/>host (alias: address)<br/>username, password: SecretStr<br/>port=443, ssl_verify=False<br/>device_type (validated+mapped)<br/>name, vendor, model"]
            appCfg["AppConfig<br/>default_device: str | None<br/>timeout: float = 30.0<br/>devices: dict[str, DeviceConfig]"]
        end

        subgraph interpolation["Environment Interpolation"]
            interp["interpolate_env_vars()<br/>Supports \${VAR_NAME} syntax<br/>Recursive: str, dict, list"]
        end

        subgraph xdg["XDG Path Resolution"]
            getConfigDir["get_config_dir()<br/>AXIS_CONFIG_DIR env override<br/>XDG_CONFIG_HOME/axiscam/<br/>XDG_CONFIG_HOME/axis/ (legacy)"]
            getDataDir["get_data_dir()<br/>XDG_DATA_HOME/axiscam/<br/>~/.local/share/axiscam/"]
        end
    end

    sources --> pipeline
    pipeline --> models_cfg
    loadYaml --> interpolation
    pipeline --> xdg
```

**Device type mapping (normalisation):**

Accepts human-readable descriptions and maps them to canonical types:

| Input (case-insensitive) | Canonical type |
|---|---|
| `camera`, `dome camera`, `ptz camera`, `thermal camera` | `camera` |
| `recorder`, `nvr`, `network video recorder`, `s3008`, `s3016` | `recorder` |
| `intercom`, `network video intercom`, `door station` | `intercom` |
| `speaker`, `network speaker`, `horn speaker`, `network audio` | `speaker` |

---

## Level 4 — Code Level

Class diagrams showing the key interfaces, method signatures, and relationships.

### 4.1 VapixClient

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
        -_client: httpx.AsyncClient | None

        +base_url: str [property]

        +__aenter__() VapixClient
        +__aexit__(exc_type, exc_val, exc_tb) None

        +get(path, params) httpx.Response
        +post(path, data, json) httpx.Response
        +get_json(path, params) dict
        +post_json(path, data, json_data) dict
        +get_raw(path, params) bytes
        +get_binary(path, params, timeout) bytes

        +discover_apis() dict
        +check_connectivity() bool

        -_ensure_connected() httpx.AsyncClient
        -_check_response(response) None
    }

    class BasicAuth {
        <<httpx>>
    }
    class DigestAuth {
        <<httpx>>
    }
    class AsyncClient {
        <<httpx>>
    }

    VapixClient --> AsyncClient : wraps
    VapixClient --> BasicAuth : selects when use_digest_auth=False
    VapixClient --> DigestAuth : selects when use_digest_auth=True
```

### 4.2 BaseAPI

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
        +get_info() BasicDeviceInfo
    }
    class ParamAPI {
        +get_friendly_name() str
        +get_location() str
    }
    class LogsAPI {
        -device_name: str
        +get_logs(log_type, max_entries) LogReport
        +get_system_logs(max_entries) LogReport
    }
    class NetworkSettingsAPI {
        +get_config() NetworkConfig
    }
    class FirewallAPI {
        +get_config() FirewallConfig
    }
    class BestSnapshotAPI {
        +capture(resolution, compression, camera) bytes
        +get_config() BestSnapshotConfig
    }
    class StreamAPI {
        +get_diagnostics(device_name) StreamDiagnostics
    }
    class ServerReportAPI {
        +download_report(format, timeout) ServerReport
        +get_debug_archive(timeout) ServerReport
    }

    BaseAPI <|-- BasicDeviceInfoAPI
    BaseAPI <|-- ParamAPI
    BaseAPI <|-- LogsAPI
    BaseAPI <|-- NetworkSettingsAPI
    BaseAPI <|-- FirewallAPI
    BaseAPI <|-- BestSnapshotAPI
    BaseAPI <|-- StreamAPI
    BaseAPI <|-- ServerReportAPI
    BaseAPI <|-- "... 19 more API classes"
```

### 4.3 AxisDevice Hierarchy

```mermaid
classDiagram
    class AxisDevice {
        <<abstract>>
        +device_type: DeviceType = UNKNOWN
        -_host: str
        -_client: VapixClient
        -_capabilities: DeviceCapabilities | None
        -_device_info_cache: BasicDeviceInfo | None

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

        +host: str [property]
        +client: VapixClient [property]

        +__aenter__() Self
        +__aexit__(exc_type, exc_val, exc_tb) None

        +get_info() BasicDeviceInfo
        +get_status() DeviceStatus
        +get_capabilities() DeviceCapabilities
        +get_logs(log_type, max_entries) LogReport
        +capture_snapshot(resolution, compression, camera) bytes
        +download_server_report(format, timeout) ServerReport
        +get_stream_diagnostics(device_name) StreamDiagnostics
        +check_connectivity() bool

        +get_device_specific_info()* dict
    }

    class AxisCamera {
        +device_type = CAMERA
        +get_snapshot(resolution) bytes
        +get_snapshot_url(resolution) str
        +get_video_stream_url(profile, codec) str
        +get_stream_profiles() list
        +get_video_sources() list
        +has_ptz() bool
        +has_audio() bool
        +has_analytics() bool
        +get_device_specific_info() dict
    }

    class AxisRecorder {
        +device_type = RECORDER
        +RECORDING_GROUP_PATH: str
        +REMOTE_STORAGE_PATH: str
        +get_recording_groups() list
        +get_recording_group(group_id) dict
        +get_storage_info() dict
        +get_disk_status() list
        +get_connected_cameras() list
        +has_remote_storage() bool
        +get_device_specific_info() dict
    }

    class AxisIntercom {
        +device_type = INTERCOM
        +AUDIO_MULTICAST_PATH: str
        +get_audio_status() dict
        +get_audio_device_info() dict
        +get_audio_multicast_config() AudioMulticastConfig
        +get_sip_config() dict
        +get_snapshot(resolution) bytes
        +get_snapshot_url(resolution) str
        +has_video() bool
        +has_sip() bool
        +get_device_specific_info() dict
    }

    class AxisSpeaker {
        +device_type = SPEAKER
        +AUDIO_MULTICAST_PATH: str
        +get_audio_config() dict
        +get_audio_clips() list
        +get_audio_status() dict
        +get_audio_device_info() dict
        +get_volume() int | None
        +has_multicast() bool
        +get_device_specific_info() dict
    }

    AxisDevice <|-- AxisCamera
    AxisDevice <|-- AxisRecorder
    AxisDevice <|-- AxisIntercom
    AxisDevice <|-- AxisSpeaker

    AxisDevice *-- VapixClient : owns
    AxisDevice *-- BaseAPI : composes 27
```

### 4.4 Exception Hierarchy

```mermaid
classDiagram
    class Exception {
        <<Python built-in>>
    }

    class AxisError {
        +message: str
        Base for all axis-cam exceptions.
        Catch-all handler target.
    }

    class AxisConnectionError {
        Network unreachable, refused,
        timeout, DNS failure.
        Maps from httpx.ConnectError
        and httpx.TimeoutException.
    }

    class AxisAuthenticationError {
        HTTP 401 – bad credentials.
        HTTP 403 – insufficient permissions.
    }

    class AxisDeviceError {
        HTTP 4xx/5xx (non-auth).
        Invalid JSON response.
        Device-side failures.
    }

    class AxisConfigError {
        Missing config files.
        Invalid YAML.
        Pydantic validation errors.
    }

    class AxisApiNotSupportedError {
        API not available on this
        device type or firmware version.
    }

    Exception <|-- AxisError
    AxisError <|-- AxisConnectionError
    AxisError <|-- AxisAuthenticationError
    AxisError <|-- AxisDeviceError
    AxisError <|-- AxisConfigError
    AxisError <|-- AxisApiNotSupportedError
```

### 4.5 Configuration Models

```mermaid
classDiagram
    class AppConfig {
        +model_config: frozen=True
        +default_device: str | None
        +timeout: float = 30.0
        +devices: dict~str, DeviceConfig~
    }

    class DeviceConfig {
        +model_config: frozen=True, populate_by_name=True
        +host: str [alias: address]
        +username: str
        +password: SecretStr
        +port: int = 443
        +ssl_verify: bool = False
        +device_type: str = "camera" [alias: type]
        +name: str | None
        +vendor: str = "axis"
        +model: str | None

        +validate_host(v) str
        +validate_device_type(v) str
        +validate_vendor(v) str
    }

    AppConfig *-- DeviceConfig : devices dict
```

---

## Deployment View

How `axis-cam` is installed and invoked in practice:

```mermaid
graph TD
    subgraph userMachine["User Machine (macOS / Linux)"]
        subgraph pythonEnv["Python 3.12+ Environment"]
            uvTool["uv tool install axis-cam<br/>or: pip install axis-cam"]
            venv[".venv / isolated env<br/>managed by uv"]
            pkg["axis_cam package<br/>src/axis_cam/"]
        end

        subgraph entrypoints["Entry Points"]
            cliEP["axiscam (CLI script)<br/>→ axis_cam.cli:main"]
            libEP["import axis_cam<br/>Python library usage"]
        end

        subgraph configFiles["Config Files (XDG)"]
            configYaml["~/.config/axiscam/config.yaml<br/>Device inventory + settings"]
            envFile["~/.config/axiscam/.env<br/>Credentials (AXIS_* vars)"]
        end
    end

    subgraph network["Network Segment"]
        direction LR
        cam["AXIS Camera<br/>(M/P/Q series)"]
        nvr["AXIS Recorder<br/>(S-series NVR)"]
        intercom["AXIS Intercom<br/>(I-series)"]
        speaker["AXIS Speaker<br/>(C-series)"]
    end

    uvTool --> venv
    venv --> pkg
    pkg --> cliEP
    pkg --> libEP

    configYaml --> pkg
    envFile --> pkg

    cliEP -->|"HTTPS (port 443)<br/>or HTTP (other port)<br/>Basic / Digest Auth"| cam
    cliEP -->|HTTPS| nvr
    cliEP -->|HTTPS| intercom
    cliEP -->|HTTPS| speaker
```

**Installation methods:**

| Method | Command | Use case |
|---|---|---|
| uv tool (recommended) | `uv tool install axis-cam` | Isolated global CLI install |
| uv in project | `uv add axis-cam` | Library dependency |
| Development | `uv sync --all-extras` | Local dev with test deps |
| pip | `pip install axis-cam` | Standard install |

**Runtime dependencies installed:**

| Package | Version | Role |
|---|---|---|
| `httpx` | ≥0.27.0 | Async HTTP client with auth |
| `pydantic` | ≥2.0.0 | Data validation and models |
| `pydantic-settings` | ≥2.0.0 | Settings management |
| `typer` | ≥0.12.0 | CLI framework |
| `rich` | ≥13.0.0 | Terminal output formatting |
| `pyyaml` | ≥6.0.0 | YAML config parsing |
| `platformdirs` | ≥4.0.0 | XDG path resolution |
| `shellingham` | ≥1.5.0 | Shell detection for Typer |

---

## Request Lifecycle — Data Flow

How a single CLI command flows through all layers end-to-end.

### Happy Path: `axiscam info --device front_door`

```mermaid
sequenceDiagram
    actor User
    participant CLI as cli.py<br/>device_info()
    participant Config as config.py<br/>load_config()
    participant Factory as get_device_class()
    participant Device as AxisCamera<br/>(AxisDevice)
    participant API as BasicDeviceInfoAPI<br/>(BaseAPI)
    participant Client as VapixClient
    participant httpx as httpx.AsyncClient
    participant AXIS as AXIS Camera<br/>(192.168.1.10)

    User->>CLI: axiscam info --device front_door

    CLI->>Config: get_device_config("front_door")
    Config->>Config: load_env_file() → os.environ
    Config->>Config: load_yaml_config(~/.config/axiscam/config.yaml)
    Config->>Config: interpolate_env_vars() → resolve ${AXIS_ROOT_USER_PASSWORD}
    Config-->>CLI: DeviceConfig(host="192.168.1.10", port=443, type="camera", ...)

    CLI->>Factory: get_device_class("camera")
    Factory-->>CLI: AxisCamera class

    CLI->>Device: async with AxisCamera("192.168.1.10", "admin", "secret", 443)
    Device->>Client: VapixClient(host, user, pass, port=443, use_https=True)
    Device->>Client: __aenter__() → DigestAuth
    Client->>httpx: AsyncClient(auth=DigestAuth, timeout=30.0, verify=False)

    CLI->>Device: await dev.get_info()
    Device->>Device: check _device_info_cache (None)
    Device->>API: device_info.get_info()
    API->>Client: _get("/axis-cgi/basicdeviceinfo.cgi")
    Client->>Client: _ensure_connected()
    Client->>httpx: GET https://192.168.1.10:443/axis-cgi/basicdeviceinfo.cgi
    httpx->>AXIS: HTTP GET + Digest Auth challenge/response
    AXIS-->>httpx: 200 OK + JSON payload
    httpx-->>Client: httpx.Response
    Client->>Client: _check_response() → OK (200)
    Client-->>API: dict (parsed JSON)
    API-->>Device: BasicDeviceInfo model
    Device->>Device: cache → _device_info_cache
    Device-->>CLI: BasicDeviceInfo

    CLI->>CLI: Build Rich Table with device fields
    CLI->>User: Rendered table to terminal

    CLI->>Device: __aexit__()
    Device->>Client: __aexit__()
    Client->>httpx: aclose()
```

### Error Path: Authentication Failure

```mermaid
sequenceDiagram
    participant Client as VapixClient
    participant httpx as httpx.AsyncClient
    participant AXIS as AXIS Camera

    Client->>httpx: GET /axis-cgi/basicdeviceinfo.cgi
    httpx->>AXIS: HTTP GET
    AXIS-->>httpx: 401 Unauthorized
    httpx-->>Client: httpx.Response(status=401)
    Client->>Client: _check_response() → status_code == 401
    Client->>Client: raise AxisAuthenticationError("Authentication failed for 192.168.1.10...")
    Note over Client: Exception propagates up<br/>through BaseAPI → AxisDevice → CLI
    Client-->>CLI: AxisAuthenticationError
    CLI->>CLI: console.print("[red]Error:[/red]...")
```

---

## Technology Choices

| Decision | Choice | Rationale |
|---|---|---|
| HTTP client | `httpx` (async) | Native async support; built-in Basic and Digest auth; cleaner API than `aiohttp`; `respx` for test mocking |
| Data validation | `pydantic` v2 | Type-safe models, automatic validation, `SecretStr` for password masking, frozen configs |
| CLI framework | `typer` | Declarative, type-hint driven; generates `--help` automatically; integrates with Rich |
| Terminal output | `rich` | Tables, panels, trees, colour — zero boilerplate for professional terminal UX |
| Config format | YAML | Human-editable device inventories; supports `${VAR}` interpolation for secrets |
| Config paths | XDG Base Directory | Platform-correct paths on Linux and macOS; respects `XDG_CONFIG_HOME` |
| Auth strategy | Basic / Digest (configurable) | VAPIX supports both; Digest default avoids plaintext credential exposure |
| Async pattern | `async with` context manager | Guarantees connection teardown even on exception; pairs naturally with httpx |
| Composition over inheritance | API modules composed into Device | Each API module is independently testable; devices gain capabilities by composition not deep inheritance |
| Abstract base for devices | `abc.ABC` + `@abstractmethod` | Enforces `get_device_specific_info()` contract on all device subclasses |
| Package manager | `uv` + `hatchling` | Fast dependency resolution; `pyproject.toml`-native; `uv tool install` for isolated CLI |
| Python version | 3.12+ | `X | Y` union syntax, `Self` type, latest `asyncio`; no legacy compatibility burden |
| Build backend | `hatchling` | Simple, PEP 517/660 compliant; works seamlessly with `uv` |
| Secrets handling | `SecretStr` + `.env` file | Prevents accidental password logging; `.env` in config dir keeps credentials out of YAML |
