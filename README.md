# AXIS Camera Manager (axiscam)

A powerful CLI tool for managing AXIS cameras, recorders, intercoms, and speakers via the VAPIX API. Designed for network administrators and integrators who need efficient device management and diagnostics.

## Features

- **Multi-Device Support**: Cameras, recorders (NVR), intercoms, and speakers
- **Comprehensive Device Info**: Serial numbers, firmware, capabilities
- **Stream Diagnostics**: RTSP/RTP configuration, stream profiles - essential for third-party integration
- **Network Discovery**: LLDP neighbor discovery for switch port mapping
- **Log Retrieval**: System, access, and audit logs with severity filtering
- **Device Reports**: Generate comprehensive JSON/YAML configuration reports
- **Diagnostic Downloads**: Server reports and debug archives for AXIS support
- **Security Configuration**: Firewall, SSH, certificates, SNMP, NTP
- **Authentication**: Digest (default) and Basic authentication support
- **Async Operations**: Efficient parallel communication with multiple devices
- **Configuration Management**: YAML config with environment variable interpolation
- **Legacy Support**: Automatic migration from `~/.config/axis/` to `~/.config/axiscam/`

## Installation

### Using uv (Recommended)

```bash
# Install as a tool
uv tool install .

# Or install in a virtual environment
uv venv
uv sync
source .venv/bin/activate
```

### Using pip

```bash
pip install .
```

### Using pipx (isolated environment)

```bash
pipx install .
```

## Quick Start

```bash
# 1. Initialize configuration
axiscam init

# 2. Edit ~/.config/axiscam/config.yaml with your devices

# 3. List configured devices
axiscam devices

# 4. Get device info
axiscam info --device front_camera

# 5. Generate a report
axiscam report --device front_camera --format json
```

## Configuration

### Configuration File Location

- **Primary**: `~/.config/axiscam/config.yaml`
- **Legacy (auto-detected)**: `~/.config/axis/config.yaml`
- **Override via environment**: `AXIS_CONFIG_DIR`

### Configuration Format

```yaml
# ~/.config/axiscam/config.yaml
default_device: front_camera
timeout: 30.0

devices:
  front_camera:
    name: "Front Door Camera"
    vendor: axis
    model: M3216-LVE
    type: camera
    address: 192.168.1.10
    port: 443
    username: ${AXIS_ROOT_USER_NAME}
    password: ${AXIS_ROOT_USER_PASSWORD}
    ssl_verify: false

  main_nvr:
    name: "Main Recorder"
    vendor: axis
    model: S3008
    type: recorder
    address: 192.168.1.100
    port: 443
    username: ${AXIS_ROOT_USER_NAME}
    password: ${AXIS_ROOT_USER_PASSWORD}
    ssl_verify: false

  front_intercom:
    name: "Front Door"
    vendor: axis
    model: I8016-LVE
    type: intercom
    address: 192.168.1.12
    port: 443
    username: ${AXIS_ROOT_USER_NAME}
    password: ${AXIS_ROOT_USER_PASSWORD}
    ssl_verify: false

  office_speaker:
    name: "Office"
    vendor: axis
    model: C1410
    type: speaker
    address: 192.168.1.45
    port: 443
    username: ${AXIS_ROOT_USER_NAME}
    password: ${AXIS_ROOT_USER_PASSWORD}
    ssl_verify: false
```

### Legacy List Format (Auto-Converted)

The tool also supports the legacy list format used in `~/.config/axis/config.yaml`:

```yaml
devices:
  - name: 'Front Camera'
    vendor: AXIS
    model: "M3216-LVE"
    type: "Dome Camera"
    address: 192.168.1.10
    port: 80
    username: '${AXIS_ROOT_USER_NAME}'
    password: '${AXIS_ROOT_USER_PASSWORD}'
```

This format is automatically converted to the dict format internally.

### Environment Variables

```bash
# Credentials (recommended: use .env file)
export AXIS_ROOT_USER_NAME=root
export AXIS_ROOT_USER_PASSWORD=your_secure_password

# Config override
export AXIS_CONFIG_DIR=/custom/path

# Direct device connection (bypasses config)
export AXIS_HOST=192.168.1.10
export AXIS_USERNAME=root
export AXIS_PASSWORD=password
export AXIS_PORT=443
```

### Secrets Management

Store credentials in `~/.config/axiscam/.env`:

```bash
# ~/.config/axiscam/.env
AXIS_ROOT_USER_NAME=root
AXIS_ROOT_USER_PASSWORD=your_secure_password
```

Source before running:
```bash
source ~/.config/axiscam/.env
axiscam info --device front_camera
```

## CLI Reference

### Global Options

| Option | Short | Description |
|--------|-------|-------------|
| `--device` | `-d` | Device name from config or IP address |
| `--host` | `-H` | Device IP (overrides --device) |
| `--username` | `-u` | Authentication username |
| `--password` | `-p` | Authentication password |
| `--port` | `-P` | Port number (default: 443) |
| `--digest/--no-digest` | | Authentication mode (default: digest) |
| `--json` | `-j` | Output as JSON |

