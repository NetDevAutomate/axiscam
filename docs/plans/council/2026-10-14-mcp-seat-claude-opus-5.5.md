# Seat: claude-opus-5.5

## Verified against code
- F1 "32 modules": **refuted**. 29 `@register` classes, of which 26 are `ResourceModule`s. `params`, `logs` and `serverreport` have no `read()`.
- Coverage floor 71: **refuted**. It is `fail_under = 72` (`pyproject.toml:115`).
- I1 gating: **partly refuted**. `base.py:318` fails open (empty discovery means every resource is included). `api_id=None` modules (params, users, onvif_users, time, device_info) are never gated, so the S3008's missing `param.cgi` is a read error, not "not advertised".
- I5: there is no `AxisAuthError`; the class is `AxisAuthenticationError`. `AxisPermissionError` **subclasses** it (`exceptions.py:64`).
- I2/I7: readers do return pydantic models. `AuditReport`, `Finding`, `DeviceReport`, `RestorePlan` and `BackupManifest` are **dataclasses**. On the wire the audit status is `"n/a"` and the key is `id`.
- F5: **true for the CLI, unusable in a server**. `cli/context.py` imports typer, prints to `console = Console()` (stdout, `cli/app.py:19`) and raises `typer.Exit`. `run_fleet` writes `console.status` (`fleet.py:109`). Both would corrupt stdio JSON-RPC.
- **Live leak:** `DeviceContext` is a frozen dataclass with `password: str` and no `repr=False` (`context.py:40,58`).
- `apply_param_restore` (`restore.py:203`) re-checks neither the serial (only the planning step does, `:190`) nor whether values drifted since the plan.
- F4: VAPIX `add`/`set_password` and ONVIF `add`/`set_password`/`set_level` (`onvif_users.py:218`) all take a password. That conflicts with "no tool accepts a password".
- Hardening plan line 67: "Not by hand, **not by an agent**, and not by the fleet fan-out."
- "Community strings never stored": true for the REST `snmp` model. `params.export()` is returned and stored unfiltered. Whether it contains secrets is **unverified**.
- `load_config` is `@lru_cache` (`config.py:415`), so a long-lived server never sees config edits.
- Tests: 804 `def test_` functions; 875 not run.
- Spec and SDKs: **2026-07-28 "latest" confirmed**, including the tasks extension, MRTR, `ttlMs`/`cacheScope`, and "list endpoints no longer vary per-connection". `mcp` 2.3.0 (2 Oct 2026) has `MCPServer`, in-memory `Client(server)` and `Resolve`/`Elicit`. `fastmcp` 4.1.0 (8 Oct 2026) "builds on the MCP Python SDK v2".

## Q1 — SDK
**Official `mcp` v2 (`MCPServer`).**
1. fastmcp 4 depends on `mcp` v2 and adds Apps, code-mode, provider extras and Horizon. None of that is needed, and it doubles the surface that can break.
2. The primitives this design needs are in the official SDK: `Client(server)` for in-memory tests, and `Resolve(Elicit(...))`, which carries one confirmation body over legacy elicitation *and* 2026-07-28 MRTR. That is exactly what Q3 needs.
3. Longevity and learning: it is LF-governed, moves in lockstep with the spec and uses the spec's vocabulary. fastmcp has had three breaking majors in about two years.

I disagree with "fastmcp for batteries": none is needed.

## Q2 — Tool surface
**13 tools. Reads are tools; resources are used only for static or immutable data.**

| # | Tool | Purpose | R/W |
|---|---|---|---|
| 1 | `list_devices` | names, type, groups, host | R |
| 2 | `list_modules(device)` | advertised / not advertised / never gated | R |
| 3 | `read_module(device, module)` | `module` is an enum built from the registry | R |
| 4 | `device_report(device, full)` | `collect_report` | R |
| 5 | `security_audit(device, status?)` | `run_audit` | R |
| 6 | `fleet_read(selection, op∈{info,report,audit})` | bounded fan-out, one row per device | R |
| 7 | `query_params(device, prefix, limit≤200, cursor)` | redacted, paginated | R |
| 8 | `backup_create(device)` | fixed server root → `backup_id` | R (device) |
| 9 | `backup_list()` | ids and identity | R |
| 10 | `backup_verify(backup_id)` | `verify_backup` | R |
| 11 | `plan_restore(device, backup_id)` | → handle | W phase 1 |
| 12 | `plan_account_change(device, account, set_role\|remove)` | the only password-free account writes → handle | W phase 1 |
| 13 | `apply_plan(plan_id)` | confirmed with Elicit, apply, verify | W phase 2 |

