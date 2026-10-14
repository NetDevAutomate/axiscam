# MCP server for axiscam — design decision (council arbitration)

Date: 2026-10-14. Brief: `2026-10-14-mcp-server-council-brief.md`. Seats (verbatim, in
`council/`): `claude-opus-5.5` (1,802 words), `gpt-5.6-sol` (1,249), `deepseek-3.2` (1,765 —
its first draft was a tool-narration preamble; the clean copy is kept). Arbitration is by the
coordinator (claude-fable-5.1); every factual claim that decides a question below was checked
against source or PyPI on the day, and the result is stated.

## Seat reliability, checked first

- **opus** and **gpt** verified the brief against code and primary sources; their refutations
  all held up (see Errata). Both are weighted fully.
- **deepseek**'s review contains refuted facts that carry its main dissent: it dated `mcp` 2.3.0
  and `fastmcp` 4.1.0 to 2024 (PyPI: uploaded 2026-10-02 and 2026-10-08) and "could not verify"
  the 2026-07-28 spec (it is current); it claimed the official SDK "requires stdio/HTTP" for
  tests (v2 `Client(server)` runs in memory — SDK docs) and that `fastmcp` has "zero
  transitive deps beyond pydantic" (`fastmcp` 4.1.0 requires `fastmcp-slim[client,server]`,
  which builds on `mcp` v2); it confirmed F1 = 32 modules (29) and said `params` is reachable
  via `collect_report(full=True)` (`params` has no `read()`, it is not a `ResourceModule`).
  Its **Q1 dissent is discounted** on that basis. Two of its points survive on merit and are
  adopted below (per-device concurrency; live state is not a resource).

## Where they agree (adopted; agreement on an open question is evidence)

1. **Generic reader, not one tool per module.** `read_module(device, module)` gated by the
   device's live `available_resources()`; a module the device lacks returns `not_advertised`.
   Three of three.
2. **Server-minted plan handle for every write**; apply consumes only a previously returned
   handle; planning writes nothing. Three of three.
3. **Synchronous, bounded long operations; no tasks extension in v1.** Three of three.
4. **Same distribution, optional extra `axis-cam[mcp]`, second script `axiscam-mcp`.** Three.
5. **`unknown` is a first-class status on the wire, never a default value.** Three.
6. **Never exposed**: factory default, reboot, arbitrary parameter set, lockout overrides /
   last-administrator removal, crash-report/server-report download. Three of three (union in
   §Never exposed).

## Where they diverge — picked, with the reason and the cost

