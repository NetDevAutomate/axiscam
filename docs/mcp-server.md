# MCP server

`axiscam-mcp` exposes the `axis_cam` library to an MCP host (Kiro, Claude, any
client speaking the Model Context Protocol) over stdio. Twelve tools read and
plan; one, `apply_plan`, writes -- and only after the server has asked the human
to confirm. Design record:
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

## Layout

```
src/axis_cam/mcp_server/
  server.py      composition root: build_server(), TOOL_NAMES, main()
  deps.py        per-server bundle: resolver, plan store, backup root, enums, helpers
  schemas.py     result models
  devices.py     DeviceResolver protocol, ConfigResolver, device-name enum
  plans.py       single-use plan store
  redact.py      Scrubber and parameter redaction
  resources.py   read-only resources
  tools/read.py, audit.py, backup.py, write.py   each exposes register(deps)
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
| `apply_plan(plan_id)` | Ask the human to confirm the stored plan, then apply it. | **device** |

## Resources

Read-only, and fixed while the server runs, so a host may cache them. Live
device state is never a resource; that is what the read tools are for.

| URI | Content |
|---|---|
| `axiscam://checks` | Every check `security_audit` runs: id, title, severity, guide reference, and for parameter checks the parameter and hardened values. Derived from the audit itself, so it cannot drift. `data_dependent` names the checks that only appear when their data is readable. |
| `axiscam://schemas/{module}` | JSON Schema of the `value` `read_module` returns for that module. |
| `axiscam://backups/{backup_id}/manifest` | A backup's manifest, including `contains_credentials` (names only). Same `backup_id` validation as the tools. |

## Applying a plan

`apply_plan(plan_id)` is the only write. In order:

1. **The host must be able to ask a human.** The server checks that the client
   declared the MCP *elicitation* capability. If not, the call is an error and
   nothing is written: the model that holds a plan handle cannot approve its own
   plan, and a host's tool auto-approve is not a human decision either.
2. **The server renders the question from the stored plan** -- device, serial
   number and every change (credentials redacted) -- never from model input.
   Decline or cancel writes nothing and keeps the plan.
3. **Single use.** An approved plan is consumed whatever happens next.
4. **Same device, unchanged.** The serial number is re-read and must match; for a
   restore every planned parameter must still hold the value the plan saw; for an
   account the role must be unchanged. Otherwise `refused`.
5. One write at a time per device (a lock), each parameter verified by reading it
   back; the library's lockout guard still applies to account changes.

Plans live in memory for 10 minutes; a restart forgets them.

**Host support, checked 2026-10-15:** kiro-cli 2.30.0 declares *no* client
capabilities when it connects (`initialize` from "Q DEV CLI" carries
`capabilities: {}`), so in a Kiro CLI or Kiro Crew session `apply_plan` refuses
and the plan tools are the useful part. Kiro IDE 0.10+ and other hosts with
form elicitation (Claude Desktop, VS Code) can apply. Until then, apply with the
CLI: `axiscam backup restore` / `axiscam accounts set-role`.

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
set (only a stored, confirmed plan), lockout overrides, crash/server-report downloads, network-parameter
restores, fleet writes, and raw config/backup bytes.
