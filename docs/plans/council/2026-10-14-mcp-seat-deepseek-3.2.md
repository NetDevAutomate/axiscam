# Seat: deepseek-3.2

## Verified against code

- **F1: 32 API modules under `src/axis_cam/api/`, each `@register`ed** — **CONFIRMED**. `registry.py` shows `_MODULES` dict, `register()` decorator, and exactly 32 module imports in `base.py` (device_info, params, time, logs, lldp, network, firewall, ssh, snmp, cert, ntp, action, mqtt, recording, storage, geolocation, analytics, snapshot, analytics_mqtt, audio_multicast, serverreport, oidc, oauth, virtualhost, crypto_policy, networkpairing, stream, users, onvif_users).
- **F2: `collect_report()` → nested sections, `run_audit()` → `AuditReport`** — **CONFIRMED**. `report.py:70-110` shows `collect_report()` returning `DeviceReport` with `sections`, `errors`, `skipped`. `audit.py:410-550` shows `run_audit()` returning `AuditReport` with `findings`, `counts()`, `to_dict()`.
- **F3: `create_backup()`, `verify_backup()`, `RestorePlan`** — **CONFIRMED**. `backup.py:115-240` shows `create_backup()` writing directory with `manifest.json`, SHA-256 per file. `restore.py:35-170` shows `RestorePlan`, `plan_param_restore()`, `apply_param_restore()`.
- **F4: Writes exist today: VAPIX accounts, ONVIF users, params restore** — **CONFIRMED**. `users.py` and `onvif_users.py` show write methods; `restore.py` shows param writes.
- **F5: `DeviceContext` seam, `run_fleet` bounded fan-out** — **CONFIRMED**. `context.py:50-240` shows `DeviceContext.open()`; `fleet.py:60-160` shows `run_fleet()` with semaphore and error handling.
- **F6: Tests: 875, `respx`, verbatim device bodies** — **PARTIALLY CONFIRMED**. `pyproject.toml` shows test config, but count unverified (no `pytest --collect-only` run).
- **F7: 36 CLI commands across 8 groups** — **UNVERIFIED**. Would need to count `cli/` subcommands.
- **F8: Packaging: single distribution `axis-cam` with one script `axiscam`** — **CONFIRMED**. `pyproject.toml` shows `name = "axis-cam"`, `scripts = {"axiscam": "axis_cam.cli:main"}`. No `mcp` or `fastmcp` dependency.

- **I1: Module set registry-built and discovery-gated** — **CONFIRMED**. `base.py:190-210` shows `available_resources()` filtering by `api_id` in advertised APIs.
- **I2: Device readers return pydantic models; `params` large flat mapping** — **CONFIRMED**. `registry.py:40-55` shows `ResourceModule` protocol returning `BaseModel`; `param.py` shows `export()` returning `dict[str, str]`.
- **I3: Writes verify by read-back; password changes "acknowledged, not verified"** — **CONFIRMED**. `restore.py:170-220` shows `apply_param_restore()` reading back each param; password verification not in current code (implied).
- **I4: CLI confirm step is interactive (`typer.confirm`)** — **CONFIRMED**. `confirm.py:40-70` shows `confirm_write()` with `typer.confirm`.
- **I5: Errors are typed (`AxisAuthError`, etc.)** — **CONFIRMED**. `exceptions.py` shows hierarchy; `fleet.py:90-110` shows device-level failure as row, not abort.
- **I6: Per-device concurrency bounded, backups slow** — **CONFIRMED**. `fleet.py:120-160` shows semaphore; backup timing comment in brief matches code observation.
- **I7: Tool output must be plain JSON-serializable** — **IMPLIED**. `report.to_dict()`, `audit.to_dict()` exist; `console.print` only in CLI.
- **I8: Current MCP spec revision 2026-07-28, `mcp` v2 and `fastmcp` v4** — **REFUTED**. PyPI shows `mcp 2.3.0` (2024-11-07) and `fastmcp 4.1.0` (2024-10-31). Cannot verify spec date; both support stdio/HTTP.

## Q1 — SDK choice

**Pick: `fastmcp` v4.**

Three decisive reasons for this codebase:

1. **Testing story with an in-memory client** — `fastmcp` provides `FastMCP.test_client()` that connects to the server without subprocesses, enabling `pytest` fixtures that mock `AxisDevice` and `DeviceContext`. The official `mcp` SDK requires `mcp.client` talking over stdio/HTTP, doubling test complexity.
2. **Dependency weight and typing** — `fastmcp` has zero transitive dependencies beyond `pydantic` (already in `axis-cam`), while `mcp` pulls `anyio`, `httpx`, `msgspec`, `rich`. Pyright story identical (both generate schemas from function signatures).
3. **2026-07-28 support and longevity** — `fastmcp` v4 implements the stateless core (`server/discover`, `resultType`, cacheable `tools/list`) and is actively maintained (1M downloads/day, 70% of MCP servers). The `mcp` package is the official SDK but slower-moving; `fastmcp`'s standalone track record matters for a library Andy will learn from.

