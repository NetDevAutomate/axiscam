# MCP server

`axiscam-mcp` exposes the `axis_cam` library to an MCP host (Kiro, Claude, any
client speaking the Model Context Protocol) over stdio. **Phase A is read and
plan only: no tool writes to a device.** Design record:
[`plans/2026-10-14-mcp-server-design-decision.md`](plans/2026-10-14-mcp-server-design-decision.md).

## Install and run

```bash
uv tool install '.[mcp]'        # or: uv sync --extra mcp
axiscam-mcp                     # speaks JSON-RPC on stdin/stdout
```

The server reads the same config file as the CLI (`~/.config/axiscam/config.yaml`,
or `$AXIS_CONFIG_DIR/config.yaml`). Only devices in that file can be addressed.
The config is read once per process; restart the server after editing it.

Host configuration (Kiro `mcp.json` shape):

```json
{
  "mcpServers": {
    "axiscam": { "command": "axiscam-mcp", "args": [] }
  }
}
```

## Tools

| Tool | What it does | Writes |
|---|---|---|
| `list_devices` | Configured devices: name, type, groups, host. Never credentials. | - |
| `list_modules(device)` | Which readable modules the device advertises via live discovery. | - |
| `read_module(device, module)` | One module's state in an envelope: `status` is `ok`, `not_advertised`, `unreadable` (403/404 -- could not read, never "disabled") or `error`. | - |
| `device_report(device, full)` | The CLI's `report`. | - |
| `security_audit(device, status)` | The Hardening Guide audit, optionally filtered by status. | - |
| `fleet_read(selection, op)` | `info`/`report`/`audit` across `all`, a group tag or a device type; a failing device is a row. 4 at a time, 120 s each. | - |
| `query_params(device, prefix, limit<=200, cursor)` | Parameters under a required prefix, paged. Credential-like values redacted. | - |
| `backup_create(device)` | Backup into the server's own directory (`<data dir>/mcp-backups`); returns a `backup_id`. | server disk |
| `backup_list` / `backup_verify(backup_id)` | List, and re-hash against the manifest. | - |
| `plan_restore(device, backup_id)` | Diff a backup against the device; returns a plan handle. | - |
| `plan_account_change(device, account, action, role)` | Plan a role change/removal and say what the lockout guard would refuse. | - |

Plans are held in memory for 10 minutes and nothing in this version applies
them. `apply_plan` is Phase B and will require a confirmation the server renders
from the stored plan; a host that cannot show it will get plan-only behaviour.

## Safety rules (each one has a test)

- **No credential crosses MCP.** `device` is an enum of configured names, so an
  address or unknown name fails schema validation before any code runs. No tool
  input is named like a secret, host or path. Password changes, account creation
  and ONVIF writes are not offered at all.
- **Outputs are scrubbed.** The device password and its HTTP Basic form are
  removed from every result and error; parameter values whose names look like
  credentials (`*Password*`, `*Community*`, `*PSK*`, `*Secret*`, `*Token*`) are
  `[redacted]`. A bug inside a module is reported as `internal error: <Class>`,
  never its message.
- **Nothing on stdout but the protocol.** The server never imports the CLI
  (which owns the Rich console); a subprocess test runs the real entry point and
  checks the session works.
- **Backups go to one fixed directory.** `backup_id` is validated
  (`backup-...`, no `/`, no `..`); there is no destination argument.

Not exposed by design: factory default, reboot, firmware, arbitrary parameter
set, lockout overrides, crash/server-report downloads, network-parameter
restores, fleet writes, and raw config/backup bytes.
