# Council brief — an MCP server for axiscam

Date: 2026-10-14. Repo: `/Users/ataylor/code/personal/network/axiscam` (`main` at `6cbaa22`).
This brief is answered independently by several model families; a coordinator arbitrates.
**Do not hedge toward consensus.** Where you disagree with what another careful engineer
would say, say so and say why — disagreement is what this exercise buys.

Read this file in full, then **verify its claims against the code before planning around
them.** Files worth reading first: `src/axis_cam/api/registry.py`, `src/axis_cam/devices/base.py`,
`src/axis_cam/report.py`, `src/axis_cam/audit.py`, `src/axis_cam/backup.py`,
`src/axis_cam/restore.py`, `src/axis_cam/cli/confirm.py`, `src/axis_cam/cli/context.py`,
`src/axis_cam/cli/fleet.py`, `src/axis_cam/config.py`, `docs/architecture.md`,
`docs/plans/2026-10-12-admin-and-modularity-review.md` (the programme that produced the
current shape, with every live-device finding), `docs/plans/2026-10-14-hardening-pass-plan.md`.

Rules for answering: read-only. Do **not** modify files, do **not** run git commands that
write, do **not** contact any device on the network (the devices in the config are
production cameras). Reads scoped to this repository plus public documentation.

## 1. Who the deliverable is for, and what "ready" means

Andy — a senior infrastructure engineer, strong intermediate in Python, who last wrote an
MCP server over a year ago — will use the server from Kiro, Claude Code and similar agent
hosts to read device state, run the security audit, create backups and (gated) apply
changes to his own Axis cameras. He also wants to *learn* current MCP practice from the
code, so the design must be explainable, not merely working.

"Ready" means: an agent host can list the configured devices, read any registered resource
on a device, run `security audit` and read the findings as structured data, create and
verify a backup, and **plan** a write — all without the agent ever seeing a credential — and
no write reaches a device without the same plan → confirm → apply → verify discipline the
CLI enforces today. Tests prove each of those sentences.

## 2. Hard constraints — not up for review

- **Core-as-library, thin wrapper.** The MCP server is a presentation layer over the
  existing `axis_cam` package, exactly as `axis_cam/cli/` is. It introduces **no new device
  contract**: every device read goes through the registry (`ResourceModule.read()`),
  `collect_report`, `run_audit`, `create_backup`/`verify_backup`, `RestorePlan`; every write
  goes through the library's existing write paths with their guards (lockout guard,
  last-administrator refusal, serial-number guard, read-back verification).
- **Credentials never cross the MCP boundary.** Device credentials come from the existing
  config file (`load_config`, `~/.config/axiscam/config.yaml`, `0600`) and are resolved
  inside the server; no tool accepts a password as an argument and no tool result, error,
  log line or resource contains one. SNMP community strings and ONVIF/VAPIX passwords are
  already never stored by the library — the server must not re-introduce them.
- **Write safety is a protocol, not a flag.** Writes are two-phase: a planning call returns
  the exact device changes; an apply call performs *only* a previously returned plan and
  verifies by re-reading. Fleet fan-out (`--all`/`--group`) is read-only, as in the CLI.
- **Python ≥ 3.12, `uv`, `ruff`, `pyright` (0 errors), `pytest` with the coverage floor in
  `pyproject.toml` (currently 71 — the floor only ever rises).** TDD: every behaviour is
  introduced by a failing test first; tests run with no device, no network.
- **Transport: stdio first.** Streamable HTTP is optional and, if offered, binds to
  loopback only by default.
- **Secure defaults already won in the library stand**: explicit `https`, refusal of Basic
  over plain HTTP, `--auth auto` following the device's challenge, errors propagate (an
  unreadable setting is `unknown`, never a default).

## 3. Invariants that would make a naive plan wrong (runtime truths, no build error)

1. The module set is **registry-built and discovery-gated**: `AxisDevice.available_resources()`
   depends on the device's live API discovery document; two devices expose different module
   sets (the S3008 recorder has no `param.cgi` at all). A static tool list that hard-codes
   modules will advertise tools that fail on some devices.
2. Device readers return **pydantic models**; `collect_report` and `create_backup` already
   serialise them. There is one payload that is not a model: `params` (a flat
   `{"root.Group.Name": "value"}` mapping of ~1,500 entries) — large enough that returning
   it whole from a tool is a context-budget problem for the calling agent.
3. **Writes verify by read-back and can legitimately be "acknowledged, not verified"**
   (password changes). The CLI prints that distinction; the server must preserve it in
   structured output rather than collapsing to success/failure.
4. The CLI's confirm step is **interactive** (`typer.confirm`). MCP has no console; the
   2026-07-28 protocol revision replaced server-initiated requests (including
   `elicitation/create`) with the Multi Round-Trip Request pattern (`resultType:
   "input_required"`), and not every host implements it. Confirmation therefore needs a
   design, not a port.
5. **Errors are typed** (`AxisAuthError`, `AxisConnectionError`, `AxisPermissionError`,
   `AxisUserError`, `AxisApiNotSupportedError`, ...). A device-level failure on one device
   in a fleet read is **that device's row**, not an abort; a bug in the operation itself
   must propagate (fleet runner rule).
6. Per-device concurrency is bounded (semaphore, default 4, 2 for backups) and backups are
   slow (36 s for five devices, 85 MB crash reports). Long operations need a shape
   (progress, or the tasks extension, or a bounded synchronous call with a stated timeout).
