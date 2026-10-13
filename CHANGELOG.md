# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project is at
0.1.0 alpha and does not yet promise a stable API.

The programme behind these changes, with per-phase status tables and the
decisions taken, is `docs/plans/2026-10-12-admin-and-modularity-review.md`.

## [Unreleased]

### Added
- API module registry (`axis_cam.api.registry`) and the structural `ResourceModule`
  protocol; `AxisDevice.modules`, `.resources`, `.available_resources()` gated by
  API discovery.
- `UsersAPI` on `pwdgrp.cgi` with `accounts list|add|set-password|set-role|remove`,
  the plan → dry-run / confirm → apply → verify pattern (`cli/confirm.py`), and a
  lockout guard (self-removal, self-de-admin, last administrator).
- Audit, system and access logs from their dedicated CGIs (`auditlog.cgi?tail=N`,
  `systemlog.cgi`, `accesslog.cgi`) with the server-report tarball as fallback;
  `LogReport.source`.
- `download crash-report` (what the web UI calls the crash report) with Axis's
  privacy notice; `download debug` kept as a hidden alias.
- `backup create|show|verify`: a snapshot directory with a hash-verified manifest
  that lists what a VAPIX backup cannot contain and what this version does not read.
- `--auth auto|basic|digest`: `auto` follows the device's `WWW-Authenticate`
  challenge (Basic over HTTPS, Digest over HTTP).
- Fleet fan-out: `--all` / `--group NAME` on the read-only commands `info`,
  `security audit`, `accounts list`, `onvif list` and `backup create`, with
  bounded concurrency (`--concurrency`). Devices carry `groups:` tags in the
  config (the type is always a group). A failing device is a row, not an
  abort; exit 1 if any device failed. `security audit --all` prints a
  checks × devices matrix. `--show-all` replaces `security audit --all` for
  listing passing checks.
- `axiscam security audit` and `axis_cam.audit`: the AXIS OS Hardening Guide
  (July 2026) as checks over what the library already reads — the guide's own
  "Basic hardening via VAPIX API" parameters plus HTTPS-only, authentication
  policy, cipher list, remote syslog, accounts, ONVIF users, SNMP, firewall,
  crypto policy, NTP, certificates, firmware. Each finding carries evidence,
  the guide's remedy and section; `unknown` (could not read) is never pass or
  fail; `n/a` when the product lacks the setting. Exit 1 on any failure
  (`--no-fail` for pipelines), `--all`, `--json`.
- `axiscam onvif list|add|set-password|set-level|remove` and `OnvifUsersAPI`:
  the ONVIF user database (separate from VAPIX accounts) over the ONVIF Device
  Management SOAP service on `/vapix/services`, which takes VAPIX administrator
  credentials. Faults are decoded to their ONVIF codes (`AxisSoapFault`);
  creates, level changes and deletes are verified by re-reading; the only
  ONVIF Administrator is protected unless `--allow-lockout`. ONVIF users are
  now part of `report --full` and `backup create` (names and levels only).
  Live-tested on an M3216-LVE: create, rotate, level up, level down with a new
  password, remove — each followed by an ONVIF login as the test user. A
  `SetUser` must carry the password (Axis: `ter:InvalidArgs` without one), so
  `set-level` asks for it.
- `VapixClient.post_raw()` for SOAP/XML bodies (401/403 raised, other
  statuses returned for the caller to read the fault).
- `backup restore DIR`: restores the parameter tree from a backup through
  `param.cgi?action=update`, one parameter at a time with read-back verification,
  plan → `--dry-run` / confirm → apply; refuses a backup from another serial
  number; `Network` excluded unless `--include-network`. `ParamAPI.set()`.
  The plan skips what the device declares read-only (`ParamAPI.definitions()`
  decodes `listdefinitions` `securityLevel`) and refuses a `params.json` that
  does not match the manifest's hash. Live-tested on an M3216-LVE: one label
  changed and restored, both writes verified by read-back and visible in the
  device's audit log.
- `ParamAPI.get()` returned `None` for every parameter: a single-parameter
  `action=list` is echoed without the `root.` prefix, which the parser now
  normalises. Found by the first live restore's read-back.
- CI (`.github/workflows/ci.yml`) mirroring the central `ci-standards` `python-uv`
  profile; `CHANGELOG.md`, `CONTRIBUTING.md`.
- `axis_cam.files.write_private`: every diagnostic, export and the config file are
  written `0600`.
- `tests/test_docs.py`: documented methods must exist on the real classes.

### Changed
- **Breaking:** the transport scheme is explicit (`https` defaults to `true`) and
  never inferred from the port; Basic over plain HTTP is refused without
  `allow_insecure_basic`. A misconfigured device now gets an actionable error.
- **Breaking:** `device.get_ssh_config()` and 28 similar pass-through wrappers are
  removed; call the module (`device.ssh.get_config()`).
- **Breaking:** `--digest/--no-digest` → `--auth`; `use_digest_auth` → `auth_mode`.
- **Breaking:** `report` output is nested under `sections` and keyed by module name.
- `cli.py` split into the `cli/` package with `DeviceContext`.
- `ParamAPI.export()` has one shape: `{"root.Group.Name": "value"}`.
- Coverage gate measures coverage (`--cov=src/axis_cam`) with a ratcheting floor.

### Fixed

- The SSH, firewall, SNMP, crypto-policy, certificate and NTP readers were
  parsing field names no device sends (`ipv4Rules`, `tlsMinVersion`,
  `authorizedKeys`, …) and swallowing every error into an all-defaults model,
  so `security ssh` reported SSH disabled on a device where it is on. Each is
  now shaped by the device's own OpenAPI (fetched from
  `/config/discover/apis/<api>/<version>/openapi.json`) and verified live;
  errors propagate. `SshConfig.enabled` comes from `Network.SSH.Enabled` (the
  REST API has no switch). Certificates are parsed from their PEM
  (`cryptography`): subject, issuer, validity, key type, fingerprint,
  self-signed. `SnmpConfig` never holds community strings.
- `ParamAPI` parsed JSON against a `text/plain` CGI and had never returned data on
  a real device.
- API discovery fetched `/config/discover/apis.json` (404 on AXIS OS 11.11 and
  12.11) and so returned nothing; it now uses `/config/discover/apis`, is cached,
  and modules resolve their REST path from it instead of hard-coding a version
  that five of them had wrong on current firmware.
- `storage`, `recording`, `mqtt` and `action` parsers accept the list-shaped
  collections devices actually return (`storage.read()` crashed on every device).
- Time fallback uses the documented Time API (`POST time.cgi getDateTimeInfo`);
  `date.cgi` is a 404 on 11.11.
- A 403 is `AxisPermissionError` (this account may not use this API) and is
  recorded per module by report and backup; a 401 still aborts.
- `--auth auto` settles the scheme only on a successful response and reconsiders
  when a later 401 offers only the other scheme.
- 62 `except Exception` sites narrowed so authentication and connection errors
  propagate instead of rendering as empty or default-valued results.
- Log timestamps normalised to aware UTC (mixed naive/aware sorting raised).
- `--json` output no longer soft-wraps at the console width.
- 66 documented methods that never existed removed from `docs/api-modules.md`.

### Security
- `ssl_verify`, `https` and `timeout` from the config file are honoured by every
  command (previously dropped).
- Tracebacks never print local variables (which include the device password).
- New account passwords are never taken from the command line.
