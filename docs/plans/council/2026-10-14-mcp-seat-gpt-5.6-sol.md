## Verified against code

- **Refuted:** F1 says 32 registered API modules. There are 32 Python files in the directory but only **29 `@register` classes**; `__init__.py`, `base.py`, and `registry.py` are infrastructure. `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/api/registry.py:28,80-87` defines the protocol/registry.
- **Confirmed:** resources are structural `read() -> BaseModel` modules and availability is discovery-gated; `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/devices/base.py:290-316`.
- **Confirmed:** reports preserve per-module errors/skips while auth/connection escape; `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/report.py:69-108`. Audit has five statuses and structured findings; `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/audit.py:57-64,100-129,750`.
- **Confirmed:** backup has explicit exclusion classes and hashes; create/verify are `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/backup.py:50-66,160,260`. Restore serial-binds the plan and verifies each parameter; `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/restore.py:171-231`.
- **Confirmed:** fleet catches only `AxisError`/`OSError`, retains order, and lets bugs propagate; `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/cli/fleet.py:80-110`.
- **Refuted:** the coverage floor is not 71; it is **72** at `/Users/ataylor/code/personal/network/axiscam/pyproject.toml:115`. Packaging is one script and has no MCP dependency (`:20-47`).
- **Confirmed publicly:** latest spec is **2026-07-28**; official `mcp` **2.3.0** uses `MCPServer`, supports that revision and legacy clients, and has `Client(server)` in-memory tests. `fastmcp` is **4.1.0** and built over the v2 engine. Sources: [official v2 notes](https://py.sdk.modelcontextprotocol.io/v2/whats-new/), [official testing](https://py.sdk.modelcontextprotocol.io/v2/get-started/testing/), [spec](https://modelcontextprotocol.io/specification/2026-07-28), [mcp PyPI](https://pypi.org/project/mcp/), [FastMCP PyPI](https://pypi.org/project/fastmcp/).
- Unavailable in this review runtime: `@mochi:mochi` (not configured); `session-db`, `home-assistant`, `kirocrew-core`, `time`, `kirocrew-computer`, `playwright-mcp`, `kirocrew-cron`, `studyloop`, and two unnamed servers (started with no tools).

## Q1 — SDK choice

**Pick: official `mcp` v2; three decisive reasons.** (1) It is the protocol owner’s stable line, reducing longevity risk and avoiding an extra framework layer. (2) `Client(MCPServer, raise_exceptions=True)` is the exact no-network test harness needed. (3) typed return annotations/Pydantic models generate and validate `outputSchema`, fitting pyright and this codebase’s existing models. FastMCP’s state/session/application machinery is valuable for larger apps, but is unnecessary dependency and conceptual weight for a thin stdio adapter.

## Q2 — Tool surface

**14 tools:** `list_devices` (RO, aliases/type only); `list_device_resources` (RO, live discovery); `read_resource` (RO, one available module); `read_params` (RO, prefix/query + cursor + limit); `collect_report` (RO); `run_security_audit` (RO); `create_backup` (device-RO, local-write); `verify_backup` (RO); `plan_param_restore`/`apply_param_restore`; `plan_vapix_account_change`/`apply_vapix_account_change`; `plan_onvif_account_change`/`apply_onvif_account_change`. Each apply accepts only a server-minted handle; planning returns exact changes and writes nothing. Initial account actions exclude any operation requiring a password.

Expose all **26 current `ResourceModule`s** through `axis://devices/{alias}/resources/{module}` plus the generic tool—not 26 tools. Resources support browse/read hosts; the tool gives portable agent invocation and typed errors. `list_device_resources` is authoritative per device. `read_resource` rejects unadvertised modules. `params` is separate and paginated/filtered; never return all ~1,500 entries by default (hard maximum 100, opaque cursor).

## Q3 — write confirmation without a console

**One mechanism: plan handle + MRTR confirmation + apply.** Planning stores an immutable plan under a random 256-bit, one-use handle for 10 minutes, bound to device alias, live serial, action, current-state fingerprint, and exact redacted changes. `apply(handle)` returns `input_required`; only an accepted continuation with SDK-validated request state re-reads serial/current state, consumes the handle atomically, calls the existing guarded writer, and verifies.

A host without MRTR is **plan-only**: apply returns structured `confirmation_unsupported` and performs zero writes. Do not add an ordinary “yes” argument; a model could supply it. Tests spy on every device writer: direct, forged, expired, replayed, rejected, stale-state, wrong-serial, and unsupported-host paths all record zero calls; only plan→accepted continuation records one.

## Q4 — Error model

**Three channels.** Expected domain failures (`AxisConnectionError`, authentication/permission, device/API/user/lockout/SOAP/config errors) become sanitized tool results with `isError=true`, stable `code`, retryability, device alias, and no credential/host internals. Per-module and per-device partial failures remain ordinary successful structured results with `status="error"`; audit could-not-read remains finding `status="unknown"`. JSON-RPC errors are reserved for malformed protocol requests, unknown tools, and server defects. Unexpected exceptions propagate to SDK sanitization.

## Q5 — Structured output

**Yes: every tool declares one Pydantic-derived output schema.** Use MCP-facing DTOs, not ad-hoc dictionaries. The generic reader returns a stable envelope (`device`, `module`, `status`, `model`, `data`, `error`); its dynamic `data` is JSON-valued because one call spans 26 model types. Firmware wire differences must be normalized by the library: REST/CGI device-info variants both become `BasicDeviceInfo`. If a genuine semantic variant remains, model it as a discriminated Pydantic union—never vary the undocumented shape by firmware.

## Q6 — Long operations

**One bounded strategy initially: synchronous calls with progress, no Tasks extension.** Backups use progress notifications per device/module, backup fleet concurrency 2, per-device timeout 180 seconds, overall five-device timeout 10 minutes, and cancellation cleanup. Crash-report download is not exposed. Add Tasks only after a supported host matrix proves demand; stdio synchronous progress is simpler and interoperable now.

## Q7 — Package layout and TDD order

**One optional extra, one script, six modules, ten tests.** Keep `axis_cam/mcp/` in the same distribution; add exact-pinned `axis-cam[mcp]` and `axiscam-mcp = axis_cam.mcp.__main__:main`. Modules: `server`, `models`, `devices`, `resources`, `operations`, `plans`; no core logic duplication.

First failing tests, in order: (1) `list_devices` omits credentials → config projection; (2) discovery lists only available resources → resolver; (3) unavailable `read_resource` never calls reader → gate; (4) model return has validated structured output → DTO/schema; (5) params requires limit/cursor and caps 100 → pager; (6) audit preserves all five statuses, especially unknown → audit DTO; (7) backup create then verify returns manifest/problems → backup adapter; (8) restore planning makes zero set calls and returns exact changes/handle → plan store; (9) forged/expired/replayed handle makes zero writes → handle validation; (10) MRTR rejection/unsupported host makes zero writes while accepted continuation applies once and reports per-change verification → confirmation/apply.

Use an injected `DeviceResolver` and `FakeAxisDevice` with fake registry modules for service tests; use official `Client(server)` for MCP tests. Do not patch CLI `DeviceContext.open`: the MCP layer must not depend on Typer. Keep `respx` only for existing wire-contract tests below the server boundary.

## Q8 — Secrets boundary tests

**Eight tests:** results recursively exclude configured username/password and known sentinel secrets; Pydantic `SecretStr` never serializes; each typed exception containing a sentinel is sanitized; unexpected exception text is SDK-sanitized; captured stderr/logging contains no sentinel; resource URIs contain alias/module only; tool schemas accept no password/credential field; plan handles/results contain redacted actions and hashes, never secret values. Run the sentinel scan across both `content` and `structured_content`.

## Q9 — What must not be exposed

**Six exclusions:** factory default/reboot/firmware upgrade (lockout/destructive, out of scope); arbitrary parameter set (bypasses plans); `allow_lockout` overrides (defeat library safety); VAPIX/ONVIF create or password rotation and ONVIF level change (require a secret crossing MCP); crash-report/debug archive (documented to contain passwords/network traces/images); raw config, `.env`, device host/username/password, logs, or backup file bytes as resources. Backups expose metadata/path and verification, not bulk sensitive content.

## Q10 — What this brief gets wrong

**Four incorrect/unsafe assumptions; one missing question.** Registered modules are 29, not 32. Coverage is 72, not 71. File mode `0600` is operational history, not enforced by `load_config`; startup must reject group/world-readable credential files. Finally, “host approval” is not proof of human confirmation and an ordinary `confirm=true`/handle call is model-forgeable.

The missing question: **what cryptographic/protocol evidence proves a human—not the calling model—approved this exact redacted plan, and which target hosts actually supply it?** Until the compatibility matrix answers that, unsupported hosts must remain plan-only.

## Where the other reviewers will be wrong

- They will choose FastMCP for convenience, paying for stateful application abstractions this thin adapter does not need while obscuring current official SDK practice Andy wants to learn.
- They will accept `apply(handle)` as confirmation. A handle proves sequencing, not consent; the model received it and can replay it.
- They will patch `DeviceContext.open` and couple MCP tests to Typer instead of injecting a presentation-neutral resolver and exercising the real in-memory MCP client.

## What the brief gets wrong

The material errors are **29 registered modules, coverage floor 72, and no code-enforced `0600` load invariant**. Its largest design blind spot is equating two-phase sequencing with human authorization; those are separate properties and need separate tests.