- **Generic `read_module`, not 26 tools.** 2026-07-28 forbids tool lists that vary per connection, and 26 schemas would cost context on every turn. A module the device lacks returns `not_advertised`.
- **`params`:** there is no whole-tree read. A prefix is required, and results are capped at 200 with a cursor and `total`.
- **Resources:** `axiscam://checks`, `axiscam://schemas/{module}` and `axiscam://backups/{id}/manifest`, all immutable. Live device state is not a resource: `resources/read` is cacheable by contract, and most agent hosts never let the model read resources by itself.

## Q3 — Write confirmation
**A server-minted handle plus a server-rendered `Elicit`, failing closed on hosts that cannot elicit.**

- `plan_*` stores a plan in memory. The `plan_id` is `secrets.token_urlsafe(16)`. The plan records the device, the serial read at planning time, the frozen changes, their SHA-256, a 600 s TTL, and a single-use flag.
- `apply_plan` declares a `Resolve(Elicit(...))` parameter. The server renders the message from the *stored* plan, never from agent text. The SDK sends it as `input_required` on 2026-07-28 and as `elicitation/create` on legacy hosts.
- After confirmation, the server re-reads the serial and every planned value's current state. Any drift aborts the whole plan; otherwise it applies and verifies.
- **A host without elicitation or MRTR** gets `isError` "host cannot confirm; nothing written". Host tool-approval is *not* accepted as the gate: auto-approve and trust-all modes let the agent approve itself. Whether Kiro supports elicitation is unverified.
- **Tests:**
  - Unknown, expired, reused or tampered handles, and declined confirmations, each cause **zero** `param.cgi?action=update` and `pwdgrp.cgi` requests (respx `call_count == 0`).
  - An AST test shows write methods are referenced only in `plans.py`.
  - Every `readOnlyHint` tool runs against a router that raises on any write route.

## Q4 — Error model
**Three tiers:**
1. **JSON-RPC error** for protocol faults: unknown tool, invalid arguments (including a device not in the enum), resource not found (`-32602`).
2. **`isError` with `{status:"error", error:{type, message, device}}`** for whole-call failures:
   - 401, connection errors, `AxisConfigError` and `AxisLockoutError`;
   - plan expired, stale or serial mismatch, and a declined confirmation;
   - any **non-Axis exception**, with a scrubbed message. In a fleet call this fails the whole call; it is never turned into a device row.
3. **Success with a per-item status** for 403, `AxisApiNotSupportedError` and `AxisDeviceError`: `status:"unreadable"` plus the reason. Catch `AxisPermissionError` before its parent class.

Every read envelope is `{status: ok|not_advertised|unreadable, value: object|null, reason}`. `value` is null unless the status is `ok`, so no defaulted model is ever returned. The audit's `unknown` passes through verbatim, and the counts are always included.

## Q5 — Structured output
**Rule: every tool declares an `outputSchema` built from MCP-layer envelope models (`schemas.py`), not from the device models.**
- The `value` slot is `dict[str, Any]` plus a `model` name. The exact schema is published at `axiscam://schemas/{module}`.
- A 26-branch `oneOf` would add thousands of tokens to `tools/list` on every turn.

Example: `crypto_policy` (gated on `crypto-policy`, AXIS OS 12 only). On 11.x it returns `{"module":"crypto_policy","status":"not_advertised","value":null,"reason":"not in discovery"}`. On 12.x it returns `ok` with a value. The schema is the same in both cases.

## Q6 — Long operations
**Synchronous and bounded, with `notifications/progress` when the request carries a `progressToken`. No tasks extension.**
- `backup_create` handles one device per call, with `anyio.fail_after(120)` and no server report.
- `fleet_read` runs at concurrency 4 with a 120 s deadline. Devices that have not finished come back as `status:"timeout"` rows.
- Tasks add state and polling that hosts barely support; 36 s fits in one call.