**Note**: Digest authentication is enabled by default as most AXIS devices require it. Use `--no-digest` for devices that only support Basic authentication.

### Core Commands

```bash
# Show device information
axiscam info --device camera1

# Check device connectivity
axiscam status --device camera1

# List available VAPIX APIs
axiscam apis --device camera1

# List device parameters
axiscam params --device camera1 --group Network

# Export all parameters as JSON
axiscam params --device camera1 --export --output params.json

# Show LLDP neighbors (switch port discovery)
axiscam lldp --device camera1

# Generate device report
axiscam report --device camera1 --format json --output report.json

# Generate full report with all configurations
axiscam report --device camera1 --full --output full_report.json
```

### Report Command Options

| Option | Short | Description |
|--------|-------|-------------|
| `--device` | `-d` | Device name or IP address |
| `--output` | `-o` | Output file path |
| `--format` | `-f` | Output format: `json` (default), `yaml`, `text` |
| `--full` | | Include all configurations (SSH, SNMP, certs, MQTT, actions, recording, storage, geolocation, analytics, OIDC, OAuth, crypto policy) |

### Download Commands

Download diagnostic reports and debug archives from AXIS devices.

```bash
# Download server report (ZIP with snapshot image)
axiscam download report --device camera1 --output ~/report.zip

# Download server report as plain text
axiscam download report --device camera1 --format text --output ~/report.txt

# Download server report as ZIP without image
axiscam download report --device camera1 --format zip --output ~/report.zip

# Download debug archive (comprehensive diagnostics for AXIS support)
axiscam download debug --device camera1 --output ~/debug.tgz

# With extended timeout for large archives
axiscam download debug --device camera1 --output ~/debug.tgz --timeout 300
```

#### Server Report Options (`axiscam download report`)

| Option | Short | Description |
|--------|-------|-------------|
| `--device` | `-d` | Device name or IP address |
| `--output` | `-o` | Output file (auto-generates if not specified) |
| `--format` | `-f` | Report format: `zip_with_image` (default), `zip`, `text` |
| `--timeout` | `-t` | Download timeout in seconds (default: 60) |
| `--digest/--no-digest` | | Authentication mode (default: digest) |

#### Debug Archive Options (`axiscam download debug`)

| Option | Short | Description |
|--------|-------|-------------|
| `--device` | `-d` | Device name or IP address |
| `--output` | `-o` | Output file (auto-generates if not specified) |
| `--timeout` | `-t` | Download timeout in seconds (default: 120) |
| `--digest/--no-digest` | | Authentication mode (default: digest) |

**Note**: Debug archives can be large (10+ MB) and take time to generate. Use extended timeouts for slower devices or large configurations.

### Stream Diagnostics

Essential for troubleshooting third-party integration (e.g., UniFi AI Port):

```bash
# Show RTSP, RTP, and stream profile configuration
axiscam stream show --device camera1

# Output as JSON for scripting
axiscam stream show --device camera1 --json
```

Output includes:
- RTSP port and authentication
- RTP port range and multicast settings
- Stream profiles (codec, resolution, FPS, bitrate, GOP)

### Log Commands

```bash
# System logs
axiscam logs system --device camera1 --lines 50

# Access logs (HTTP requests)
axiscam logs access --device camera1 --lines 20

# Audit logs (configuration changes)
axiscam logs audit --device camera1

# All logs combined
axiscam logs all --device camera1 --lines 100
```

### Network Commands

```bash
# Show network configuration
axiscam network show --device camera1

# Show DNS settings
axiscam network dns --device camera1

# Show interface details
axiscam network interface --device camera1
```

### Security Commands

```bash
# Firewall status and rules
axiscam security firewall --device camera1

# SSH configuration
axiscam security ssh --device camera1

# Certificate information
axiscam security cert --device camera1
```

### Service Commands

```bash
# SNMP configuration
axiscam services snmp --device camera1

# NTP configuration
axiscam services ntp --device camera1
```

### Configuration Commands

```bash
# Show current configuration
axiscam config

# Initialize config with template
axiscam init

# Force overwrite existing config
axiscam init --force

# Migrate from legacy path (~/.config/axis/)
axiscam migrate

# List all configured devices
axiscam devices
```

## Device Types

### Camera (`type: camera`)

Full support for:
- Video streaming (RTSP, RTP, MJPEG)
- PTZ control (if equipped)
- Video analytics
- Snapshots
- Recording profiles

### Recorder (`type: recorder`)

Support for NVRs like AXIS S3008:
- Recording status
- Storage management
- Connected camera management
- Playback configuration

### Intercom (`type: intercom`)

Support for door stations like AXIS I8016-LVE:
- SIP configuration
- Audio/video calls
- I/O ports (door lock, etc.)
- Event handling

### Speaker (`type: speaker`)

Support for network speakers like AXIS C1410:
- Audio streaming
- Multicast configuration
- Zone management
- Audio clips

## Troubleshooting

### Connection Issues

