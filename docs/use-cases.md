# Use Cases & How-To Guide

This guide covers real-world scenarios for `axiscam` — from first-time setup through fleet-scale automation. Each use case includes CLI commands, Python API examples, a user-flow diagram, and representative output.

---

## Table of Contents

**Part 1: Core Use Cases**

1. [Initial Setup & Configuration](#1-initial-setup--configuration)
2. [Device Discovery & Inventory](#2-device-discovery--inventory)
3. [Stream Configuration for Third-Party Integration](#3-stream-configuration-for-third-party-integration)
4. [Security Auditing](#4-security-auditing)
5. [Log Analysis & Monitoring](#5-log-analysis--monitoring)
6. [Network Topology Mapping](#6-network-topology-mapping)

**Part 2: Extended Use Cases**

7. [Generating Device Reports](#7-generating-device-reports)
8. [Downloading Diagnostic Archives](#8-downloading-diagnostic-archives)
9. [MQTT & Event Automation](#9-mqtt--event-automation)
10. [Recording & Storage Management](#10-recording--storage-management)
11. [Multi-Device Fleet Management](#11-multi-device-fleet-management)
12. [Configuration Migration](#12-configuration-migration)

**Part 3: Application Flow Diagrams**

- [Application Startup Flow](#application-startup-flow)
- [Authentication Flow](#authentication-flow)
- [API Fallback Flow](#api-fallback-flow)
- [Error Handling Flow](#error-handling-flow)

**Part 4: User Journey Diagrams**

- [First-Time Setup Journey](#first-time-setup-journey)
- [Daily Operations Journey](#daily-operations-journey)
- [Troubleshooting Journey](#troubleshooting-journey)
- [Integration Workflow](#integration-workflow)

---

## Part 1: Core Use Cases

---

### 1. Initial Setup & Configuration

**Scenario:** You have a new AXIS camera deployment. Before running any commands, you need a config file with device credentials and need to decide how to handle secrets securely.

#### Step 1 — Generate the default config

```bash
axiscam init
# Created config file: /Users/you/.config/axiscam/config.yaml
```

Force-overwrite if you need a clean slate:

```bash
axiscam init --force
```

#### Step 2 — Inspect the generated config structure

```bash
axiscam config
```

#### Step 3 — Edit the config to match your devices

`~/.config/axiscam/config.yaml`:

```yaml
default_device: front_door

timeout: 30.0

devices:
  front_door:
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
    name: "Main NVR"
    vendor: axis
    model: S3016
    type: recorder
    address: 192.168.1.100
    port: 443
    username: ${AXIS_ROOT_USER_NAME}
    password: ${AXIS_ROOT_USER_PASSWORD}
    ssl_verify: false
```

The `${VAR_NAME}` syntax interpolates environment variables at load time. This keeps credentials out of the YAML file.

#### Step 4 — Store credentials in `.env`

Create `~/.config/axiscam/.env`:

```bash
AXIS_ROOT_USER_NAME=admin
AXIS_ROOT_USER_PASSWORD=your_secure_password
```

Secure the file immediately:

```bash
chmod 600 ~/.config/axiscam/.env
chmod 600 ~/.config/axiscam/config.yaml
```

The `.env` file is loaded before YAML interpolation. Variables in `.env` will not override variables already in your shell environment — existing shell exports take precedence.

#### Step 5 — Verify connectivity

```bash
axiscam status --device front_door
axiscam info --device front_door
```

#### Using environment variables directly (no config file)

For CI pipelines or one-off commands:

```bash
AXIS_HOST=192.168.1.10 \
AXIS_USERNAME=admin \
AXIS_PASSWORD=secret \
  axiscam info
```

Or with explicit flags:

```bash
axiscam info --host 192.168.1.10 --username admin --password secret
```

#### Python API

```python
from axis_cam import AxisCamera
from axis_cam.config import get_device_config

# From config
cfg = get_device_config("front_door")
async with AxisCamera(
    cfg.host,
    cfg.username,
    cfg.password.get_secret_value(),
    cfg.port,
) as cam:
    info = await cam.get_info()
    print(f"Connected to {info.product_number} ({info.serial_number})")

# Or directly
async with AxisCamera("192.168.1.10", "admin", "secret") as cam:
    info = await cam.get_info()
```

#### User Flow

```mermaid
flowchart TD
    A([Start]) --> B[axiscam init]
    B --> C{Config exists?}
    C -- Yes --> D[axiscam init --force]
    C -- No --> E[Config written to\n~/.config/axiscam/config.yaml]
    D --> E
    E --> F[Edit config.yaml\nadd devices + env var refs]
    F --> G[Create .env\nwith credentials]
    G --> H[chmod 600 both files]
    H --> I[axiscam status -d front_door]
    I --> J{Reachable?}
    J -- Yes --> K([Setup complete])
    J -- No --> L[Check IP / credentials\naxiscam info --host x.x.x.x -u admin -p pass]
    L --> I
```

#### Expected Output

```
╭─────────────────── Status: 192.168.1.10 ─────────────────────╮
│ Reachable                                                      │
╰──── M3216-LVE (camera) ───────────────────────────────────────╯
Serial     ACCC8E123456
Firmware   11.11.114
Device Time 2026-04-06T09:15:00Z
```

---

### 2. Device Discovery & Inventory

**Scenario:** You need a quick picture of what devices are configured, whether they are reachable, and what firmware they are running.

#### List configured devices

```bash
axiscam devices
```

#### Check a single device

```bash
axiscam info --device front_door
axiscam status --device main_nvr
```

#### Check all devices in a shell loop

```bash
axiscam devices --json 2>/dev/null | \
  jq -r '.[] | .name' | \
  while read dev; do
    echo "=== $dev ==="
    axiscam status --device "$dev"
  done
```

Or target by IP when not in config:

```bash
axiscam info --host 192.168.1.22 --username admin --password secret
```

#### Inspect available APIs on a device

```bash
axiscam apis --device front_door
```

Useful when integrating with a new firmware version — shows which VAPIX API versions are released vs. beta.

#### Python API — build an inventory dict

```python
import asyncio
from axis_cam import AxisCamera
from axis_cam.config import load_config

async def inventory_all():
    config = load_config()
    results = {}

    for name, dev_cfg in config.devices.items():
        if dev_cfg.device_type != "camera":
            continue
        try:
            async with AxisCamera(
                dev_cfg.host,
                dev_cfg.username,
                dev_cfg.password.get_secret_value(),
                dev_cfg.port,
            ) as cam:
                info = await cam.get_info()
                status = await cam.get_status()
                results[name] = {
                    "model": info.product_number,
                    "serial": info.serial_number,
                    "firmware": info.firmware_version,
                    "reachable": status.reachable,
                    "ip": dev_cfg.host,
                }
        except Exception as e:
            results[name] = {"error": str(e), "ip": dev_cfg.host}

    return results

inventory = asyncio.run(inventory_all())
for name, data in inventory.items():
    print(f"{name}: {data}")
```

#### User Flow

```mermaid
flowchart LR
    A([Start]) --> B[axiscam devices\nlist configured]
    B --> C{Device in config?}
    C -- Yes --> D[axiscam info -d name\naxiscam status -d name]
    C -- No --> E[axiscam info\n--host x.x.x.x -u -p]
    D --> F[axiscam apis -d name\ncheck API versions]
    E --> F
    F --> G[Build inventory\nfirmware, serial, status]
    G --> H([Inventory complete])
```

#### Expected Output

```
Configured Devices
Name           Type      Host           Port  Friendly Name
front_door *   camera    192.168.1.10   443   Front Door Camera
back_yard      camera    192.168.1.11   443   Back Yard Camera
main_nvr       recorder  192.168.1.100  443   Main NVR

* = default device
```

---

### 3. Stream Configuration for Third-Party Integration

**Scenario:** You need to wire an AXIS camera into UniFi Protect, Milestone XProtect, or another NVR. You need the RTSP URL, the active stream profiles, and confirmation of the auth method.

#### Check stream configuration

```bash
axiscam stream show --device front_door
```

#### Get JSON output for scripting

```bash
axiscam stream show --device front_door --json
```

#### Construct the RTSP URL manually

Based on the stream output, AXIS RTSP URLs follow this pattern:

```
rtsp://<host>/axis-media/media.amp
rtsp://<host>/axis-media/media.amp?streamprofile=<profile>
rtsp://<host>/axis-media/media.amp?videocodec=h264
rtsp://<host>/axis-media/media.amp?videocodec=h265&streamprofile=high
```

For authenticated streams (required by most third-party NVRs):

```
rtsp://admin:password@192.168.1.10/axis-media/media.amp
```

#### Python API — get stream URL

```python
from axis_cam import AxisCamera

async with AxisCamera("192.168.1.10", "admin", "secret") as cam:
    # Default H.264 stream
    url = await cam.get_video_stream_url()
    print(url)
    # rtsp://192.168.1.10/axis-media/media.amp?videocodec=h264

    # With a named profile
    url = await cam.get_video_stream_url(profile="high", codec="h265")
    print(url)
    # rtsp://192.168.1.10/axis-media/media.amp?streamprofile=high&videocodec=h265

    # Get all configured stream profiles
    profiles = await cam.get_stream_profiles()
    for p in profiles:
        print(p)
```

#### Integration checklist

1. Run `axiscam stream show -d <device>` — note the RTSP port (usually 554) and auth method
2. Check that RTSP is enabled
3. Identify the target stream profile (name, resolution, codec)
4. In your NVR, enter: `rtsp://admin:password@<host>:<rtsp_port>/axis-media/media.amp?streamprofile=<name>`
5. For UniFi Protect custom cameras — use RTSP without credentials in the URL; configure credentials separately in the NVR UI

#### User Flow

```mermaid
flowchart TD
    A([Need RTSP URL]) --> B[axiscam stream show\n-d camera_name --json]
    B --> C{RTSP enabled?}
    C -- No --> D[Enable RTSP via\ndevice web UI]
    C -- Yes --> E[Note port + auth method\nnote stream profiles]
    D --> B
    E --> F{Auth method?}
    F -- digest --> G[Use credentials in\nNVR UI not URL]
    F -- basic/none --> H[Embed creds in URL\nrtsp://user:pass@host/...]
    G --> I[Build RTSP URL\nwith stream profile]
    H --> I
    I --> J[Configure in NVR\nUniFi / Milestone / Blue Iris]
    J --> K{Stream working?}
    K -- Yes --> L([Done])
    K -- No --> M[Check firewall\naxiscam security firewall -d cam]
    M --> J
```

#### Expected Output

```
╭──────── Stream Diagnostics: 192.168.1.10 ────────╮
│ Enabled                                            │
╰────────────────────────────────────────────────────╯

RTSP Configuration
Port            554
Authentication  digest
Timeout         60s

RTP Configuration
Port Range      50000-50999
Multicast       No

Stream Profiles
Name        Codec   Resolution  FPS  Bitrate    GOP
high        H.264   1920x1080   25   4000 kbps  50
medium      H.264   1280x720    15   2000 kbps  30
low         H.264   640x360     10   500 kbps   20
```

---

### 4. Security Auditing

**Scenario:** Before a compliance review or after a firmware upgrade, audit the security posture of your camera fleet — firewall rules, SSH configuration, certificate validity, and SNMP exposure.

#### Firewall check

```bash
axiscam security firewall --device front_door
axiscam security firewall --device front_door --json
```

#### SSH configuration

```bash
axiscam security ssh --device front_door
```

Key things to check:
- `Root Login` should be `Disabled` in production
- `Password Auth` should ideally be `Disabled` if key-based auth is in use
- List of authorized keys matches expectations

#### TLS certificates

```bash
axiscam security certs --device front_door
```

Check `Valid To` dates against today. Any certificate marked `Invalid/Expired` needs immediate attention.

#### SNMP exposure

```bash
axiscam services snmp --device front_door
```

In a security audit, look for:
- SNMP v1/v2 enabled with `public` community string
- Write community string set (configuration attack surface)
- Trap receivers pointing to unexpected IPs

#### Python API — audit across fleet

```python
import asyncio
from axis_cam import AxisCamera
from axis_cam.config import load_config
from datetime import date

async def security_audit():
    config = load_config()
    findings = []

    for name, dev_cfg in config.devices.items():
        try:
            async with AxisCamera(
                dev_cfg.host,
                dev_cfg.username,
                dev_cfg.password.get_secret_value(),
                dev_cfg.port,
            ) as cam:
                ssh = await cam.get_ssh_config()
                fw = await cam.get_firewall_config()
                snmp = await cam.get_snmp_config()
                certs = await cam.get_cert_config()

                if ssh.root_login_enabled:
                    findings.append(f"{name}: SSH root login enabled")
                if not fw.enabled:
                    findings.append(f"{name}: Firewall disabled")
                if snmp.enabled and snmp.read_community == "public":
                    findings.append(f"{name}: SNMP using default 'public' community")
                for cert in certs.certificates:
                    if not cert.is_valid:
                        findings.append(f"{name}: Expired certificate {cert.id}")

        except Exception as e:
            findings.append(f"{name}: Could not audit — {e}")

    return findings

findings = asyncio.run(security_audit())
for f in findings:
    print(f"[FINDING] {f}")
```

#### User Flow

```mermaid
flowchart TD
    A([Start audit]) --> B[axiscam security firewall\n-d device]
    B --> C{Firewall enabled\nand rules sane?}
    C -- No --> Z1[Flag: Firewall misconfiguration]
    C -- Yes --> D[axiscam security ssh\n-d device]
    D --> E{Root login\ndisabled?}
    E -- No --> Z2[Flag: SSH root login]
    E -- Yes --> F[axiscam security certs\n-d device]
    F --> G{Any expired\ncerts?}
    G -- Yes --> Z3[Flag: Expired TLS certificate]
    G -- No --> H[axiscam services snmp\n-d device]
    H --> I{Default community\nor SNMP v1?}
    I -- Yes --> Z4[Flag: SNMP weakness]
    I -- No --> J([Audit passed])
    Z1 & Z2 & Z3 & Z4 --> K[Remediation required]
```

#### Expected Output

```
╭──── Firewall: 192.168.1.10 ────╮
│ Status: Enabled                 │
│ Default Policy: DROP            │
╰─────────────────────────────────╯

Firewall Rules (3)
Name              Enabled  Action  Source      Port  Protocol  Priority
allow-https-mgmt  Yes      allow   10.0.0.0/8  443   TCP       10
allow-rtsp        Yes      allow   *           554   TCP       20
deny-all          Yes      deny    *           *     Any       100
```

---

### 5. Log Analysis & Monitoring

**Scenario:** A camera rebooted overnight. You need to examine system logs for errors, check who accessed the device (access logs), and search for a specific error pattern.

#### System logs — last 50 entries

```bash
axiscam logs system --device front_door --lines 50
```

#### Access log — see who logged in

```bash
axiscam logs access --device front_door --lines 30
```

#### Audit log — configuration changes

```bash
axiscam logs audit --device front_door
```

#### All logs combined

```bash
axiscam logs all --device front_door --lines 100
```

#### Search by keyword

```bash
# Find reboot events
axiscam logs search "reboot" --device front_door

# Find authentication failures
axiscam logs search "failed" --device front_door --lines 100

# Find network errors
axiscam logs search "network" --device front_door
```

#### Python API — search and parse logs

```python
from axis_cam import AxisCamera
from axis_cam.models import LogType

async with AxisCamera("192.168.1.10", "admin", "secret") as cam:
    # Get system logs
    report = await cam.logs.get_logs(LogType.SYSTEM, max_entries=100)
    for entry in report.entries:
        print(f"{entry.timestamp} [{entry.level}] {entry.message}")

    # Search for failures
    failures = await cam.logs.search_logs("failed", max_entries=50)
    print(f"Found {len(failures.entries)} failure events")

    # Filter by severity in Python
    errors = [e for e in report.entries if str(e.level).lower() in ("error", "err")]
    print(f"{len(errors)} error-level events")
```

#### Tailing logs for a maintenance window

Use a shell loop to poll logs during a firmware upgrade:

```bash
while true; do
  axiscam logs system --device front_door --lines 5
  sleep 10
done
```

#### User Flow

```mermaid
flowchart TD
    A([Incident reported]) --> B{Know what to\nlook for?}
    B -- Yes --> C[axiscam logs search\n'keyword' -d device]
    B -- No --> D[axiscam logs system\n-d device -n 100]
    C --> E[Review matching entries]
    D --> F{Errors found?}
    F -- Yes --> G[axiscam logs search\n'error_text' -d device]
    F -- No --> H[axiscam logs access\n-d device]
    G --> E
    H --> I{Unexpected\nauthentication?}
    I -- Yes --> J[axiscam logs audit\n-d device]
    I -- No --> K([No security event])
    J --> L[Review config changes]
    E & L --> M([Document findings])
```

#### Expected Output

```
System Logs  from 192.168.1.10 (47 entries)

2026-04-06 08:00:01  INFO    syslog  System started
2026-04-06 08:00:05  INFO    network  Network interface eth0 up
2026-04-06 07:59:58  WARNING firmware  Firmware update completed, rebooting
2026-04-06 07:45:12  ERROR   ntpd  Failed to reach NTP server 0.pool.ntp.org
```

---

### 6. Network Topology Mapping

**Scenario:** You are auditing physical switch connectivity for a camera fleet. LLDP lets each camera report what switch port it is connected to, enabling automated topology mapping without a site walk.

#### Show LLDP neighbors for one camera

```bash
axiscam lldp --device front_door
```

#### JSON output for processing

```bash
axiscam lldp --device front_door --json
```

#### Map all cameras to switch ports

```bash
for dev in front_door back_yard lobby_cam; do
  echo "=== $dev ==="
  axiscam lldp --device "$dev" --json | \
    jq -r '.neighbors[] | "\(.sys_name) port \(.port_id)"'
done
```

#### Network interface details

```bash
axiscam network show --device front_door
axiscam network dns --device front_door
```

#### Python API — build a topology map

```python
import asyncio
from axis_cam import AxisCamera
from axis_cam.config import load_config

async def topology_map():
    config = load_config()
    topology = {}

    for name, dev_cfg in config.devices.items():
        try:
            async with AxisCamera(
                dev_cfg.host,
                dev_cfg.username,
                dev_cfg.password.get_secret_value(),
                dev_cfg.port,
            ) as cam:
                lldp = await cam.get_lldp_info()
                net = await cam.get_network_config()

                topology[name] = {
                    "camera_ip": dev_cfg.host,
                    "mac": net.interfaces[0].mac_address if net.interfaces else None,
                    "neighbors": [
                        {
                            "switch": n.sys_name,
                            "port": n.port_id.value,
                            "port_desc": n.port_descr,
                        }
                        for n in lldp.neighbors
                    ],
                }
        except Exception as e:
            topology[name] = {"error": str(e)}

    return topology

topology = asyncio.run(topology_map())
for cam, data in topology.items():
    if "neighbors" in data and data["neighbors"]:
        n = data["neighbors"][0]
        print(f"{cam} ({data['camera_ip']}) -> {n['switch']} port {n['port']}")
```

#### User Flow

```mermaid
flowchart LR
    A([Start mapping]) --> B[For each camera]
    B --> C[axiscam lldp\n-d camera --json]
    C --> D{Neighbors\nfound?}
    D -- Yes --> E[Extract switch name\nport ID, port description]
    D -- No --> F[LLDP not enabled\nor no neighbor]
    E --> G[axiscam network show\n-d camera]
    G --> H[Record MAC + IP]
    F --> H
    H --> I{More cameras?}
    I -- Yes --> B
    I -- No --> J[Build topology table\ncamera → switch → port]
    J --> K([Topology map complete])
```

#### Expected Output

```
╭────────── LLDP Info: 192.168.1.10 ──────────╮
│ LLDP Status: Enabled                          │
╰───────────────────────────────────────────────╯

LLDP Neighbors (1 found)
System Name    Model              Chassis ID         Port                Interface
core-sw-01     Cisco Catalyst 9K  00:1a:2b:3c:4d:5e  Gi1/0/12 (Camera)  eth0
```

---

## Part 2: Extended Use Cases

---

### 7. Generating Device Reports

**Scenario:** Before a maintenance window or after a fleet upgrade, you want a structured snapshot of every camera's configuration — firmware, network, security posture — saved to disk for comparison or audit trail.

#### Quick report to stdout

```bash
axiscam report --device front_door
```

#### Full report including all optional sections

```bash
axiscam report --device front_door --full
```

The `--full` flag adds: SSH config, SNMP, certificates, MQTT, action rules, recording, storage, geolocation, analytics, OIDC/OAuth, and crypto policy.

#### Save to file in JSON

```bash
axiscam report --device front_door --output reports/front_door.json
```

#### Save in YAML format

```bash
axiscam report --device front_door --format yaml --output reports/front_door.yaml
```

#### Generate reports for all configured devices

```bash
mkdir -p reports
axiscam devices 2>/dev/null  # list configured device names first

for dev in front_door back_yard main_nvr; do
  axiscam report --device "$dev" --full \
    --output "reports/${dev}_$(date +%Y%m%d).json"
done
```

#### Python API — report as dict

```python
from axis_cam import AxisCamera

async with AxisCamera("192.168.1.10", "admin", "secret") as cam:
    info = await cam.get_info()
    network = await cam.get_network_config()
    lldp = await cam.get_lldp_info()
    stream = await cam.get_stream_diagnostics()

    report = {
        "model": info.product_number,
        "serial": info.serial_number,
        "firmware": info.firmware_version,
        "ip": network.interfaces[0].ip_address if network.interfaces else None,
        "switch_port": lldp.neighbors[0].port_id.value if lldp.neighbors else None,
        "stream_profiles": [
            {"name": p.name, "codec": p.video_codec, "resolution": p.resolution}
            for p in stream.profiles
        ],
    }
```

#### User Flow

```mermaid
flowchart TD
    A([Need report]) --> B{Full or\nstandard?}
    B -- Standard --> C[axiscam report -d device\n-o file.json]
    B -- Full --> D[axiscam report -d device\n--full -o file.json]
    C --> E{Output format?}
    D --> E
    E -- JSON --> F[--format json\ndefault]
    E -- YAML --> G[--format yaml]
    F --> H[Report saved to file]
    G --> H
    H --> I{Multiple devices?}
    I -- Yes --> J[Loop over device names\nsave per-device files]
    I -- No --> K([Done])
    J --> K
```

#### Expected Output

```json
{
  "device": "front_door",
  "info": {
    "brand": "AXIS",
    "model": "M3216-LVE",
    "serial_number": "ACCC8E123456",
    "firmware": "11.11.114"
  },
  "network": {
    "interface": "eth0",
    "ip_address": "192.168.1.10",
    "mac_address": "AC:CC:8E:12:34:56",
    "dhcp": false
  },
  "security": {
    "firewall_enabled": true,
    "ipv4_rules_count": 3,
    "ipv6_rules_count": 0
  },
  "errors": []
}
```

---

### 8. Downloading Diagnostic Archives

**Scenario:** A camera is behaving erratically and AXIS technical support needs diagnostic data. You need to collect the server report (ZIP with snapshot) and/or the full debug archive.

#### Download server report (ZIP with snapshot image)

```bash
axiscam download report --device front_door
# Output: server_report_front_door.zip
```

#### Specify output path and format

```bash
# ZIP only (no snapshot)
axiscam download report --device front_door \
  --format zip \
  --output ~/support/front_door_report.zip

# Plain text report
axiscam download report --device front_door \
  --format text \
  --output ~/support/front_door_report.txt
```

Available formats: `zip_with_image` (default), `zip`, `text`

#### Download full debug archive for AXIS support

```bash
axiscam download debug --device front_door
# Output: debug_front_door.tgz
# Default timeout: 120s (debug archives can be 10–50 MB)
```

Increase timeout for slow devices or large archives:

```bash
axiscam download debug --device front_door \
  --output ~/support/front_door_debug.tgz \
  --timeout 300
```

#### Collect diagnostics from multiple cameras

```bash
mkdir -p ~/support/$(date +%Y%m%d)
cd ~/support/$(date +%Y%m%d)

for dev in front_door back_yard lobby_cam; do
  echo "Collecting from $dev..."
  axiscam download report --device "$dev" \
    --output "${dev}_report.zip" &
done
wait
echo "All reports collected."
```

#### Python API

```python
from axis_cam import AxisCamera
from axis_cam.models import ServerReportFormat
from pathlib import Path

async with AxisCamera("192.168.1.10", "admin", "secret") as cam:
    # Server report
    report = await cam.download_server_report(
        format=ServerReportFormat.ZIP_WITH_IMAGE,
        timeout=60.0,
    )
    if report.success:
        Path("server_report.zip").write_bytes(report.content)
        print(f"Report: {report.size_bytes / 1024:.1f} KB")

    # Debug archive
    debug = await cam.download_debug_archive(timeout=120.0)
    if debug.success:
        Path("debug.tgz").write_bytes(debug.content)
```

#### User Flow

```mermaid
flowchart TD
    A([Support needed]) --> B{What does\nsupport need?}
    B -- Quick diagnostics --> C[axiscam download report\n-d device -o report.zip]
    B -- Full debug\nfor AXIS support --> D[axiscam download debug\n-d device -o debug.tgz]
    B -- Both --> C
    C --> E{Download\nsucceeded?}
    D --> E
    E -- Yes --> F[Send file to support\nor archive locally]
    E -- No --> G{Timeout?}
    G -- Yes --> H[Increase --timeout\nand retry]
    G -- No --> I[Check credentials\nand connectivity]
    H & I --> C
    F --> J([Done])
```

#### Expected Output

```
Downloading server report from 192.168.1.10...
Server report downloaded: server_report_front_door.zip
Size: 1847.3 KB, Format: zip_with_image
```

---

### 9. MQTT & Event Automation

**Scenario:** You want to push AXIS camera events (motion detection, door open/close, tampering) to a Home Assistant MQTT broker or a custom event processing system.

#### View current MQTT configuration

```bash
axiscam automation mqtt --device front_door
```

#### View action rules (what triggers what)

```bash
axiscam automation actions --device front_door
```

#### JSON output for integration scripting

```bash
axiscam automation mqtt --device front_door --json
axiscam automation actions --device front_door --json
```

#### What to look for

From `automation mqtt`:
- **Status**: whether the MQTT bridge is enabled and connected
- **Clients**: broker host, port, TLS status
- **Event Filters**: which event topics are being published and at what QoS

From `automation actions`:
- **Rules**: what conditions trigger actions (motion → recording, door open → relay)
- **Templates**: available action types for the device

#### Python API — inspect MQTT config

```python
from axis_cam import AxisCamera

async with AxisCamera("192.168.1.10", "admin", "secret") as cam:
    mqtt = await cam.get_mqtt_config()
    print(f"MQTT enabled: {mqtt.enabled}, connected: {mqtt.connected}")

    for client in mqtt.clients:
        print(f"Broker: {client.host}:{client.port} TLS={client.use_tls}")

    for filt in mqtt.event_filters:
        status = "ON" if filt.enabled else "OFF"
        print(f"Topic: {filt.topic}  QoS: {filt.qos}  [{status}]")

    # Also check action rules
    actions = await cam.get_action_config()
    for rule in actions.rules:
        status = "enabled" if rule.enabled else "disabled"
        print(f"Rule: {rule.name}  Condition: {rule.primary_condition}  [{status}]")
```

#### Typical MQTT integration pattern

```
Camera event (motion) → AXIS MQTT bridge → Broker (Mosquitto/EMQX)
                                              ↓
                                   Home Assistant / Node-RED
```

Verify the bridge is working:

```bash
# On your MQTT broker host
mosquitto_sub -h localhost -t "axis/#" -v
```

Then trigger a camera event and watch for messages.

#### User Flow

```mermaid
flowchart TD
    A([Setup MQTT\nintegration]) --> B[axiscam automation mqtt\n-d camera --json]
    B --> C{MQTT enabled\nand connected?}
    C -- No --> D[Configure MQTT broker\nvia device web UI]
    C -- Yes --> E[Note broker host/port\nevent filter topics]
    D --> B
    E --> F[axiscam automation actions\n-d camera --json]
    F --> G[Identify relevant\naction rules]
    G --> H[Subscribe to topics\non broker to verify]
    H --> I{Events arriving?}
    I -- Yes --> J([Integration working])
    I -- No --> K[Check event filters\nare enabled + topics correct]
    K --> H
```

#### Expected Output

```
╭──────── MQTT Bridge: 192.168.1.10 ────────╮
│ Status: Enabled                             │
│ Connection: Connected                       │
╰─────────────────────────────────────────────╯

MQTT Clients (1)
ID        Host             Port  Protocol  TLS
client1   192.168.1.200    1883  mqtt      -

Event Filters (3)
Name                Topic                        Enabled  QoS
Motion detected     axis/motion/front_door        Yes      1
Tampering           axis/tamper/front_door        Yes      1
Input signal        axis/io/front_door            No       0
```

---

### 10. Recording & Storage Management

**Scenario:** You need to verify what recording profiles are active, confirm remote storage (NAS/S3) is configured, and ensure retention policies match your compliance requirements.

#### View recording configuration

```bash
axiscam media recording --device front_door
```

Shows: recording groups (storage assignment, retention days, max size), recording profiles (codec, resolution, framerate).

#### View remote storage destinations

```bash
axiscam media storage --device front_door
```

#### JSON output for automation

```bash
axiscam media recording --device front_door --json
axiscam media storage --device front_door --json
```

#### Python API — inspect recording config

```python
from axis_cam import AxisCamera

async with AxisCamera("192.168.1.10", "admin", "secret") as cam:
    recording = await cam.get_recording_config()

    for group in recording.groups:
        retention = f"{group.retention_days}d" if group.retention_days else "unlimited"
        max_size = f"{group.max_size_mb}MB" if group.max_size_mb else "no limit"
        print(f"Group: {group.name}  Storage: {group.storage_id}  "
              f"Retention: {retention}  Max: {max_size}")

    for profile in recording.profiles:
        print(f"Profile: {profile.name}  {profile.video_codec}  "
              f"{profile.resolution}  {profile.framerate}fps")

    storage = await cam.get_storage_config()
    for dest in storage.destinations:
        status = "enabled" if dest.enabled else "disabled"
        print(f"Storage: {dest.name}  Type: {dest.storage_type.value}  "
              f"Bucket: {dest.bucket}  [{status}]")
```

#### User Flow

```mermaid
flowchart TD
    A([Verify recording]) --> B[axiscam media recording\n-d camera]
    B --> C{Recording\ngroups configured?}
    C -- No --> D[Configure via\ndevice web UI]
    C -- Yes --> E{Retention meets\nrequirements?}
    E -- No --> F[Update retention policy\nvia web UI]
    E -- Yes --> G[axiscam media storage\n-d camera]
    G --> H{Remote storage\nconfigured?}
    H -- No --> I[Add NAS/S3 destination\nvia web UI]
    H -- Yes --> J{Storage\nenabled?}
    J -- No --> K[Enable storage destination]
    J -- Yes --> L([Recording configured])
    D & F & I & K --> A
```

#### Expected Output

```
Recording Groups (2)
ID    Name          Storage   Retention  Max Size
rg1   Main Group    nas01     30d        50000MB
rg2   Motion Only   local     7d         5000MB

Recording Profiles (3)
ID    Name    Format  Codec  Resolution  FPS
rp1   High    mkv     h264   1920x1080   25
rp2   Medium  mkv     h264   1280x720    15
rp3   Low     mkv     h264   640x360     10
```

---

### 11. Multi-Device Fleet Management

**Scenario:** You manage 20+ cameras and need to run the same operation across all devices — firmware audit, security check, topology export — without writing each device name by hand.

#### Shell pattern — iterate all configured devices

`axiscam devices` outputs a Rich table. For scripting, use `report --json` or the Python API instead.

```bash
# Check status of all cameras via Python (most reliable)
python3 - <<'EOF'
import asyncio, json
from axis_cam import AxisCamera
from axis_cam.config import load_config

async def check_all():
    config = load_config()
    for name, dev in config.devices.items():
        try:
            async with AxisCamera(
                dev.host, dev.username,
                dev.password.get_secret_value(), dev.port
            ) as cam:
                status = await cam.get_status()
                info = await cam.get_info()
                reachable = "OK" if status.reachable else "UNREACHABLE"
                print(f"{name:20} {reachable:12} {info.firmware_version:15} {dev.host}")
        except Exception as e:
            print(f"{name:20} ERROR        -               {dev.host} ({e})")

asyncio.run(check_all())
EOF
```

#### Parallel fleet operations with asyncio

```python
import asyncio
from axis_cam import AxisCamera
from axis_cam.config import load_config

async def audit_device(name, dev_cfg):
    try:
        async with AxisCamera(
            dev_cfg.host,
            dev_cfg.username,
            dev_cfg.password.get_secret_value(),
            dev_cfg.port,
        ) as cam:
            info = await cam.get_info()
            fw = await cam.get_firewall_config()
            return {
                "name": name,
                "firmware": info.firmware_version,
                "firewall": fw.enabled,
                "ok": True,
            }
    except Exception as e:
        return {"name": name, "error": str(e), "ok": False}

async def audit_fleet():
    config = load_config()
    tasks = [
        audit_device(name, dev_cfg)
        for name, dev_cfg in config.devices.items()
    ]
    # Run all audits concurrently
    results = await asyncio.gather(*tasks)
    return results

results = asyncio.run(audit_fleet())
for r in results:
    if r["ok"]:
        fw = "FW:ON" if r["firewall"] else "FW:OFF"
        print(f"{r['name']:20} {r['firmware']:15} {fw}")
    else:
        print(f"{r['name']:20} ERROR: {r['error']}")
```

#### Filter devices by type

```python
from axis_cam.config import load_config

config = load_config()

cameras = {k: v for k, v in config.devices.items() if v.device_type == "camera"}
recorders = {k: v for k, v in config.devices.items() if v.device_type == "recorder"}
intercoms = {k: v for k, v in config.devices.items() if v.device_type == "intercom"}
```

#### User Flow

```mermaid
flowchart TD
    A([Fleet operation]) --> B[Load config\nload_config]
    B --> C[Filter by device type\nif needed]
    C --> D[Create async tasks\nfor each device]
    D --> E[asyncio.gather\nrun in parallel]
    E --> F{Per device:\ncommand succeeds?}
    F -- Yes --> G[Collect result]
    F -- No --> H[Record error\ncontinue]
    G --> I{More devices?}
    H --> I
    I -- Yes --> F
    I -- No --> J[Aggregate results\nprint / save report]
    J --> K([Fleet operation complete])
```

---

### 12. Configuration Migration

**Scenario:** You were using an earlier version of `axiscam` (or the predecessor `axis-cam` CLI) that stored config at `~/.config/axis/`. The new path is `~/.config/axiscam/`. Migrate without losing your device definitions.

#### Check if legacy config exists

```bash
ls ~/.config/axis/config.yaml 2>/dev/null && echo "Legacy config found" || echo "No legacy config"
```

When you run any `axiscam` command with a legacy config present, you will see:

```
Warning: Using legacy config path: /Users/you/.config/axis
         Consider migrating to: /Users/you/.config/axiscam
         Run 'axiscam config migrate' to migrate automatically.
```

#### Run the migration

```bash
axiscam migrate
```

This command:
1. Copies `~/.config/axis/config.yaml` to `~/.config/axiscam/config.yaml`
2. Copies `~/.config/axis/.env` to `~/.config/axiscam/.env` (if it exists)
3. Sets `chmod 600` on both new files
4. Leaves the legacy directory untouched

#### Verify migration

```bash
axiscam config          # confirms new path is in use
axiscam devices         # devices should be listed
axiscam status --device <name>  # confirm connectivity still works
```

#### Clean up legacy directory (after verification)

```bash
rm -rf ~/.config/axis
```

Only do this after confirming the new config works correctly.

#### Environment variable override (CI/CD)

If you have a custom config location (e.g., in a secrets manager mount), override the path entirely:

```bash
AXIS_CONFIG_DIR=/run/secrets/axiscam axiscam devices
```

#### User Flow

```mermaid
flowchart TD
    A([Upgrade axiscam]) --> B{Warning shown\non next command?}
    B -- Yes --> C[axiscam migrate]
    B -- No --> D([Already on new path])
    C --> E{Migration\nsucceeded?}
    E -- Yes --> F[axiscam config\nverify new path]
    E -- No --> G{New config\nalready exists?}
    G -- Yes --> H[axiscam init --force\nto reset, then re-edit]
    G -- No --> I[Check permissions\non ~/.config/]
    F --> J[axiscam devices\naxiscam status -d name]
    J --> K{All devices\nworking?}
    K -- Yes --> L[rm -rf ~/.config/axis]
    K -- No --> M[Compare old and new\nconfig.yaml]
    M --> J
    L --> N([Migration complete])
```

---

## Part 3: Application Flow Diagrams

### Application Startup Flow

```mermaid
flowchart TD
    A([CLI invoked:\naxiscam COMMAND]) --> B[Typer parses\ncommand + options]
    B --> C[resolve_device_config\nhost, device, username, password, port]
    C --> D{--host provided?}
    D -- Yes --> E{username + password\nprovided?}
    E -- No --> F[Exit 1: credentials required]
    E -- Yes --> G[Use host directly]
    D -- No --> H[load_config\nlru_cache]
    H --> I[load_env_file\n~/.config/axiscam/.env]
    I --> J[load_yaml_config\nconfig.yaml with env interpolation]
    J --> K{Device name\nresolved?}
    K -- Yes --> L[DeviceConfig loaded\nhost, user, pass, port, type]
    K -- No --> M{device arg looks\nlike an IP?}
    M -- Yes --> N[get_device_config_by_host\nlookup in config]
    M -- No --> O[Exit 1: no device specified]
    N --> L
    G --> L
    L --> P[get_device_class\ncamera / recorder / intercom / speaker]
    P --> Q[Create device instance\nasync context manager]
    Q --> R[Execute command\nAPIcalls via VAPIX]
    R --> S[Render output\nRich table / JSON]
    S --> T([Exit 0])
```

---

### Authentication Flow

```mermaid
flowchart TD
    A([Device created with\nuse_digest_auth=True/False]) --> B{--digest flag?}
    B -- True default --> C[Digest Authentication\nHTTP Digest RFC 2617]
    B -- False via --no-digest --> D[Basic Authentication\nBase64 encoded]
    C --> E[First request:\nno credentials]
    E --> F[Device returns\n401 + WWW-Authenticate nonce]
    F --> G[Client computes\nHA1 = MD5 user:realm:pass\nHA2 = MD5 method:uri\nresponse = MD5 HA1:nonce:HA2]
    G --> H[Retry with\nAuthorization: Digest header]
    D --> I[All requests include\nAuthorization: Basic base64]
    H --> J{Response 200?}
    I --> J
    J -- Yes --> K([Request succeeds])
    J -- 401 --> L([Authentication failed\ncheck credentials])
    J -- 403 --> M([Forbidden\ncheck user permissions])
```

**Choosing auth method:**
- Use `--digest` (default) for all production devices — credentials are not sent in plaintext
- Use `--no-digest` only if the device firmware does not support Digest auth (very old firmware)

---

### API Fallback Flow

```mermaid
flowchart TD
    A([API call requested]) --> B[Try primary REST endpoint\n/axis-cgi/.../.cgi via HTTPS]
    B --> C{HTTP response?}
    C -- 200 --> D[Parse JSON/XML response]
    C -- 404 Not Found --> E[API not available\non this firmware/model]
    C -- 401 --> F[Re-authenticate\nsee Auth Flow]
    C -- 500 --> G[Server error\ndevice-side issue]
    D --> H{Response valid?}
    H -- Yes --> I([Return parsed data])
    H -- No / parse error --> J[Try CGI fallback\n/axis-cgi/param.cgi?action=list]
    E --> J
    J --> K{CGI response?}
    K -- 200 --> L[Parse param=value format]
    K -- error --> M[Raise exception\nlog to report errors]
    L --> I
    F --> B
    G --> M
```

---

### Error Handling Flow

```mermaid
flowchart TD
    A([Exception raised]) --> B{Exception type?}
    B -- ConnectionError\nTimeoutError --> C[Device unreachable\ncheck IP + network]
    B -- AuthenticationError\n401 --> D[Invalid credentials\ncheck username/password]
    B -- PermissionError\n403 --> E[Insufficient permissions\ncheck VAPIX user role]
    B -- APINotAvailable\n404 --> F[API not supported\ncheck firmware version]
    B -- ParseError --> G[Unexpected response format\ncheck firmware / API version]
    B -- General Exception --> H[Unexpected error\ncollected in report errors list]
    C --> I[axiscam status -d device\nverify connectivity]
    D --> J[axiscam info --host x -u admin -p pass\ntest with explicit creds]
    E --> K[Check VAPIX user in\ndevice web UI → Users]
    F --> L[axiscam apis -d device\ncheck supported API versions]
    G --> M[axiscam download debug\ncollect diagnostics]
    H --> M
    I & J & K & L & M --> N([Remediate and retry])
```

---

## Part 4: User Journey Diagrams

### First-Time Setup Journey

```mermaid
journey
    title First-Time axiscam Setup
    section Install
      Install via uv tool install: 5: User
      Run axiscam --help: 4: User
    section Configure
      Run axiscam init: 5: User
      Edit config.yaml with device IPs: 3: User
      Create .env with credentials: 4: User
      chmod 600 both files: 4: User
    section Verify
      axiscam status -d device_name: 4: User
      axiscam info -d device_name: 5: User
      axiscam devices: 5: User
    section Explore
      axiscam apis -d device: 3: User
      axiscam stream show -d device: 4: User
      axiscam lldp -d device: 4: User
```

---

### Daily Operations Journey

```mermaid
journey
    title Daily Camera Operations
    section Morning Check
      axiscam status -d all_devices: 4: Operator
      axiscam logs system -d key_cam -n 20: 3: Operator
    section Incident Response
      axiscam logs search error -d camera: 4: Operator
      axiscam logs access -d camera: 4: Operator
      axiscam status -d camera: 5: Operator
    section Maintenance
      axiscam report -d camera -o daily.json: 4: Operator
      axiscam download report -d camera: 3: Operator
    section End of Day
      Review report files: 3: Operator
      Note any firmware updates needed: 3: Operator
```

---

### Troubleshooting Journey

```mermaid
flowchart TD
    A([Camera issue reported]) --> B[axiscam status\n-d camera]
    B --> C{Reachable?}
    C -- No --> D[Check network\nping IP directly]
    C -- Yes --> E[axiscam logs system\n-d camera -n 50]
    D --> F{Ping succeeds?}
    F -- No --> G[Physical check:\npower, cable, switch port]
    F -- Yes --> H[axiscam info --host IP\n-u admin -p pass\ntest direct connection]
    H --> I{Connects with\nexplicit creds?}
    I -- Yes --> J[Config issue:\ncheck ~/.config/axiscam/config.yaml]
    I -- No --> K[Credentials changed?\nCheck device web UI]
    E --> L{Errors in\nlogs?}
    L -- Yes --> M[axiscam logs search\n'error_text' -d camera]
    L -- No --> N[axiscam stream show\n-d camera]
    M --> O{Stream-related\nissue?}
    N --> O
    O -- Yes --> P[Check RTSP port\nfirewall rules]
    O -- No --> Q[axiscam download debug\n-d camera -o debug.tgz]
    P --> R[axiscam security firewall\n-d camera]
    Q --> S([Send to AXIS support])
    R --> T{Firewall blocking\nRTSP port?}
    T -- Yes --> U[Update firewall rules\nvia device web UI]
    T -- No --> S
    G & J & K & U --> V([Resolve and retest])
```

---

### Integration Workflow

Connecting an AXIS camera to a third-party NVR (UniFi Protect, Milestone, Blue Iris):

```mermaid
flowchart LR
    A([Need to add camera\nto NVR]) --> B[axiscam stream show\n-d camera --json]
    B --> C[Note:\nRTSP port\nAuth method\nStream profile names]
    C --> D[axiscam security firewall\n-d camera --json]
    D --> E{Port 554 / RTSP\nopen in firewall?}
    E -- No --> F[Add firewall rule\nvia device web UI\nor VAPIX API]
    E -- Yes --> G[Build RTSP URL\nrtsp://host/axis-media/media.amp\n?streamprofile=high]
    F --> G
    G --> H{NVR type?}
    H -- UniFi Protect --> I[Add as RTSP camera\nCredentials in NVR UI\nnot in URL]
    H -- Milestone / Blue Iris --> J[Add as Axis camera\nwith RTSP URL\nDigest auth if supported]
    H -- Generic NVR --> K[Use RTSP URL\nwith embedded creds\nfor Basic auth only]
    I & J & K --> L{Stream\nworking?}
    L -- Yes --> M([Integration complete])
    L -- No --> N[axiscam logs search\n'rtsp' -d camera]
    N --> O[Check NVR event logs\nfor connection errors]
    O --> G
```

---

*For command signatures and all options, see the [CLI Reference](cli-reference.md). For Python API details, see [API Modules](api-modules.md). For architecture context, see [Architecture](architecture.md).*