7. Tool output goes to the agent's context: Rich console rendering is wrong here (the CLI
   already had a `--json` wrapping bug from `console.print`); structured results must be
   plain JSON-serialisable data with an `outputSchema`.
8. The current MCP spec revision is **2026-07-28** (stateless core — no `initialize`
   handshake, `server/discover`, `resultType` on every result, cacheable `tools/list` with
   `ttlMs`/`cacheScope`, deterministic tool order recommended, tasks moved to an
   extension). The official Python SDK is **`mcp` v2** (`MCPServer`), which speaks
   2026-07-28 *and* every earlier revision; the standalone **`fastmcp` v4** also targets it.
   Verify both from PyPI / their docs rather than from memory — this brief may be wrong
   about details.

## 4. Known facts, numbered (so answers can reference them)

- F1. 32 API modules under `src/axis_cam/api/`, each `@register`ed with `name` and `api_id`
  (`None` = never gated, else gated on the discovery document) and a `read()`.
- F2. `collect_report(device, full=...)` → nested `sections` keyed by module name, with
  per-module `errors` and `skipped`. `run_audit(device)` → `AuditReport` of `Finding`s
  (`id`, `title`, `status` ∈ pass/fail/unknown/n-a/info, `severity`, `evidence`,
  `recommendation`, `reference`).
- F3. `create_backup(...)` writes a directory with `manifest.json` (SHA-256 per file, honest
  "not included by design" / "not implemented" lists); `verify_backup(dir)` → list of
  problems. `RestorePlan` diffs a backup against the device; apply is one
  `param.cgi?action=update` per changed parameter with read-back.
- F4. Writes that exist today: VAPIX accounts (`UsersAPI`), ONVIF users (`OnvifUsersAPI`),
  params restore. Planned: `security harden` (see the hardening plan), which turns audit
  remedies into parameter writes.
- F5. `cli/context.py::DeviceContext` is the seam through which the CLI resolves a config
  device to an `AxisDevice` (used by all 32 CLI tests as a patch point).
  `cli/fleet.py::run_fleet` is the bounded fan-out.
- F6. Tests: 875, `respx` for wire-level HTTP tests, verbatim device bodies as fixtures, a
  docs-match-code test that fails when docs name a method that does not exist.
- F7. 36 CLI commands across 8 groups; the server does not have to mirror them 1:1.
- F8. Packaging: single distribution `axis-cam` with one script `axiscam`. No `mcp` or
  `fastmcp` dependency exists yet.

## 5. Explicitly out of scope

- Any new device-protocol work (new VAPIX/ONVIF wrappers).
- Remote/multi-user deployment, OAuth/authorization servers, the MCP registry listing.
- A web UI. Video/stream handling. Changing the CLI.
- Hardening the devices themselves (that is the separate hardening plan).

## 6. The questions — answer each with the countable thing it asks for

- Q1. **SDK choice.** Official `mcp` v2 (`MCPServer`) or standalone `fastmcp` v4 — pick one
  and give the three decisive reasons for *this* codebase (typing/pyright story, testing
  story with an in-memory client, 2026-07-28 support, dependency weight, longevity).
- Q2. **Tool surface.** Propose the complete initial tool list: name, one-line purpose,
  read-only vs write, and for each write the two-phase shape. Target ≤ 15 tools and
  justify the count; say which registry modules are exposed as *tools* versus as MCP
  *resources* (URI-addressable reads) and why. Explicitly address `params` (I2) and the
  per-device variability (I1): generic `read_resource(device, module)` versus one tool per
  module.
- Q3. **Write confirmation without a console (I4).** Give the mechanism: e.g. plan → opaque
  server-minted plan handle (the 2026-07-28 "explicit handle as an ordinary tool argument"
  pattern) → apply(handle) with a TTL and a device-serial binding; or MRTR
  `input_required`; or host-side approval only. State what happens on a host that does not
  support MRTR, and how the test proves "no write without a prior plan".
- Q4. **Error model.** Map the typed exceptions to MCP: tool error result (`isError`) vs
  JSON-RPC error vs a structured `status` field; where `unknown` (could-not-read) lives so
  it is never mistaken for a value.
- Q5. **Structured output.** Should every tool declare an `outputSchema` derived from the
  pydantic models? Give the rule and one example for a reader whose model varies by
  firmware generation.
- Q6. **Long operations (I6).** Backup of five devices, crash-report download: synchronous
  with a timeout, progress notifications, or the tasks extension? Pick and bound it.
- Q7. **Package layout and TDD order.** Where the server lives (`axis_cam/mcp/`? separate
  distribution? optional extra `axis-cam[mcp]` with a second script `axiscam-mcp`?), the
  module split, and the **ordered list of the first ten failing tests** to write, each with
  the production change it forces. Name the test double for devices (reuse
  `DeviceContext.open` patching? a fake `AxisDevice` built from the registry? `respx`?).
- Q8. **Secrets boundary tests.** List the tests that prove credentials cannot leak:
  through results, through errors, through logging to stderr, through resource URIs.
- Q9. **What should NOT be exposed over MCP at all**, with reasons (e.g. factory default,
  removing the last administrator, crash-report download that contains passwords).
- Q10. **What this brief gets wrong.** Name the assumptions above you checked and found
  false or contradictory, and the question we should have asked.

## 7. Output format (hard cap 1,800 words)

```
## Verified against code  (bullet per claim checked: file:line, confirmed/refuted)
## Q1 … Q10  (one section each, the countable answer first, reasoning after)
## Where the other reviewers will be wrong  (your prediction, 3 bullets)
## What the brief gets wrong
```