```bash
# Test basic connectivity
axiscam status --device camera1

# Check if HTTPS is required
axiscam status --host 192.168.1.10 --port 80 -u admin -p pass

# Try Basic auth if Digest fails (rare)
axiscam info --device camera1 --no-digest
```

### Authentication Errors

1. Verify credentials are correct
2. Check if account is locked (too many failed attempts)
3. Digest authentication is default; try `--no-digest` for older devices
4. Verify user has admin privileges

### SSL Certificate Errors

The default `ssl_verify: false` bypasses certificate verification. For production:

```yaml
devices:
  secure_camera:
    address: camera.example.com
    port: 443
    ssl_verify: true  # Requires valid certificate
```

### Port 80 vs 443

- **Port 443 (HTTPS)**: Default, recommended for security
- **Port 80 (HTTP)**: Legacy, sends credentials in clear text

```yaml
devices:
  legacy_camera:
    address: 192.168.1.10
    port: 80  # HTTP - not recommended
```

### Config Migration

If using legacy `~/.config/axis/` path:

```bash
# Auto-migrate to new path
axiscam migrate

# Or manually copy
cp -r ~/.config/axis/* ~/.config/axiscam/
```

### Debug Information

```bash
# Get comprehensive device configuration report
axiscam report --device camera1 --full --output config_report.json

# Download server report (diagnostic info + snapshot)
axiscam download report --device camera1 --output server_report.zip

# Download debug archive (comprehensive logs for AXIS support)
axiscam download debug --device camera1 --output debug.tgz --timeout 180
```

### Common Error Messages

| Error | Solution |
|-------|----------|
| `Connection refused` | Check IP/port, device may be offline |
| `401 Unauthorized` | Verify username/password |
| `SSL certificate verify failed` | Set `ssl_verify: false` or install cert |
| `No device specified` | Use `--device` or `--host` option |
| `Device not found in config` | Check device name in config.yaml |

## API Coverage

This tool covers the following AXIS VAPIX APIs:

| API | Description | Status |
|-----|-------------|--------|
| basic-device-info | Device identification | Full |
| param | Device parameters | Full |
| time | Time/timezone/NTP | Full |
| network-settings | Network configuration | Full |
| lldp | Neighbor discovery | Full |
| log | System/access/audit logs | Full |
| firewall | Firewall rules | Full |
| ssh | SSH configuration | Full |
| snmp | SNMP configuration | Full |
| cert | Certificate management | Full |
| ntp | NTP synchronization | Full |
| action | Action rules | Full |
| mqtt | Event bridge | Full |
| recording | Recording profiles | Full |
| storage | Remote storage | Full |
| geolocation | GPS/location | Full |
| analytics | Video analytics | Full |
| snapshot | Best snapshot | Full |
| audio-multicast | Audio streaming | Full |
| stream | RTSP/RTP/profiles | Full |
| serverreport | Diagnostic reports & debug archives | Full |
| oidc | OpenID Connect authentication | Full |
| oauth | OAuth 2.0 client credentials | Full |
| virtualhost | Virtual host configuration | Full |
| crypto-policy | TLS/cipher configuration | Full |
| network-pairing | Device pairing | Full |

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/yourusername/axis.git
cd axis

# Install dependencies with uv
uv sync --dev
```

### Testing

```bash
# Run all tests
uv run pytest

# With coverage
uv run pytest --cov=src/axis_cam --cov-report=term-missing

# Specific test file
uv run pytest tests/test_api_stream.py -v
```

### Code Quality

```bash
# Lint
uv run ruff check src/ tests/

# Format
uv run ruff format src/ tests/

# Type check
uv run mypy src/
```

### Project Structure

```
axis/
├── src/axis_cam/
│   ├── __init__.py          # Package exports
│   ├── cli.py               # Typer CLI (~2200 lines)
│   ├── client.py            # VapixClient HTTP client
│   ├── config.py            # Configuration management
│   ├── models.py            # Pydantic models (~2000 lines)
│   ├── exceptions.py        # Exception hierarchy
│   ├── api/                  # VAPIX API modules
│   │   ├── base.py          # BaseAPI abstract class
│   │   ├── device_info.py   # Basic device info
│   │   ├── param.py         # Parameters
│   │   ├── stream.py        # Stream diagnostics
│   │   ├── logs.py          # Log retrieval
│   │   ├── network.py       # Network settings
│   │   └── ... (30 modules)
│   └── devices/
│       ├── base.py          # AxisDevice abstract base
│       ├── camera.py        # AxisCamera
│       ├── recorder.py      # AxisRecorder
│       ├── intercom.py      # AxisIntercom
│       └── speaker.py       # AxisSpeaker
├── specs/                    # Device API specifications
│   ├── m3216-lve.json       # Dome camera
│   ├── s3008.json           # NVR
│   ├── i8016-lve.json       # Intercom
│   └── c1410.json           # Speaker
├── tests/                    # Comprehensive test suite
└── pyproject.toml           # Project configuration
```

## License

MIT

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and linting
5. Submit a pull request

## Support

- Report issues on GitHub
- Check existing issues before creating new ones
- Include device model and firmware version in bug reports