## Q7 — Layout and TDD
**Same distribution, optional extra `axis-cam[mcp]`, script `axiscam-mcp`, package `src/axis_cam/mcp_server/`.**
- Not `axis_cam/mcp/`: a package named `mcp` beside `import mcp` misleads readers and tools.
- Modules: `server.py` (registration only), `devices.py`, `plans.py`, `schemas.py`, `redact.py`, `tools/{read,audit,backup,write}.py`.
- Prerequisite library extractions, which leave the CLI's behaviour unchanged:
  - move `DeviceContext` and `get_device_class` to `axis_cam/connection.py`, with `password` marked `field(repr=False)`;
  - create a console-free `axis_cam/fleet.py` with an `on_progress` callback.

**Test double:** a real `AxisDevice` with respx and the existing verbatim fixtures, an in-memory `Client(server)`, and a temporary `AXIS_CONFIG_DIR` holding a canary password, with `load_config.cache_clear()`. I would not patch `DeviceContext.open`: that bypasses the credential path that Q8 must prove.

First ten failing tests, in order:
1. `test_tools_list_deterministic_no_stdout_on_import` → `server.py`
2. `test_list_devices_never_contains_canary` → `devices.py`, `connection.py` with `repr=False`
3. `test_device_arg_is_config_enum_ip_rejected` → schema built from config
4. `test_read_module_ok_ssh` → `tools/read.py` and the envelope
5. `test_read_module_not_advertised_null_value` → `available_resources` wiring
6. `test_403_unreadable_401_isError` → error mapping and except ordering
7. `test_audit_structured_equals_to_dict` → `tools/audit.py`
8. `test_backup_fixed_root_traversal_id_rejected` → `tools/backup.py`
9. `test_apply_bad_handle_zero_writes` → `plans.py`
10. `test_apply_aborts_on_serial_or_value_drift` → the drift check before apply

## Q8 — Secrets tests
**Ten tests:**
1. Parametrize over every tool in `tools/list`: the canary, `base64(user:canary)` and the Digest `response=` value are absent from `content` and `structuredContent`.
2. Forced 401, timeout, httpx errors, and an echoing `AxisUserError`: the canary is absent from every error text.
3. Non-Axis exceptions: the canary is absent and no traceback is returned.
4. `capfd` on stderr plus `caplog` at DEBUG with the httpx/httpcore loggers on: no canary and no Authorization header.
5. Every resource URI and template is built only from device names and backup ids.
6. `repr(DeviceContext)` and `repr(AxisDevice)` do not contain the canary. **This fails today.**
7. `query_params` redacts `*Password*`, `*Community*`, `*PSK*` and `*Secret*` keys.
8. The `plan_restore` `current`/`target` values are redacted the same way.
9. No tool input property matches `(?i)pass|secret|community|token`.
10. In a subprocess stdio run, stdout carries only valid JSON-RPC frames.

## Q9 — Never exposed
**Nine:**
1. Account creation and password change (a secret would have to be an argument).
2. All ONVIF writes (`set_level` needs a password).
3. `allow_lockout=True` and removing the last administrator (an unauthenticated user could then create an admin).
4. Server-report download (contains configuration, 85 MB).
5. `include_network=True` restores (they cut their own connection).
6. `security harden` apply (the hardening plan says "not by an agent").
7. Ad-hoc host or credential arguments.
8. Fleet writes and generic `param set`.
9. Factory default and reboot.

## Where the other reviewers will be wrong
- They will reuse `cli/context.py` and `run_fleet` as "the seam". Both write Rich output to stdout, which breaks stdio framing.
- They will accept host tool-approval or a `confirm: true` argument as the human gate. The agent writes the arguments, and auto-approve modes exist.
- They will expose F4's account and ONVIF writes without noticing that each needs a password argument.

## What the brief gets wrong
- Wrong numbers and names: the module count (29/26, not 32), the coverage floor (72), `AxisAuthError`, and `n-a`.
- I1 overstates gating: it fails open, and the legacy-CGI modules are never gated.
- F4 is mostly unexposable under the brief's own credential rule, and the hardening plan forbids agent-applied harden.
- Bugs the server would inherit:
  - the `DeviceContext` repr leak;
  - no drift or serial check at apply;
  - an unfiltered `params` export;
  - the cached config.
- **The question to ask:** once account writes and harden are removed, is a two-phase apply path worth building in v1 for one restore and two role changes? §1 "ready" only requires *planning* a write. I would ship tools 1–12 first, then add `apply_plan` once elicitation is verified on Kiro and Claude Code.
