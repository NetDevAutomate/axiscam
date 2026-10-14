# Hardening pass — plan from the security-audit findings

Date: 2026-10-14. Status: **plan only — nothing in this document has been applied.**
Source of findings: `axiscam security audit --all --json`, run 2026-10-14 ~12:05 UTC against
the five configured devices on `main` at `6cbaa22`. Checks and remedies are the audit's own,
which quote the AXIS OS Hardening Guide (July 2026 edition); see
`2026-10-12-admin-and-modularity-review.md` § Phase 7 for how each check maps to the guide.

## Who this is for, and what "done" means

For Andy, on his own five devices. "Done" for the whole pass is: every check the devices
*can* satisfy reads `pass` on every device, every check deliberately left failing has a
written reason in this file, **and every consumer that worked before the pass still works
after it**. The second half is the hard part — the audit tells us what is on, not who
depends on it.

## Ground truth: what fails today

| Check | Severity | intercom | front_of_house | back_of_house | nvr (S3008) | mini_speaker |
|---|---|---|---|---|---|---|
| `https.only` | high | fail | fail | fail | unknown | fail |
| `snmp.legacy_versions` | high | fail | pass | pass | pass | fail |
| `access.ssh` | medium | fail | fail | fail | unknown | fail |
| `auth.brute_force_delay` | medium | fail | fail | **pass** | unknown | fail |
| `discovery.bonjour` | medium | fail | fail | fail | unknown | fail |
| `discovery.upnp` | medium | fail | fail | fail | unknown | fail |
| `discovery.ws_discovery` | medium | fail | fail | fail | unknown | fail |
| `logging.remote_syslog` | medium | fail | fail | fail | unknown | pass |
| `network.firewall` | medium | fail | fail | fail | fail | fail |
| `tls.ciphers` | medium | pass | pass | pass | unknown | fail |
| `access.web_interface` | low | fail | fail | fail | unknown | fail |
| `discovery.zeroconf` | low | fail | fail | fail | unknown | fail |
| `info.server_tokens` | low | fail | fail | fail | unknown | fail |
| `logging.access_log` | low | fail | fail | fail | unknown | fail |
| `tls.crypto_policy` | low | fail | fail | fail | unknown | unknown |

The S3008 has no `param.cgi`, so 25 of its checks are `unknown` — **not** a clean bill of
health, and not something this pass can fix through the parameter API. It gets its own
section at the end.

## Live dependencies a naive pass would break (verified today, read-only)

These were read from the devices' own access and audit logs, not assumed.

1. **An ONVIF/RTSP consumer at `192.168.10.112`** (user agent `GStreamer/1.20.7`) streams
   H.265 over RTSP/TCP from `back_of_house` and `front_of_house` as the ONVIF user `onvif`,
   with sessions re-created every ~hour. Its password is **not** the one in
   `~/.config/axiscam/config.yaml` — the cameras log my probe with the configured password
   as `onvif from 127.0.0.1 failed to access /onvif/device_service. Password mismatch` on all
   three cameras, while the consumer authenticates successfully. No ONVIF-over-HTTP calls
   from that host appear in the retrieved log window (RTSP only), but ONVIF clients re-read
   `GetStreamUri` over HTTP on reconnection/re-adoption, so `https.only` is a risk for it
   until proven otherwise over a longer window.
2. **Six administrator accounts on the cameras** (`accounts list`, 2026-10-13): vendor and
   service accounts `axisconnect`, `AxisDeviceMgmt`, `webrtcacapuser`, `ACCAdmin` plus
   `homeassistant` and the root admin. `ACCAdmin` is the AXIS Camera Station / Companion
   recorder account — if the S3008 records the cameras over HTTP, `https.only` breaks
   recording. `homeassistant` is the Home Assistant Axis integration, which defaults to
   port 80. **Neither has been checked for scheme yet** — that is Wave 0.
3. **`unifiprotect` (Administrator) and `onvif` (Operator) ONVIF users on the speaker.**
4. **Nothing is known to use SSH, SNMP, Bonjour, UPnP or Zero-Conf.** "Not known" is not
   "not used": Wave 0 reads the logs for `sshd` logins and any SNMP source before turning
   them off.

## Mechanism: how changes are applied

Not by hand, not by an agent, and not by the fleet fan-out.