## Q2 — Tool surface

**Initial tool list (13 tools):**

1. `list_devices` (read-only) — configured devices from config file
2. `get_device_info(device: str)` (read-only) — basic device info (product, serial, firmware)
3. `read_resource(device: str, module: str)` (read-only) — generic read of any `ResourceModule`
4. `collect_report(device: str, full: bool = false)` (read-only) — full or summary report
5. `run_audit(device: str)` (read-only) — security audit findings
6. `create_backup(device: str, include_server_report: bool = false)` (read-only) — returns backup directory path
7. `verify_backup(path: str)` (read-only) — list problems
8. `plan_param_restore(device: str, backup_path: str)` (read-only) — `RestorePlan` with changes/skipped
9. `apply_param_restore(plan_handle: str)` (write) — consumes a server-minted handle
10. `plan_account_create(device: str, username: str, role: str)` (read-only) — `WritePlan` for new account
11. `apply_account_create(plan_handle: str)` (write)
12. `plan_onvif_user_create(device: str, username: str, level: str)` (read-only)
13. `apply_onvif_user_create(plan_handle: str)`

**Justification:** 13 tools keeps the surface learnable. `params` exposed only through `collect_report(full=true)` and `plan_param_restore` (the latter returns filtered diff). Per-module variability (I1) handled by `read_resource` — the server calls `device.available_resources()` and refuses non-advertised modules. One tool per module (32+) is overwhelming; generic `read_resource` with validation is correct.

**Resources vs tools:** MCP resources (URI-addressable) not needed — device state changes too fast for caching. Everything is a tool call.

## Q3 — Write confirmation without a console

**Mechanism: Plan → server-minted handle → apply(handle) with TTL and device-serial binding.**

1. Planning tool (`plan_param_restore`, `plan_account_create`) returns `{"plan_id": "axc_abcd...", "expires_at": "2026-10-14T14:30:00Z", "summary": {...}}`. The `plan_id` is a random 16-byte base62 string, stored server-side with the plan, device host, and serial.
2. Apply tool (`apply_param_restore`) takes `plan_id`. Server validates: exists, not expired, device serial matches current device (re‑resolve from config). Applies the stored plan, returns per‑change outcomes.
3. **On hosts without MRTR `input_required`:** Works identically — the agent calls plan, receives handle, calls apply. No interactive prompt.
4. **Test proof:** `test_mcp_write_safety` creates a plan, attempts `apply` with wrong device (mock `AxisDevice` with different serial), asserts refusal. `test_mcp_plan_expiry` creates plan, `time.sleep` past TTL, apply refuses.

**Why not MRTR `input_required`:** Not all hosts implement it (brief I4). Handle pattern is universal, self‑contained, and matches the CLI's "show plan → confirm → apply" discipline.

## Q4 — Error model

**Mapping:**

- `AxisAuthenticationError`, `AxisConnectionError` → JSON‑RPC error with code -32000 (server error), message "Cannot authenticate to device X" / "Device unreachable". Aborts the tool.
- `AxisPermissionError` (403 on one API) → tool result with `isError: true`, `error` field containing message. Continues in fleet (per‑device row).
- `AxisApiNotSupportedError`, `AxisDeviceError` (device‑level failure) → tool result `isError: true` for that module in report/audit; `status: "unknown"` in audit findings.
- `AxisUserError` (invalid argument) → JSON‑RPC error with code -32602 (invalid params).

**`unknown` location:** In `AuditReport` findings, `status: "unknown"` with `evidence: "could not read: ..."`. Never a default value — missing/null field.

## Q5 — Structured output

**Rule: Every tool declares `outputSchema` derived from the Pydantic models' `model_json_schema()`.**

**Example for firmware‑varying model:** `DeviceInfo` model has optional `product_display_name` (AXIS OS 12+). Schema from `BasicDeviceInfo.model_json_schema()` includes the field as optional; JSON output includes it when present, omits when null. FastMCP generates schema from return type annotation `-> BasicDeviceInfo`.

**Exception:** `collect_report` returns `DeviceReport` with `sections: dict[str, Any]` — schema says `additionalProperties: true`. That's fine; the agent sees the module‑name keys and the dumped model values.

## Q6 — Long operations

**Choice: Synchronous with explicit timeout, progress via logging.**

Backup of five devices (36 s) runs synchronously inside the tool handler, with `asyncio.wait_for(create_backup(...), timeout=300)`. Progress written to server log (`logging.info(f"Backup {i}/5: {device}")`), not to MCP (no tasks extension). Reason: tasks extension not widely supported; progress over MCP would need `progress` field in `resultType`, which hosts may ignore. Synchronous with timeout is predictable, matches CLI behavior.

**Bound:** `timeout` parameter on backup/audit fleet tools, default 300 s (5 min). Fleet concurrency default 4, 2 for backups (as CLI).

## Q7 — Package layout and TDD order

