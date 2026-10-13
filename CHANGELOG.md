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
- `ParamAPI` parsed JSON against a `text/plain` CGI and had never returned data on
  a real device.
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