| Q | opus | gpt | deepseek | **Pick** |
|---|---|---|---|---|
| Q1 SDK | official `mcp` v2 | official `mcp` v2 | `fastmcp` v4 | **`mcp` v2 (`MCPServer`)**. Owner-maintained, moves with the spec, in-memory `Client(server)` for tests, `Resolve(Elicit(...))` spans legacy elicitation and 2026-07-28 MRTR in one tool body (SDK docs, verified). deepseek's three reasons were factually wrong. Cost: fewer batteries — none are needed for a thin stdio adapter. |
| Q2 resources | immutable data only (`axiscam://checks`, `schemas/{module}`, `backups/{id}/manifest`); live state is a tool | all 26 modules as `axis://` resources *and* the generic tool | no resources | **opus.** `resources/read` carries `ttlMs`/`cacheScope` by contract (2026-07-28), so live device state as a resource is a semantic mismatch, and most hosts never let the model read resources itself. gpt's URIs stay as the schema catalogue only. Cost: no URI-addressable device reads; the generic tool is the one path. |
| Q2 params | `query_params(prefix REQUIRED, limit≤200, cursor)`, redacted | `read_params(prefix/query, cursor, hard max 100)` | via `collect_report(full)` (impossible) | **opus + gpt**: prefix required, cap 200, cursor, `total`; **redaction is mandatory, not optional** — verified today: the M3216 tree holds 12 secret-looking names incl. live SNMP community strings, a proxy password and an 802.1X key password. |
| Q2 fleet | one `fleet_read(selection, op∈{info,report,audit})` | none | timeouts on "fleet tools" | **opus**: one read-only fan-out tool mirroring `--all/--group`; timeouts become `status:"timeout"` rows; backup is **not** fleet-exposed. |
| Q3 confirmation | handle + `Resolve(Elicit)` rendered from the *stored* plan; fail closed where the host cannot elicit; **drift check at apply** | handle + MRTR `input_required`; plan-only on non-MRTR hosts | handle only, "works identically everywhere" | **opus mechanism, gpt handle properties.** Handle: `secrets.token_urlsafe(16)`, single-use, 600 s TTL, bound to device name, serial read at planning, and a SHA-256 of the frozen changes. Apply re-reads serial and every planned current value; any drift aborts the whole plan. Host tool-approval is **not** the human gate (auto-approve modes exist). deepseek's "works everywhere" is precisely the model-forgeable path — rejected. Cost: on a host without elicitation/MRTR the server is plan-only. |
| Q3 phasing | ship read + plan tools first; add `apply_plan` once elicitation is verified on Kiro and Claude Code | build apply with MRTR | build apply | **opus.** Phase A = 12 read/plan tools; Phase B = `apply_plan` after a live check that the Kiro host surfaces the elicitation. Keeps the first deliverable countable and never ships a write path whose gate is unproven. |
| Q4 errors | 3 tiers; envelope `{status: ok\|not_advertised\|unreadable, value\|null, reason}`; catch `AxisPermissionError` before its parent | 3 channels, same split | auth/connection → JSON-RPC `-32000`; `AxisUserError` → `-32602` | **opus/gpt.** Domain failures are tool results (`isError` for whole-call: 401, connection, config, lockout, plan errors, non-Axis exceptions scrubbed); per-item `unreadable` for 403 / not-supported / device errors; JSON-RPC only for protocol faults (unknown tool, invalid args, resource not found `-32602`). deepseek's mapping puts device outcomes in the protocol channel — wrong layer. |
| Q5 output | envelope models in `schemas.py`; `value: dict` + `model` name; exact schema published as a resource; no 26-way `oneOf` | MCP-facing DTOs, same shape | device models' `model_json_schema()` directly | **opus/gpt.** Note `AuditReport`, `Finding`, `DeviceReport`, `RestorePlan`, `BackupManifest` are dataclasses, not pydantic (verified) — DTOs are needed anyway. |
| Q6 bounds | backup one device per call, 120 s; `fleet_read` concurrency 4, 120 s deadline; `notifications/progress` when a `progressToken` is present | per-device 180 s, overall 10 min, concurrency 2 for backup | 300 s, progress via server log | **converged**: reads/audit 120 s per call; backup one device per call, 180 s; `notifications/progress` when the request carries a token; unfinished fleet devices returned as `timeout` rows. |
| Q7 layout | `src/axis_cam/mcp_server/` (not `mcp`, which misleads beside `import mcp`); prerequisite extraction of a console-free `axis_cam/connection.py` (`password` `repr=False`) and `axis_cam/fleet.py` with `on_progress` | `axis_cam/mcp/`; inject a `DeviceResolver`; never depend on Typer | `axis_cam/mcp/`; patch `DeviceContext.open` | **opus layout + gpt's injection (same idea).** `cli/context.py` imports typer, prints to the Rich console and raises `typer.Exit` (verified `context.py:13,17,114,119,151,156,165`); on stdio that corrupts JSON-RPC framing. So the seam is extracted first, the CLI keeps its behaviour, and the server never imports `axis_cam.cli`. deepseek's patch-the-CLI-seam is rejected. |
| Q7 test double | real `AxisDevice` + `respx` + verbatim fixtures; in-memory `Client(server)`; temp config dir with a **canary password**; `load_config.cache_clear()` | injected resolver + `FakeAxisDevice` + fake registry modules; `Client(server)` | patch `DeviceContext.open` + `FakeAxisDevice` | **both opus and gpt**: respx-backed real device for boundary and secrets tests (exercises the real credential path); a fake registered module for the "appears with no server change" test (the Phase 1 registry pattern). |
| Q7 first ten tests | concrete list, each forcing one production change; #6 (`repr(DeviceContext)` leaks the password) fails today | ten, similar shape | ten, FastMCP-specific | **opus's list** (below), with gpt's #5 (params cap) folded in. |
| Q8 secrets | 10 tests incl. base64 Basic, Digest `response=`, stderr+caplog with httpx loggers, subprocess stdio frames | 8 | 5 | **opus's 10** + gpt's "no tool input property matches a credential name" (= opus #9) — eleven assertions. |
| Q9 | 9 exclusions | 6 | 5 incl. stream URLs | **Union**, below. |

## Where they agree against the coordinator (the brief's author)

1. **F5 is wrong for a server.** The brief named `cli/context.py::DeviceContext` as the seam.
   opus and gpt both rejected it: it is Typer- and console-bound. The seam must be extracted.
2. **Two-phase sequencing is not human consent.** The brief framed write safety as
   plan → apply(handle). opus and gpt both said a handle proves ordering, not approval — the
   model that received it can replay it. Confirmation needs an out-of-band question the model
   does not author.
3. **F4 is mostly unexposable under the brief's own rule.** VAPIX `add`/`set_password` and every
   ONVIF write take a password argument (`onvif_users.py:218`, verified). Only `set_role` /
   `remove` / params restore survive the "no credential crosses MCP" constraint.
4. **Live device state is not a resource** (opus, deepseek) — the brief's Q2 had floated it.

## Brief errata (all verified)

- F1: **29** registered modules (26 `ResourceModule`s; `params`, `logs`, `serverreport` have no
  `read()`), not 32.
- Coverage floor is **72** (`pyproject.toml:115`), not 71.
- I5: the class is `AxisAuthenticationError`; `AxisPermissionError` subclasses it
  (`exceptions.py:48,64`) — catch order matters.
- Audit status wire value is `"n/a"` (`audit.py:63`), key `id`.
- I1 overstated gating: `api_id=None` modules are never gated, and empty discovery includes
  every module (`devices/base.py:305-318`). The S3008's missing `param.cgi` is therefore a
  *read error*, not "not advertised" — the envelope's `unreadable` status is where it lands.
- "`0600` config" is operational history; `load_config` does not enforce a mode.

## Defects in the existing library the server would inherit (fix-don't-defer: all filed here, fixed in Phase A where marked)

| # | Finding | Evidence | Disposition |
|---|---|---|---|
| D1 | `DeviceContext.password: str` with default repr — any traceback or log of the object prints the password | `cli/context.py:40,58` | **Fix in Phase A** (extraction gives the new type `field(repr=False)`; a test asserts the canary is absent from `repr`). |
| D2 | `apply_param_restore` re-checks neither serial nor value drift; only the planning step checks serial | `restore.py:188-191` vs `:203` | **Fix in Phase B** with the drift check; the library gains it, the CLI inherits it. |
| D3 | `params.export()` and every `backup/params.json` contain live credentials (SNMP community strings, proxy password, 802.1X key password) with no manifest declaration | live read, 12 names | **File**: manifest must declare "contains credentials: …" (honest-manifest rule) and `backup restore` should skip them unless `--include-secrets`; the MCP `query_params` redacts them from day one. Separate PR. |
| D4 | `load_config` is `@lru_cache(maxsize=1)` — a long-lived server never sees config edits | `config.py:415` | **Phase A**: the server resolves config per call through the injected resolver; document the restart requirement until the cache is scoped. |
| D5 | Fleet runner writes `console.status` to stdout | `cli/fleet.py:109` | **Fix in Phase A** by the console-free `axis_cam/fleet.py` extraction with `on_progress`. |
| D6 | Per-device concurrency: two tools on the same camera share nothing today; the brief did not ask (deepseek's question, adopted) | design gap | **Phase A**: one `AxisDevice` per tool call; a per-device `asyncio.Lock` around any write in Phase B. |

## The decision

**Phase A — read and plan (12 tools), `mcp` v2, stdio, TDD.**

| # | Tool | R/W |
|---|---|---|
| 1 | `list_devices()` — name, type, groups, host; never credentials | R |
| 2 | `list_modules(device)` — advertised / not advertised / never gated | R |
| 3 | `read_module(device, module)` — `module` is an enum built from the registry; envelope `{status, value, reason, model}` | R |
| 4 | `device_report(device, full=false)` | R |
| 5 | `security_audit(device, status=null)` | R |
| 6 | `fleet_read(selection, op∈{info,report,audit})` — concurrency 4, 120 s, timeout rows | R |
| 7 | `query_params(device, prefix, limit≤200, cursor)` — prefix required, secrets redacted | R |
| 8 | `backup_create(device)` — fixed server-side root, returns `backup_id`; 180 s | R (device) |
| 9 | `backup_list()` | R |
| 10 | `backup_verify(backup_id)` | R |
| 11 | `plan_restore(device, backup_id)` → handle | plan |
| 12 | `plan_account_change(device, account, set_role\|remove)` → handle | plan |

Resources (immutable only): `axiscam://checks`, `axiscam://schemas/{module}`,
`axiscam://backups/{id}/manifest`. `tools/list` is deterministic (sorted) with `ttlMs`.

**Phase B — `apply_plan(plan_id)`** with `Resolve(Elicit(...))` rendered from the stored plan,
single-use handle, 600 s TTL, serial + value-drift re-check, per-device lock, fail closed on a
host that cannot confirm. Gate to start Phase B: a live check that the Kiro host surfaces the
elicitation (if it does not, Phase B ships plan-only and says so).

Layout: `src/axis_cam/mcp_server/{server,devices,plans,schemas,redact}.py` +
`tools/{read,audit,backup,write}.py`; prerequisite extractions `axis_cam/connection.py`
(`DeviceConnection`, `password` `repr=False`, `open()`), `axis_cam/fleet.py` (console-free,
`on_progress`); the CLI's `DeviceContext` and `run_fleet` become thin wrappers over them.
Extra `axis-cam[mcp]` pinned `mcp==2.3.0`; script `axiscam-mcp`.

**First ten failing tests, in order** (each names the production change it forces):

1. `test_tools_list_deterministic_and_no_stdout_on_import` → `server.py`
2. `test_list_devices_never_contains_canary` → `devices.py`, `connection.py` with `repr=False`
3. `test_device_arg_is_config_enum_and_ip_rejected` → device enum built from config
4. `test_read_module_ok_ssh` → `tools/read.py`, envelope
5. `test_read_module_not_advertised_null_value` → `available_resources` wiring
6. `test_403_is_unreadable_401_is_error` → error mapping, except ordering
7. `test_query_params_requires_prefix_caps_200_redacts_secrets` → pager + `redact.py`
8. `test_audit_structured_equals_to_dict` → `tools/audit.py`
9. `test_backup_fixed_root_and_traversal_id_rejected` → `tools/backup.py`
10. `test_plan_restore_zero_writes_returns_handle` → `plans.py`

Secrets boundary (Phase A, eleven assertions): every tool's `content` and `structuredContent`
free of the canary, `base64(user:canary)` and a Digest `response=`; error texts and non-Axis
exceptions scrubbed; `capfd` stderr + `caplog` (httpx/httpcore at DEBUG) carry no canary or
`Authorization` header; resource URIs built only from names and ids; `repr(DeviceConnection)`
clean; `query_params` redacts `*Password*`, `*Passwd*`, `*Community*`, `*PSK*`, `*Secret*`,
`*Token*` keys; plan payloads redacted the same way; no tool input property matches
`(?i)pass|secret|community|token`; a subprocess stdio run emits only JSON-RPC frames.

**Never exposed** (union of the seats): factory default, reboot, firmware upgrade; arbitrary
parameter set; `allow_lockout` and removal of the last administrator; account creation,
password changes and all ONVIF writes (a secret would cross MCP); crash-report and
server-report download; `include_network` restores; `security harden` apply (the hardening
plan: "not by an agent"); ad-hoc host or credential arguments; fleet writes; raw config,
`.env`, logs or backup bytes as resources; stream URLs.

## Costs accepted

No URI-addressable live reads; no write reaches a device until Phase B's gate is met; a
host without elicitation/MRTR gets a plan-only server; `params` cannot be read whole over MCP.