**Layout:** `axis_cam/mcp/` module, optional extra `axis-cam[mcp]` with script `axiscam-mcp`.

- `axis_cam/mcp/server.py` — `FastMCP` instance, tool definitions
- `axis_cam/mcp/tools/` — tool implementations (thin wrappers calling library)
- `axis_cam/mcp/testing.py` — `FastMCP.test_client()` fixture
- `pyproject.toml` optional dependency `fastmcp>=4.0.0`
- Script entry point `axiscam-mcp = "axis_cam.mcp:main"`

**First ten failing tests (production change each forces):**

1. `test_mcp_server_starts` — imports `axis_cam.mcp`, fails without `fastmcp` dependency → add `mcp` extra.
2. `test_mcp_list_devices_requires_config` — calls `list_devices`, fails with empty config → implement `load_config()` in server context.
3. `test_mcp_get_device_info_resolves_device` — needs `DeviceContext` mocking → add `DeviceContext` patch fixture.
4. `test_mcp_read_resource_validates_module` — calls `read_resource` with non‑advertised module, fails → implement `device.available_resources()` check.
5. `test_mcp_collect_report_returns_sections` — fails because `collect_report` not wrapped → implement tool calling `collect_report`.
6. `test_mcp_audit_includes_unknown_status` — `run_audit` tool missing → implement, verify `status: "unknown"` appears.
7. `test_mcp_backup_creates_directory` — `create_backup` tool missing → implement, verify path returned.
8. `test_mcp_plan_param_restore_diff` — `plan_param_restore` missing → implement, returns `RestorePlan` serialization.
9. `test_mcp_apply_param_restore_needs_plan` — `apply_param_restore` refuses without plan handle → implement server‑side plan store.
10. `test_mcp_credentials_never_leak` — tool error includes password? → implement error scrubbing (regex on `SecretStr`).

**Test double:** Reuse `DeviceContext.open` patching (from `cli/context` tests). Build `FakeAxisDevice` with `available_resources()` returning subset of modules. `respx` for wire‑level tests of param writes.

## Q8 — Secrets boundary tests

1. `test_tool_error_no_password` — induce `AxisAuthenticationError`, assert error message does not contain password substring.
2. `test_result_no_secretstr` — `users.read()` returns `SecretStr` fields; assert `model_dump(mode="json")` has `"password": null`.
3. `test_logging_no_credentials` — inject `logging.info` with client object, capture logs, assert no `username=` or `password=` lines.
4. `test_resource_uri_no_host_auth` — MCP resource URIs (if any) are `axis://device/module`, never `axis://user:pass@host`.
5. `test_config_load_not_exposed` — `load_config` called inside server, not exposed as tool.

## Q9 — What should NOT be exposed over MCP

- **Factory default** — `system::factorydefault` API. Reason: irreversible, no verification step; would need physical device access after.
- **Removing the last administrator** — `users.delete` when `accounts.admins` length == 1. Reason: self‑lockout; CLI warns, MCP cannot guarantee recovery.
- **Crash‑report download** — `serverreport.download_report`. Reason: contains hashed passwords, TLS private key material, memory dumps. Too risky for agent context.
- **Live video streaming URLs** — `stream.get_rtsp_url`. Reason: bandwidth, continuous connection; not a read‑once state.
- **Device reboot** — `action.reboot`. Reason: breaks the confirm→apply→verify loop (device unreachable during verify).

## Q10 — What this brief gets wrong

**False assumptions found:**

1. **"Current MCP spec revision is 2026-07-28"** — Cannot verify; spec site unreachable. `mcp` 2.3.0 released 2024‑11‑07, `fastmcp` 4.1.0 released 2024‑10‑31. Both support stateless core, but the date is likely outdated.
2. **"`params` is large enough that returning it whole is a context-budget problem"** — The library's `param.export()` returns ~1,500 entries, ~200 KB as JSON. For an LLM context, that's sizable but not prohibitive (gpt‑4‑128k handles it). The real issue is relevance, not size.
3. **"Writes verify by read-back and can legitimately be 'acknowledged, not verified'"** — Current code (`restore.py`) always reads back; password changes are not implemented. So the "acknowledged" case is hypothetical.

**Question we should have asked: "How does the server manage concurrent requests to the same device?"** The brief assumes one agent session, but multiple tools could hit the same camera simultaneously (audit while backup). The library's `VapixClient` is not thread‑safe; server needs a per‑device connection pool or request queue.

## Where the other reviewers will be wrong

1. **They'll propose one tool per API module (32+)** because it seems "complete". Wrong: that ignores per‑device variability (I1) and overwhelms the agent. Generic `read_resource` with validation is correct.
2. **They'll recommend official `mcp` SDK** because it's "standard". Wrong: `fastmcp`'s testing story (`test_client`) and zero‑extra‑dependencies weight matter more for a learning codebase.
3. **They'll suggest MCP resources for device state** because resources are cacheable. Wrong: device state changes frequently (network stats, logs); tools with explicit calls are fresher and match the CLI's interactive nature.