- A new `axiscam security harden` command on the existing write-safety pattern
  (`cli/confirm.py`): read → **Planned-change panel listing the exact parameter writes the
  audit's remedies prescribe** → `--dry-run` exits 0 having written nothing → confirm
  (`--yes`) → apply one `param.cgi?action=update` per parameter, read back, verify →
  **re-run the audit and print the diff** (targeted checks must now pass; no other check may
  change). Selection by `--check ID[,ID...]` and `--exclude ID`; one device at a time —
  plan → confirm → apply → verify is per device (fleet runner rule, Phase 7b).
- **Backup first, every time**: `backup create --with-server-report` before any wave on a
  device. Parameter-based checks are revertible with `backup restore` (params-only).
- **The REST-based checks are not**: firewall (`network.firewall`), crypto policy
  (`tls.crypto_policy`), remote syslog (`logging.remote_syslog`) and SNMP
  (`snmp.legacy_versions`) live in DCA REST collections, which `restore` does not touch
  (manifest: `restore: params only`). `harden` therefore records each before-value in a
  plan file and gains `--revert PLANFILE` *before* any REST check is applied. Without that,
  Wave 3/4 have no undo except the web UI.
- **Rehearse every wave on `back_of_house` first, A/B/A**: apply, prove the consumer at
  `192.168.10.112` still has an RTSP session and Home Assistant still shows the camera,
  revert, prove the audit is back to its before-state, then apply for real. Same discipline
  as the Phase 5/6 live writes, which each found a contract defect the tests could not see.
- Writes to a device's **own** management path are the lockout class: `https.only`,
  `network.firewall` and `access.web_interface` can lock *this tool* out if wrong. Each gets
  a stated recovery path in its wave before it runs.

## Waves (each one can end; each has a countable definition of done)

### Wave 0 — read-only facts and decisions (no writes)

| # | Item | Definition of done |
|---|---|---|
| 0.1 | Identify every consumer per device from the access/audit logs over a 7-day window: source IP, account, protocol (RTSP / HTTP / HTTPS / SSH / SNMP). | A **dependency table** in this file: one row per (device, source IP, account, protocol). |
| 0.2 | Decide the six admin accounts: for each, keep / demote / remove, with the consumer it serves. | Six rows, each with a decision and a reason. |
| 0.3 | ONVIF user consistency (item A of 2026-10-14): target level **Operator** on all three cameras — least privilege, and proven sufficient because the same consumer streams from `front_of_house` and `intercom` at Operator today. Lowering `back_of_house` from Administrator needs the user's *current* password (Axis refuses `SetUser` without one, Phase 6.4) and the configured password is wrong on all three devices. **Decision needed: supply the live password, or accept a rotation and update the consumer at `192.168.10.112`.** | `onvif list --all` shows `Operator` on all three cameras **and** the consumer's RTSP session is re-established afterwards. |
| 0.4 | Syslog destination: none exists today (`servers=none` everywhere except the speaker, which reports `pass`). Decide whether to stand one up (TLS preferred by the guide) or record "no destination — deferred". | A hostname:port or a written deferral. |
| 0.5 | Firewall allow-list per device: management host(s), `192.168.10.112`, the S3008, the Home Assistant host, anything found in 0.1. | A list per device in this file, reviewed by Andy. |

### Wave 1 — zero-dependency parameters (revertible with `backup restore`)

Checks: `info.server_tokens`, `auth.brute_force_delay` (3 devices; `back_of_house` already
passes), `logging.access_log`, `discovery.bonjour`, `discovery.upnp`, `discovery.zeroconf`.
`snmp.legacy_versions` joins this wave for `intercom` and `mini_speaker` **only if 0.1 finds
no SNMP source**; it is REST-based, so it waits for `--revert` otherwise.

Why these are safe: none is a path any identified consumer uses; Bonjour/UPnP/Zero-Conf are
discovery conveniences for a device that already has a static address; brute-force
throttling only delays repeated wrong passwords. Access logging is the one that makes later
waves *more* observable, so it goes first.

Definition of done: the six checks read `pass` on `intercom`, `front_of_house`,
`back_of_house`, `mini_speaker` (24 cells, or 23 if `auth.brute_force_delay` is counted as
already passing on one) **and** the 0.1 dependency table shows every consumer still
connecting after the change (RTSP session re-created, HA camera entity available).

### Wave 2 — protocol surface with a known consumer

- `discovery.ws_discovery`: WS-Discovery is how ONVIF clients *find* a camera. An adopted
  camera is addressed by IP, so this is safe **after** confirming the consumer at
  `192.168.10.112` has the cameras configured by IP (0.1 shows reconnects without discovery
  traffic). Consequence to write down: re-adoption later means typing the address.
