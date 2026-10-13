# axiscam — admin features and modularity: review and phased plan

- **Date:** 2026-10-12
- **Status:** Phases 0–4 complete; Phase 5 not started (see [Phase status](#phase-status))
- **Baseline measured:** 452 tests pass · 53% coverage (`uv run pytest --cov=src/axis_cam`) · ruff clean · pyright clean
- **Repo state at review:** local `main` was 5 ahead / 5 behind `origin/main` (diverged). Phase 0 work is on branch `phase-0-security-fixes`, cut from local `main`. Reconciling `main` with `origin/main` is a separate owner decision — nothing here pushes.

## TL;DR

The library is a clean, consistent, read-only VAPIX client with good Pydantic models and a sensible one-module-per-API decomposition. Three things block the requested goals:

1. Two silent transport-security bugs in the CLI path (TLS verification never enabled; scheme inferred from port).
2. A coverage gate that measures nothing.
3. A four-file edit tax per API module that makes "full backup/restore" and generic admin commands impractical without a registry-style refactor.

Two requested goals are already met (server report with image by default; debug archive = crash report). One needs an expectation reset: **AXIS OS has no native full backup/restore API.** "Full" has to be composed per module, and some state is unrestorable through VAPIX by design.

## Goals vs. current state

| Goal | State | Evidence |
|---|---|---|
| Server report, image by default | Done | `download report` defaults to `zip_with_image` (`src/axis_cam/cli.py`) |
| Crash report | Done, misnamed | `download debug` → `/axis-cgi/debug/debug.tgz`. Axis's [server/crash report privacy statement](https://www.axis.com/support/technical-notes/server-and-crash-report-privacy-statement) describes the crash report as the server report plus debug data that "can include user IDs, passwords, video images, network traffic". One DevTools capture of the web UI's "Download the crash report" confirms the URL; then alias `download crash-report` and warn on save. |
| Logs: system / access / audit | Exists, wrong mechanism | All three download the entire `tar_all` server report and grep filenames (`LOG_FILE_PATTERNS`, `src/axis_cam/api/logs.py`). Axis has a dedicated [`auditlog.cgi?tail=N`](https://developer.axis.com/vapix/network-video/audit-log/) and `systemlog.cgi` ([system settings](https://developer.axis.com/vapix/network-video/system-settings/)). `search_logs` and `get_log_summary` re-download the tar. |
| Users: Accounts | Missing | `pwdgrp.cgi` — verified, see [Feature gaps](#feature-gaps--verified-endpoints-and-constraints) |
| Users: ONVIF | Missing | Separate user database; ONVIF SOAP, not VAPIX |
| Backup (full) | Missing | Only `params --export` (param tree, ambiguous shape) |
| Restore (full) | Missing | No native endpoint exists |
| Modular / ResourceModule | Missing | See [Architecture](#architecture-and-the-resourcemodule-idea) |

## Findings by severity

Legend: 🔴 bug · 🟡 improvement · 🔵 style/hygiene

### 🔴 Bugs

1. **TLS verification is always off from the CLI, regardless of config.** `resolve_device_config` (`src/axis_cam/cli.py`) returns `(host, user, pw, port, type)` and drops `DeviceConfig.ssl_verify` and the app `timeout`. Every command then builds `device_class(host, user, pw, port, use_digest_auth=digest)` → `ssl_verify=False`. The README documents `ssl_verify:` per device; it is a no-op. A user who sets `ssl_verify: true` believes they are protected against MITM and is not.
2. **Transport scheme is inferred from the port.** `src/axis_cam/devices/base.py`: `use_https = port == 443`. A device on 8443 is contacted over plaintext HTTP. Combined with the library default `use_digest_auth=False`, that is Basic-auth credentials in cleartext. Fix: explicit `https: bool = True` in `DeviceConfig` and constructors; refuse Basic over HTTP unless explicitly allowed.
3. **The coverage gate is theatre.** `.pre-commit-config.yaml` ran `uv run pytest --cov-fail-under=90` without `--cov=`; verified: 452 passed, exit 0, no coverage measured. Real coverage 53%; 22 of 27 API modules at 17–29%, `cli.py` at 12%. pyproject said 80, hook said 90. Fix: measure coverage in the hook, one threshold in pyproject set at the measured baseline and ratcheted upward per phase.
4. **Log sorting crashes on mixed timestamp awareness.** `src/axis_cam/api/logs.py`: ISO timestamps with offsets (Axis emits `2025-07-22T15:38:25.307+00:00`) parse tz-aware; unparsed/continuation lines get naive `datetime.now()`. `get_logs` then sorts → `TypeError: can't compare offset-naive and offset-aware datetimes`. Latent (not reproduced on a device) but any multi-line syslog message triggers it. `now()` on unparsed lines also floats them to the top of a newest-first sort.
5. **83 `except Exception` sites across 32 files swallow auth and connection errors.** Example: `SshAPI.get_config` on a 403 returns `SshConfig(enabled=False)`. For a security tool, "could not read" rendering as "disabled" is a false negative. Fix: catch `AxisDeviceError`/`AxisApiNotSupportedError` narrowly in API/device modules; let `AxisAuthenticationError`/`AxisConnectionError` propagate; add one top-level `AxisError` handler in the CLI. Four of the 62 non-CLI sites wrap non-HTTP code (enum parsing in `cert.py`/`firewall.py`, `model_validate` in `lldp.py`, tar member decode in `logs.py`) and need their own narrow exception types.

### 🟡 Improvements

6. `--password` on the command line lands in shell history and `ps`. Add `AXIS_PASSWORD` env for ad-hoc `--host` use and a hidden interactive prompt fallback.
7. `.env` is read by `config.load_env_file` but was not in `.gitignore`.
8. `ParamAPI.export()` falls back to a different dict shape on any exception; a restore cannot tell which shape a file holds.
9. `--port 443` is a sentinel (`port if port != 443 else config.port`); an explicit 443 cannot override a config port.
10. Auth defaults disagree: CLI `digest=True`, library `use_digest_auth=False`, README says "Digest (default)".
11. README claims "Efficient parallel communication with multiple devices"; there is no multi-device fan-out anywhere.
12. Typer's pretty exceptions show local variables by default, which include `passwd`; set `pretty_exceptions_show_locals=False`.

### 🔵 Style / hygiene

13. `AxisDevice` carries 27 one-line pass-through wrappers (`get_ssh_config()` → `self.ssh.get_config()`). `BaseAPI(ABC)` has no abstract methods (`# noqa: B024`). `LogsAPI.__init__(client: Any)`. `.gitignore` had its agent/IDE block duplicated. `specs/` is ignored while `src/specs/` is a tracked near-duplicate. Empty `src/docs/`. Terraform hooks in a pure-Python repo. `mypy --strict` configured, pyright is what runs. The `device report --full` comment says "Full configuration export" but it is a hand-picked summary.

## Architecture and the ResourceModule idea

Current shape: `BaseAPI` is a thin `_get/_post/_get_raw` wrapper; 27 `XxxAPI` classes each expose `get_config() -> PydanticModel`; `AxisDevice.__init__` instantiates all 27 by hand and mirrors each with a wrapper; `cli.py` (2,566 lines) repeats the "resolve → build device → `async with` → call → Rich table" pipeline ~30 times. Adding a module touches `api/<m>.py`, `api/__init__.py`, `devices/base.py` (import, attribute, wrapper), `models.py`, `cli.py`, docs. That tax is why `device report` is a 300-line hand-written try/except chain, and why backup/restore cannot be written generically today.

A `ResourceModule` Protocol alone buys nothing. The win comes from three things together, each kept thin:

```mermaid
flowchart LR
    subgraph REG["ResourceModule registry (one decorator per module)"]
        A["ssh · firewall · ntp · …<br/>read() → model"]
        B["param · users · …<br/>read() + export() + plan_restore()/apply()"]
    end
    DEV["AxisDevice<br/>builds modules from registry,<br/>gated by /config/discover/apis.json"]
    subgraph SVC["Generic services — written once"]
        R["report"]
        K["backup → manifest + module snapshots"]
        S["restore → diff → plan → confirm → apply"]
        U["security audit"]
    end
    CLI["cli/ package<br/>one DeviceContext (ssl_verify, timeout, scheme)<br/>one module per Typer group"]
    REG --> DEV --> SVC --> CLI
```

- **Protocol:** `name`, `api_id` (API-discovery id for gating), `model`, `async read()`. Optional capability protocols `Exportable` / `Restorable`, structural, so a module opts in by implementing the methods. Not an ABC hierarchy.
- **Registry:** a decorator registers the class; `AxisDevice` builds `self.modules` from it, filtered by discovered APIs. Deletes the 27 wrappers (breaking at 0.1.0 Alpha; acceptable) and the four-file edit.
- **CLI pipeline:** a single `DeviceContext` that resolves config *including* `ssl_verify`/`timeout`/scheme, and a `cli/` package split by group. Keep Rich rendering per module; do not build a generic renderer framework.

Phase 0 introduces `ResolvedDevice` in `cli.py` as the seed of `DeviceContext`.

## Feature gaps — verified endpoints and constraints

### Accounts (VAPIX users) — [`/axis-cgi/pwdgrp.cgi`](https://developer.axis.com/vapix/network-video/system-settings/)

- `action=get|add|update|remove`; `user`, `pwd`, `grp=users`, `comment`, `strict_pwd=1`.
- Roles via `sgrp`: `viewer`, `viewer:ptz`, `operator:viewer`, `operator:viewer:ptz`, `admin:operator:viewer`, `admin:operator:viewer:ptz`.
- Rotation is `action=update&user=X&pwd=Y`.
- `action=get` returns `text/plain` lines `admin="root,joe"`, `operator="…"`, `viewer="…"`, `ptz="…"`, `digusers="…"`.
- **Gotcha 1:** errors return **HTTP 200** with body `Error: consult the system log file.` — `_check_response` will never catch them; body parsing is required.
- **Gotcha 2:** the CGI accepts POST; send `pwd` as form data, never in a GET query string (device access logs, proxies).
- Design rules: self-lockout guard (refuse to remove or de-admin the authenticated account); verify with `action=get` after every write; read the passphrase policy from the [User Management API v2](https://www.developer.axis.com/vapix/device-configuration/user-management-v2-api/) before generating passwords.

### ONVIF accounts

A separate user database on Axis (Axis FAQ and multiple VMS vendor KBs agree). No VAPIX CGI found. Path: ONVIF Device Management SOAP (`GetUsers` / `CreateUsers` / `SetUser` / `DeleteUsers` on `/onvif/device_service`, WS-UsernameToken auth). Four operations is small enough to hand-roll with httpx + stdlib XML rather than depend on `onvif-zeep`. **Needs device verification** of Axis's auth behaviour on that endpoint before design.

### Backup / restore

VAPIX system settings lists `factorydefault.cgi`, `hardfactorydefault.cgi`, `restart.cgi`, `firmwareupgrade.cgi` — no backup/restore. Axis treats backup as per-API (stream profiles docs: "a backed up configuration can be re-applied"); whole-device backup is an AXIS Device Manager feature done tool-side.

- **Backup** = registry-driven snapshot: `backup-<host>-<ts>/manifest.json` + one JSON per `Exportable` module + param tree + optional server report. The manifest must list what is **not** included: passwords, private keys, ACAP binaries/licences, recordings.
- **Restore** = per-module `plan_restore(snapshot) → list[Change]` (a diff), printed, confirmed, then `apply`. Dry-run by default, `--apply` explicit. Order: network last (you may cut yourself off); users with the lockout guard. Each module's write path (`param.cgi?action=update`, DCA `PATCH`) must be verified on a device.

### Logs

Audit → `auditlog.cgi?tail=N`; system → `systemlog.cgi`; keep `tar_all` for access/all. Normalise timestamps to aware UTC.

## Other admin tasks worth adding

- **`security audit`** against the [AXIS OS Hardening Guide](https://help.axis.com/en-us/axis-os-hardening-guide), mostly composition of existing readers: HTTP disabled, TLS floor and weak ciphers (`CryptoPolicyAPI`), Basic auth off, SSH off, firewall on, SNMP v1/v2c off, lone `root` admin / unknown admins (an IoC in Axis's forensics guide), ONVIF accounts and discovery state, remote syslog set, NTP synced, certificate self-signed or expiring, firmware on an LTS track.
- **`system restart` / `factory-default [--hard]` / `firmware status|upgrade`** — confirm-gated, same write-safety pattern as users.
- Passphrase policy get/set; persistent logging on/off/clear (half-exists); remote syslog.
- Network trace — `GET /axis-cgi/debug/debug.tgz?cmd=pcapdump&duration=<s>` returns a `.pcap` (developer troubleshooting page); `download network-trace --duration 30` is a small addition on the crash-report path with the same `0600` writer.
- Fleet fan-out (`--all` / `--group`) — makes the README claim true.

## Phases

| Phase | Scope | Why here |
|---|---|---|
| 0 | 🔴1–5, 🟡7, 🟡12. Each its own commit with a test. | Silent security bugs first; none need the refactor |
| 1 | Protocol + registry + capability gating; `cli/` package with `DeviceContext`; delete wrappers; `report` becomes registry-driven | Every later feature otherwise pays the four-file tax |
| 2 | `UsersAPI` on `pwdgrp.cgi` + `accounts list\|add\|set-password\|remove` | Best-verified write surface; establishes the write-safety pattern (POST form, 200-body errors, lockout guard, confirm/dry-run) that restore reuses |
| 3 | Logs via `auditlog.cgi`/`systemlog.cgi`; `download crash-report` alias + warning + `0600` | Small, high value |
| 4 | Backup with honest manifest | Pure reads over the registry |
| 5 | Restore, module by module, verified on a device | Most unknowns; benefits from everything above |
| 6 | ONVIF accounts after a device check of the SOAP path | Unverified auth behaviour |
| 7 | `security audit` + fleet fan-out | Composition |

Rationale for the order: the two transport bugs are the only findings that hurt someone today, and writes change the project's safety posture — the confirm/dry-run pattern should exist once, in Phase 2, before restore multiplies it across 27 modules.

## Phase status

### Phase 0 — complete on branch `phase-0-security-fixes` (2026-10-12)

| Item | Commit | Status |
|---|---|---|
| Plan document | `95bf4de` | ✅ |
| 🟡7 `.gitignore`: `.env`, dedupe | `9b7ed3e` | ✅ |
| 🔴3 real coverage gate (hook measures coverage; single threshold at baseline) | `b5a0903` | ✅ |
| 🔴2 explicit `https`; refuse Basic over plain HTTP | `3a887f8` | ✅ |
| 🔴1 `ResolvedDevice` plumbs `ssl_verify`/`timeout`/`https` through the CLI; 🟡9 `--port` is a real override | `93fb91c` | ✅ |
| 🔴4 tz-aware log timestamps; continuation lines inherit the previous timestamp | `2e2b2ac` | ✅ |
| 🔴5 narrow exception handling (62 sites); CLI `run_async`/`main` error path; 🟡12 hide locals | `ae540bf` | ✅ |

After Phase 0: 485 tests pass · 54.6% coverage · ruff clean · pyright 0 errors (9 pre-existing warnings, unchanged). Each fix carries a regression test that was shown to fail against the previous source.

Behaviour changes a library user will notice: a non-443 port no longer implies HTTP (`https=False` is explicit); Basic auth over plain HTTP raises `AxisConfigError` unless `allow_insecure_basic=True`; `get_config()`-style methods raise `AxisAuthenticationError`/`AxisConnectionError` instead of returning defaults.

### Phase 1 — complete on branch `phase-0-security-fixes` (2026-10-13)

| Step | Commit | Status |
|---|---|---|
| 1.1 registry, `ResourceModule`, `AxisDevice.modules` / `resources` / `available_resources()` | `f3737b4` | ✅ 21 tests, incl. gating against all four `src/specs` captures |
| 1.2 delete the 29 pass-through wrappers; 34 CLI + 4 test + 1 doc call sites rewritten | `2f23115` | ✅ `devices/base.py` 603 → 334 lines |
| 1.3 `axis_cam/report.py`; `report` command registry-driven; JSON via `typer.echo` | `fd4226a` | ✅ fake-module test proves report code lists no modules |
| 1.4 `cli/` package; `DeviceContext`; `cli.py` deleted | `df52dfc` | ✅ 32 CLI tests: every `--help`, commands end to end through `DeviceContext.open` |
| 1.5 docs, coverage ratchet 50 → 58, `emit_json()` across all `--json` paths, this table | `fb9a1b7` | ✅ |

After Phase 1: 553 tests pass (from 485) · 60% coverage (from 54.6) · ruff clean · pyright 0 errors (9 pre-existing warnings, unchanged). Each step was committed through the pre-commit gate.

Found and fixed along the way: `console.print(json.dumps(...))` soft-wraps at Rich's console width and corrupts piped JSON (reproduced: a 300-character value split mid-string). Every `--json` path now goes through `emit_json()` (`typer.echo`), with a regression test.

Behaviour changes a library user will notice: `device.get_ssh_config()` and the other 28 forwarders are gone (`device.ssh.get_config()`); `LogsAPI(client, device_name=None)` defaults the name to `client.host`; `report` output is nested under `sections` and keyed by module name.

Sequence, one commit each, ordered so every step can end on its own:

| Step | Scope | Definition of done (countable) |
|---|---|---|
| 1.1 | `api/registry.py`: `ResourceModule` Protocol (`name`, `api_id`, `read()`), `@register` decorator, `build_modules()`. Every module gains `name`/`api_id`; resources gain `read()`. `AxisDevice` builds its modules from the registry and exposes `modules`, `resources`, `available_resources()` (gated by API discovery). Additive — wrappers still exist. | `tests/test_registry.py`: every `BaseAPI` subclass in `axis_cam.api` is registered (27), names unique, `AxisDevice` annotations match the registry, gating filters by discovered ids and does not filter when discovery is empty |
| 1.2 | Delete the pass-through wrappers from `AxisDevice`; rewrite CLI and test call sites to `dev.<module>.<method>()` with asserted counts | `devices/base.py` has 0 `self.x = XAPI(...)` lines and 0 `get_*_config`-style wrappers; the device-specific methods on subclasses are untouched |
| 1.3 | `axis_cam/report.py`: registry-driven collection (`collect_report`), per-module `AxisDeviceError`/`AxisApiNotSupportedError` → `errors`, auth/connection errors propagate; `report` command uses it | A test registers a fake resource and sees it in a `--full` report without editing report code; the 19 `except Exception` sites in the old report are gone |
| 1.4 | `cli/` package: `app.py` (Typer apps, console, `run_async`), `context.py` (`DeviceContext`, `resolve_device_config`), `options.py`, one module per command group; `cli.py` deleted | `axiscam --help` and every group `--help` pass under `CliRunner`; `axis_cam.cli:main` entry point unchanged |
| 1.5 | Docs (`README`, `docs/architecture.md`, `docs/api-modules.md`, `docs/device-classes.md`, `docs/cli-reference.md`), this status table, coverage ratchet | `fail_under` raised to the new measured floor (≥ 54); ruff clean; pyright 0 errors |

Decisions taken for Phase 1:

- **Typed attribute declarations stay.** `AxisDevice` keeps one annotation per module (`ssh: SshAPI`) so `dev.ssh.get_config()` remains statically typed; the registry does the instantiation. Adding a module is therefore `api/<m>.py` + its import in `api/__init__.py` + one annotation line, and a test fails if the annotations and the registry drift. Full dynamism (`setattr` only) would have cost every caller its type information.
- **A resource is a module with `read() -> BaseModel`.** `params`, `logs` and `serverreport` are registered modules but not resources in Phase 1: the param tree is too large for a report (Phase 4 gives `ParamAPI` an `export()`), and logs / server reports are downloads, not configuration.
- **`api_id` is `None` for CGI-capable modules** (`device_info`, `time`, `params`, `logs`, `serverreport`) because they work on devices whose discovery omits the REST id (`c1410` lists neither `time` nor `param`). Gating applies only to REST-only modules and only when discovery returned a non-empty list; the four captures in `src/specs/` are the fixtures.
- **Report sections are keyed by module name and hold `model_dump(mode="json")`.** `info` → `device_info`, `security` → `firewall`, `certificates` → `cert`; the default report is the summary set (`device_info`, `time`, `network`, `lldp`, `stream`, `firewall`, `ntp`), `--full` is every available resource. Output-shape change, acceptable at 0.1.0.
- **Device options stay per command.** Typer's shared-callback pattern would move `--device` before the subcommand (`axiscam --device x info`), a UX break for no gain. `ResolvedDevice` becomes `DeviceContext` with Digest/Basic folded in so `open()` takes no arguments.
- **`Exportable` / `Restorable` are not defined yet.** They get a Protocol when Phase 4/5 has a second implementer; an abstraction with one implementation is a fake nobody wants.

### Phase 2 — complete on branch `phase-0-security-fixes` (2026-10-13)

| Step | Commit | Status |
|---|---|---|
| 2.1 `UsersAPI` on `pwdgrp.cgi`; models, exceptions, `_get_text`/`_post_form`; registry 28 | `d566f28` | ✅ 51 tests incl. respx wire test (password in body, empty query string) |
| 2.2 `cli/confirm.py` write-safety helper; `accounts list\|add\|set-password\|set-role\|remove` | `1109fbf` | ✅ 25 CLI tests: dry-run writes nothing and never prompts; declining exits 1 with no write; `--yes` writes; refusals are one line |
| 2.3 docs, 66 phantom methods removed + `tests/test_docs.py`, coverage ratchet 58 → 61, this table | `10f30de` | ✅ |

After Phase 2: 631 tests pass (from 553) · 63.2% coverage (from 60.0) · ruff clean · pyright 0 errors (9 pre-existing warnings, unchanged).

Found and fixed along the way: `docs/api-modules.md` documented **66 methods that do not exist** across 22 classes (`SshAPI.enable()`, `FirewallAPI.add_rule()`, `CertAPI.install_certificate()`, …) — aspirational write APIs written as if shipped. Removed by cross-checking every documented method against `inspect.getmembers` of the real class, and the check is now `tests/test_docs.py` (also asserts every registered module has a section in `api-modules.md` and a row in `device-classes.md`).

Contract verified against the VAPIX System settings page on 2026-10-13 (fetched, not recalled): `action=add|update|remove|get`; `user` 1–14 chars `[A-Za-z0-9]`; `pwd` 1–64 chars, ASCII `0x20–0x7E` under `strict_pwd=1`; `grp=users` (`root` only for the initial account); `sgrp` one of the six role strings; success bodies `Created|Modified|Removed account <user>.`; error bodies at **HTTP 200**: `Error: consult the system log file.`, `Error: action operation type.`, `Error: account user name.`, `Error: malformed action operation, <action>.`, `Error: invalid password.`; initial-admin errors are 401. The doc itself says not to put credentials in the URL. Discovery id `user-management` belongs to the apidiscovery CGI, not `/config/discover/apis.json`, so `api_id = None` (never gated), consistent with the other CGI modules.

| Step | Scope | Definition of done (countable) |
|---|---|---|
| 2.1 | `models.UserRole`/`UserAccount`/`UserAccounts`; `api/users.py` `UsersAPI` (`list`, `add`, `set_password`, `set_role`, `remove`, `read`), registered as `users`; `BaseAPI._get_text`/`_post_form`; `AxisUserError`, `AxisLockoutError` | Parses the doc's `action=get` example to 4 accounts with the right roles; every write sends form data (respx proves the password is in the body and absent from the URL); every `Error:` body raises `AxisUserError`; add/set_role/remove re-read and verify; lockout guard refuses self-removal, self-de-admin and removing the last admin unless `allow_lockout=True`; registry count 28 |
| 2.2 | `cli/confirm.py` write-safety helper (`plan → --dry-run / --yes / prompt`); `accounts list\|add\|set-password\|set-role\|remove`; new passwords only via hidden prompt or `--password-stdin` | `--dry-run` makes no write call and exits 0; declining makes no write call and exits 1; `--yes` writes; lockout errors are one line; 9 groups in `--help` |
| 2.3 | Docs (cli-reference, README, api-modules, device-classes), plan status, coverage ratchet | `fail_under` at the new measured floor |

Write-safety pattern (restore reuses it in Phase 5): read current state → compute a human-readable plan → `--dry-run` prints it and exits 0 → otherwise confirm (`--yes` skips) → apply → re-read and verify → print the verified result. Secrets never appear in argv.

### Phase 3 — complete on branch `phase-0-security-fixes` (2026-10-13)

Contracts verified from the VAPIX pages on 2026-10-13: `GET /axis-cgi/systemlog.cgi[?text=<alnum>]` (filter from AXIS OS 11.11.45), `GET /axis-cgi/accesslog.cgi`, `GET /axis-cgi/auditlog.cgi[?tail=<n>]` (discovery id `audit-log`, AXIS OS 12.7+, admin, `text/plain`; 400/401/500 on error). The web-interface help (LTS 2026) describes *Download the crash report* as "information that is in the server report as well as detailed debug information … might contain sensitive information such as network traces … can take several minutes"; the developer troubleshooting page uses `/axis-cgi/debug/debug.tgz?cmd=pcapdump&duration=N` for the network trace, so `debug.tgz` is the debug/crash archive. Byte-for-byte equality with the web UI's download still needs one DevTools capture on a device; the naming follows the web UI regardless.

| Step | Commit | Status |
|---|---|---|
| 3.1 dedicated log CGIs with tarball fallback; `LogReport.source`; aware `retrieved_at` | `5533830` | ✅ 9 endpoint tests + 5 fallback tests |
| 3.2 `download crash-report` (+ hidden `debug` alias), privacy notice, 300 s; `files.write_private` for every diagnostic incl. `report -o`, `params --export -o`, `init` | `3317711` | ✅ 12 tests incl. `0600` on POSIX and tightening of a pre-existing `0644` file |
| 3.3 docs, coverage ratchet 61 → 62, this table | `a82c141` | ✅ |

After Phase 3: 682 tests pass (from 661) · 64.6% coverage (from 63.2) · ruff clean · pyright 0 errors (9 pre-existing warnings, unchanged).

Original step table:

| Step | Scope | Definition of done (countable) |
|---|---|---|
| 3.1 | `LogsAPI` reads system/access/audit from their dedicated CGIs (`auditlog.cgi?tail=N` for the requested count) and falls back to the `tar_all` server report only when the CGI is absent; `LogReport.source` says which. `stream_logs`/`search_logs`/`get_log_summary` follow | Tests: each type hits its CGI with the right params; 404 → tarball fallback with `source` saying so; auth errors propagate; `ALL` still uses the tarball |
| 3.2 | `download crash-report` (primary) with `download debug` kept as an alias; privacy notice before download; every downloaded diagnostic written `0600` via one helper (`axis_cam.files.write_private`), also used by `save_report`/`save_debug_archive`; crash-report timeout default 300 s | Tests: file mode is `0600` on POSIX; notice printed; alias and primary share one implementation |
| 3.3 | Docs, plan status, coverage ratchet | `fail_under` at the new measured floor |

### Phase 4 — complete on branch `phase-0-security-fixes` (2026-10-13)

**Blocker found first.** `ParamAPI` reads `param.cgi` through `client.get_json()`, but the VAPIX Parameter management page (fetched 2026-10-13) documents `action=list` as `Content-Type: text/plain` with `<parameter>=<value>` lines (`responseformat=rfc` "should always be used"; errors are HTTP 200 `# Error: <description>`). `response.json()` therefore raises on every real device, the narrow `except` turns it into `None`/`[]`/`{}`, and `params`, `location`, `get_friendly_name()` and `params --export` have been silently empty — the "cannot read ≠ empty" false negative from Phase 0 in another coat. All 27 tests in `tests/test_api_param.py` feed JSON dicts, i.e. they lock the wrong contract in. The REST `$export` endpoint `export()` tries first is documented nowhere I can find (discovery lists `/config/rest/param/v2beta` but no `$export`), so it is dropped rather than kept on faith.

| Step | Commit | Status |
|---|---|---|
| 4.0 `ParamAPI` on the documented text contract; one `export()` shape; `$export` removed | `30edca9` | ✅ 28 tests incl. the doc's example through the real client |
| 4.1 `axis_cam/backup.py`: `create_backup`, `load_manifest`, `verify_backup`; honest manifest | `4dbd060` | ✅ 18 tests incl. fake-module independence, tamper detection, `0700`/`0600` |
| 4.2 `backup create\|show\|verify` | `6c45863` | ✅ 10 groups in `--help` |
| 4.3 docs, coverage ratchet 62 → 64, this table | `e1a8a72` | ✅ |

After Phase 4: 712 tests pass (from 682) · 65.8% coverage (from 64.6) · ruff clean · pyright 0 errors (9 pre-existing warnings, unchanged).

Original step table:

| Step | Scope | Definition of done (countable) |
|---|---|---|
| 4.0 | `ParamAPI` parses the documented text format (one `_list()` helper: `action=list[&group=…]&responseformat=rfc`, `# Error` → `AxisDeviceError`); `export()` returns one shape, a flat `dict[str, str]` of full names → values (what `param.cgi?action=update` consumes in Phase 5); `get_all()` groups the same parse. `$export` removed. | respx wire test parses the doc's example body; 27 tests rewritten to text fixtures; `test_devices` friendly-name/location fixtures to text; `params`/`location` CLI paths covered |
| 4.1 | `axis_cam/backup.py`: `create_backup()` writes `backup-<host>-<UTC ts>/` with `manifest.json`, one `<module>.json` per available resource (via `collect_report(full=True)`), `params.json`, optional `server-report.zip`; dir `0700`, files `0600`; `load_manifest()`, `verify_backup()` (sha256) | Manifest lists every file with sha256; `not_included.by_design` and `not_included.not_implemented` are explicit lists; a fake registered module appears in a backup with no change to backup code; `verify_backup` detects a tampered file |
| 4.2 | `axiscam backup create [-o DIR] [--with-server-report]`, `backup show DIR`, `backup verify DIR` | 10th group in `--help`; `show` renders the manifest incl. what is not included; `verify` exits 1 on mismatch |
| 4.3 | Docs, plan status, coverage ratchet | `fail_under` at the new measured floor |

No `Exportable` protocol: backup is every resource's `read()` plus the one module (`params`) whose payload is not a model; one special case is handled explicitly, not abstracted (Phase 1 decision stands).

The manifest's honesty list (what a VAPIX backup cannot contain, by design): account passwords and hashes; private keys of device certificates; ACAP application binaries and licence keys; recordings and edge-storage content; the device's own TLS/SSH host keys. Not implemented yet (readable in principle): ONVIF users; installed ACAP list; stream profiles beyond what `stream` reads; view areas / PTZ presets; overlays.

## Decisions and open questions

- **Decided:** secure by default — `https` defaults to `True`; plain HTTP is an explicit `https: false` in config. Ad-hoc `--host` use is HTTPS only; a `--http` option was *not* added in Phase 1 (it would widen every command signature for an ad-hoc-only case) — add it in Phase 2 alongside the write-safety flags if a plain-HTTP device actually needs ad-hoc access.
- **Decided:** coverage threshold ratchets from the measured baseline rather than being set at an aspirational number nobody can pass (that path leads to `--no-verify`).
- **Open (filed 2026-10-13):** `VapixClient` itself still defaults to `use_https=False, port=80, use_digest_auth=False`; Phase 0 made `AxisDevice` secure by default but anyone constructing the client directly gets plain HTTP + Basic. Flip the client defaults to match (`use_https=True, port=443`) and refuse Basic-over-HTTP at the client level too; `tests/test_client.py` constructs the client bare in many places and needs the same sweep.
- **Open:** whether to flip the library default `ssl_verify=False` → `True`. It will break self-signed setups; needs an `ssl_ca_bundle` option first. Not changed in Phase 1; revisit with Phase 2's `DeviceContext` additions.
- **Fixed (2026-10-13):** every `--json` output and `params --export` to stdout went through `console.print`, which soft-wraps at Rich's console width and interprets `[...]` as markup, corrupting piped JSON (reproduced: a 300-character value split mid-string under an 80-column console). All 14 sites now use `emit_json()` / `typer.echo`; `tests/test_cli_commands.py::test_json_output_is_not_wrapped_at_console_width` guards it.
- **Open (narrowed 2026-10-13):** `download crash-report` fetches `/axis-cgi/debug/debug.tgz`, which the developer troubleshooting page identifies as the debug archive (`?cmd=pcapdump` variant is the network trace) and the web-interface help describes as "server report plus detailed debug information". Whether the web UI's button adds query parameters is still unverified — one DevTools capture on a device settles it; the command name and notice do not depend on the answer.
- **Open:** local `main` vs `origin/main` divergence (5/5).
