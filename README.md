# axis-cam

CLI tool for managing AXIS cameras, recorders, intercoms, and speakers via the VAPIX API.

## Features

- Device management for AXIS cameras, recorders, intercoms, and speakers
- Device information retrieval via VAPIX API
- Time synchronization and NTP configuration
- Log retrieval and analysis
- Network configuration management
- Async operations for efficient device communication

## Installation

```bash
# Install with uv
uv tool install .

# Or for development
uv sync --dev
```

## Usage

```bash
# Get device information
axiscam info --host 192.168.1.10 --user admin --password secret

# Get device logs
axiscam logs --host 192.168.1.10 --user admin --password secret --type system

# Check device connectivity
axiscam check --host 192.168.1.10 --user admin --password secret
```

## Configuration

Create a configuration file at `~/.config/axis-cam/config.yaml`:

```yaml
default_device: camera1
timeout: 30.0

devices:
  camera1:
    host: 192.168.1.10
    username: ${AXIS_ADMIN_USERNAME}
    password: ${AXIS_ADMIN_PASSWORD}
    device_type: camera
```

Environment variables can be interpolated using `${VAR_NAME}` syntax.

## Supported Device Types

- **Camera**: Video cameras with streaming, PTZ, and analytics
- **Recorder**: Network video recorders (NVR) like AXIS S3008
- **Intercom**: Door stations and video intercoms
- **Speaker**: Network audio speakers

## Development

```bash
# Install dev dependencies
uv sync --dev

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=src/axis_cam --cov-report=term-missing

# Lint code
uv run ruff check src/ tests/

# Format code
uv run ruff format src/ tests/

# Type check
uv run mypy src/
```

## License

MIT