- `access.ssh`: after 0.1 shows no `sshd` logins in the window.
- `https.only`: **only after** 0.1 proves every HTTP consumer (`homeassistant`, `ACCAdmin`,
  the ONVIF consumer's `GetStreamUri` path) is already on HTTPS or has been moved. The
  remedy sets `System.BoaGroupPolicy.{admin,operator,viewer}=https`. Recovery path if this
  tool is locked out: the tool itself already speaks HTTPS to port 443, so it is not;
  the risk is to consumers, which is why the proof comes first. Order: viewer → operator →
  admin, re-checking consumers between each.
- `access.web_interface`: lowest value, highest nuisance — it disables the web UI you would
  use to recover from a mistake in Wave 3/4. **Deliberately last, after Wave 4**, or left
  failing with that reason. Recommendation: leave it failing and say so.

Definition of done: `ws_discovery`, `ssh`, `https.only` pass on the four param-capable
devices (12 cells); dependency table re-verified; HA camera entities available; RTSP
sessions present; `web_interface` recorded as an accepted failure or done.

### Wave 3 — TLS and crypto (REST-based; needs `harden --revert` first)

- `tls.ciphers` on `mini_speaker` (two `DHE-RSA-*` ciphers outside the guide's list; the
  remedy is the guide's own `HTTPS.Ciphers` string). The speaker is AXIS OS 11.11 — check the
  guide's note on which policies 11.x supports before applying.
- `tls.crypto_policy` DEFAULT → MODERN on the four param-capable devices. A legacy client
  that only speaks older TLS would stop connecting; 0.1's protocol column is the evidence.

Definition of done: both checks pass where applicable (5 cells); every HTTPS consumer still
connecting; `--revert` proven on `back_of_house` before the first real apply.

### Wave 4 — firewall default DROP and remote syslog (highest lockout risk)

- `network.firewall` on all five devices (the only check that *also* fails on the S3008 —
  it is REST, so it is reachable there). Allow-list from 0.5 applied **before** the default
  policy flips to DROP; the management host must be in it; apply on one camera, verify this
  tool, HA and the RTSP consumer all still reach it, then proceed. Recovery path if locked
  out: the Axis firewall exempts nothing — recovery is the control button / factory default
  (`docs/plans/2026-10-12-admin-and-modularity-review.md` § "other admin tasks"). Written
  down before the first apply.
- `logging.remote_syslog` only if 0.4 produced a destination.

Definition of done: firewall passes on 5 devices; syslog passes on 4 or is a recorded
deferral; the full consumer table re-verified one final time.

### Wave 5 — accounts

From 0.2 and 0.3: remove or demote unused administrators (`accounts remove` / `set-role`,
each through the confirm pattern with its lockout guard), make the ONVIF level consistent,
and consider a dedicated viewer-level account for any consumer that only streams (the
guide's "dedicated non-admin account" recommendation).

Definition of done: `accounts list --all` and `onvif list --all` match the 0.2/0.3 decision
tables exactly; every consumer still authenticates.

### The S3008 recorder — separate track, not this pass

No `param.cgi`, so 25 checks are `unknown`. Hardening it means the DCA REST surfaces and
the web UI; the only check this pass can act on there is the firewall (Wave 4). Everything
else stays `unknown` and is listed as such in the final report — an honest gap, not a pass.

## What this plan deliberately does not do

- Does not fan writes out across the fleet (`--all` is read-only by design).
- Does not apply anything from an agent's judgement alone — the remedies are the audit's
  verbatim parameter writes; the only judgement is the exclusion list, and that is written
  here and reviewed before it runs.
- Does not touch the ONVIF consumer's credentials without the decision in 0.3.
- Does not disable the web interface (recorded as an accepted failure unless Andy wants it).
- Does not harden the S3008 beyond the firewall.

## Order of operations, summarised

```
backup create (device) → harden --dry-run → confirm → apply → read-back verify
→ security audit (targeted checks pass, no other check moved)
→ consumer check (RTSP session present, HA entity available)
→ next wave; on any consumer failure: harden --revert PLANFILE / backup restore
```

## Open decisions (Andy)

1. **0.3** — ONVIF `onvif` user: live password, or rotate and update the consumer at
   `192.168.10.112`?
2. **0.4** — syslog destination, or deferral?
3. **0.2** — which of `axisconnect`, `AxisDeviceMgmt`, `webrtcacapuser`, `ACCAdmin`,
   `homeassistant` are in use?
4. **Wave 2** — leave `access.web_interface` failing (recommended) or disable it last?
