# Secrets boundary: decision after the milestone-1 council (2026-10-15)

Brief: `docs/plans/2026-10-15-secrets-boundary-council-brief.md`. The four seats are
recorded verbatim under `docs/plans/council/2026-10-15-secrets-m1-seat-*.md`. The
arbitration below weighs arguments, not votes. Every claim a decision rests on was
re-run by the coordinator against the snapshot.

## Seats

| Seat | Verdict | Rating | Why |
|---|---|---|---|
| claude-opus-5.5 | COMMIT-WITH-CHANGES | useful | 8 findings; all 7 probes re-run by the coordinator and outputs match; corrected the coordinator's `response.history` assumption |
| gpt-5.6-sol | COMMIT-WITH-CHANGES | useful | 3 demonstrated claims, all reproduced; dissent on Q2 outweighed (below) but its adversarial-peer point adopted as a stated limit |
| deepseek-3.2 | COMMIT-WITH-CHANGES | noisy | leaked DSML tool-call markup; its header-case finding is contradicted by its own probe (`authorization: Basic ... Redacted? True`); Q1 dissent answered below |
| qwen3-coder-next | COMMIT | noisy | narrated process instead of results; verdict contradicts its own R2 finding; "demonstrated" claims show no output |

The LiteLLM `litellm-proxy-docker council` could not run here: its key comes from
1Password and needs `OP_SERVICE_ACCOUNT_TOKEN`, which is not set in the agent shell.
Getting it would mean decrypting a credential file. The seats ran as Kiro sub-agents
from four labs on one byte-identical brief, in isolation, which is the same method.

## Decisions

**D1. Source check: refuse, never redact (Q1).** The brief's requirement R2 is reworded,
following opus: data paths return what the device sent or fail loudly, and are never
silently altered. Redacting in `BaseAPI._get_text` changed data. GPT demonstrated it
and the coordinator reproduced it with `export()`, which returned `[redacted]` for a
stored value. Sink-only redaction would make every module-level parser and every future
one a sink to remember; this is deepseek's maintenance point, and it is right. Synthesis:
`VapixClient._check_response` refuses any success reply that quotes the request's own
credentials, in any spelling. It is the one choke point every device reply passes
through: text, JSON (`time.py:106`, and pydantic validation that would echo input),
SOAP 200 and form posts (`_post_form`, which no test covered; opus F5). Binary
downloads are not scanned. `BaseAPI` goes back to returning raw text. Genuine Axis text
never quotes the request's own credential (no device echoes headers), so the check never
fires on a real device.

**D2. Sinks: match every common spelling, keep the text (Q2).** GPT alone argued for
dropping peer text from errors. Opus, deepseek and qwen argued against, because dropping
it loses param.cgi, pwdgrp, SOAP and REST JSON error text (requirement R3), and opus
showed that wider matching costs R3 nothing. At the two error sinks (`client.py` 4xx/5xx
and `onvif_users._call`), the text is redacted before any truncation for:

- the header;
- the Basic token in the spellings opus demonstrated as whole-token leaks: URL-encoded
  (either hex case), JSON `\/` and `\u002f`, padding stripped, base64url;
- every Digest `response` hash, matched case-insensitively;
- the configured plain password (4 characters or more), literal and URL-encoded;
- fragments a peer cut short itself: any 8-character window of a token or of the
  password, and any 12-character window of a hash (GPT's pre-fragment case).

A 4xx/5xx excerpt that dumps request headers is withheld outright, because it has no
diagnostic value (opus's optional guard).

**D3. AUTO-mode replay (opus F3, also found by the coordinator).** `VapixAuth` changes one
`Request` in place (`auth.py:133`), so neither `response.request` nor `response.history`
still holds a Basic token that was sent before falling back to Digest. Verified: history
entries carry only the Digest header. The Basic token depends only on the configured
credentials, so the client always adds it as a needle.

**D4. `ParamAPI.set` (Q3, 4/4 agree on the shape; opus's demonstrated code adopted).**
`OK` is checked before any replacement, so a value of `OK` or `K` can no longer turn a
success into an error. The refusal is replaced in its documented context, `to '<value>'`.
Whole-body replacement applies only for values of 4 characters or more, because shorter
values match ordinary text and `is_secret_name` matches widely (`Audio.A0.Passthrough`).

**D5. Read-back of a secret parameter (opus F8):** fixed now, because it is the same
concern, a credential in a message. Restore withholds the value it reads back for
credential-named parameters.

## Stated limits (not goals)

- A peer that already holds the credential and deliberately re-encodes it (reversed,
  base32, digits) defeats any free-text filter, including the drop-the-text option, since
  even numeric fields can carry it. The guarantee covers reflection: verbatim echoes,
  common encodings and peer truncation (GPT's argument, adopted as a stated limit).
- A Digest `response` hash from an earlier attempt in a Digest-to-Basic fallback. That
  only happens over plain HTTP with `allow_insecure_basic`, and a hash is per-request and
  only useful together with its nonce.
- A 2xx body that carries the configured plain password without the token. Legitimate
  data does this (an admin password reused as the proxy password), so it cannot be a
  refusal trigger. Echo pages that decode Basic auth also show the header, which triggers
  D1/D2.

## Filed, not fixed

- **F6 (opus): `ParamAPI.set` sends values in the GET query string** (fixed 2026-10-22,
  D13/D14 below), contrary to
  `BaseAPI._post_form`'s own rule. A secret value reaches the device access log and
  httpx's INFO request log, and a peer that echoes the URL on a 4xx can show it
  URL-encoded. Reachable only from the CLI with `restore --include-secrets`; MCP never
  writes secret parameters (`write.py:66` keeps the default). Proposed fix: POST for
  updates, after confirming on a device that `param.cgi` accepts it. Related: a peer that
  echoes the `pwd` form field into a pwdgrp error. `pwd` does not match `is_secret_name`
  (CLI-only, the user's own new password).
- **F7 (opus): `audit.py:727` truncates library messages again** (`str(exc)[:120]`; fixed
  2026-10-22, D15 below). After
  D1/D2 the library's own messages carry no credential spellings, so the remaining
  exposure is a secret request value (F6). It gets fixed together with F6.

## Milestone 2: implementation review (commit `9199ad8`)

Brief: `docs/plans/2026-10-15-secrets-boundary-m2-council-brief.md`. The three seats are
recorded verbatim under `docs/plans/council/2026-10-15-secrets-m2-seat-*.md`.

| Seat | Verdict | Rating | Why |
|---|---|---|---|
| claude-opus-5.5 | COMMIT-WITH-CHANGES | useful | 8 findings, 12 probes; the coordinator re-ran 6 of them and they match; proposed the simplification adopted as D6 |
| gpt-5.6-sol | COMMIT-WITH-CHANGES | useful | 4 findings; its probes were not saved, so the coordinator rebuilt all 4 and each one reproduced |
| deepseek-3.2 | COMMIT-WITH-CHANGES | noisy | 26 leaked tool-call markers despite the instruction; its main finding is moot for real input; it missed all of the above |

**D6. Any reply that quotes the request's credentials is refused, whatever its status,
with `AxisEchoError(AxisConnectionError)`.**

- Opus F1 and GPT F2 were both demonstrated: about 60 module methods turn `AxisDeviceError`
  into defaults, and so does `discover_apis`. So the D1 refusal still read as "the API is
  absent", and 16 of 26 modules came back from `read_module` as `ok` with made-up values.
- A connection-class error is never caught by those fallbacks. The audit already re-raises
  it, fleet shows one error row, and `read_module` reports `error`.
- An echo in a 4xx/5xx page is the same evidence, so the same rule applies there. That
  makes span redaction at the sinks unnecessary. Opus proposed this simplification as a
  follow-up; it is adopted now, because without it a 404 echo page would still become an
  `AxisDeviceError` and be swallowed.
- The position-mapping view, span merging and replacement are deleted, along with the
  header-dump rule, which Opus F8 showed fires on an ordinary JSON key.
- What is left at the sinks: genuine device text is quoted verbatim, cut to 200
  characters. An excerpt that contains the configured password, in any common spelling,
  is withheld (GPT F3).

**D7. The MCP tool boundary.** GPT F1 was demonstrated: a pydantic `ValidationError` from a
composed tool (`device_report`) went past `deps.opened`, and the SDK logged its traceback
with the rejected input. Every registered tool is now wrapped. An unexpected exception
becomes `ToolError("internal error: <Class>")` raised `from None`, so the SDK logs one line
and no traceback.

**D8. The rest:**

- **Binary downloads:** scanned when the reply is text by `Content-Type`.
- **Server-report logs:** `get_log_files` checks the decoded log text against the configured
  credentials (Opus F2, GPT F4).
- **`backup restore` results table:** no longer prints a credential's target value (Opus F3).
- **Spellings:** any HTML entity that decodes to a single character, and double URL-encoding
  (escapes are undone twice), per Opus F5.
- **Passwords under 4 bytes:** only the whole token counts (Opus F6).
- **Digest:** `response=` is matched without case (deepseek).
- **Tests:**
  - Opus's oracle test for the window boundary and an HTML-entity spelling test (F4).
  - Opus's every-module echo test.
  - GPT's no-log test for validation input.

**Stated limits added:**

- A configured password that is reused and stored *base64-encoded* in device data is
  refused for some username lengths (Opus F7). No Axis parameter is known to store one.
- A `:` in the username moves the token's password boundary. RFC 7617 forbids it and Axis
  account names cannot contain it.
- A short or common password (four characters or more) that appears in a genuine error
  page gets that excerpt withheld. Only the device's wording is lost.

**Filed (F8, F9):**

- Backup manifests written before this change are not re-checked: `errors` text from an
  echoing peer could sit in an old manifest (GPT).
- Pre-existing: module methods that turn a genuine 404 into defaults are reported as `ok`
  by `read_module` on devices without API discovery (Opus F1's mechanism, outside echoes).
  Fix it in the modules, not at the MCP layer.

## Milestone 3: merge review (commit `f44827e`)

Two seats reviewed `f44827e` against `9199ad8` (`claude-opus-5.5` MERGE-with-follow-ups,
`gpt-5.6-sol` BLOCK). `deepseek-3.2` was dropped: it leaked tool-call markup in both earlier
rounds and its findings did not reproduce. Both seats' probes were re-run by the coordinator
before anything was changed; each fix below went in test-first (RED), and every defence was
mutation-checked (ten mutations, each turns a test red).

**D9. The client remembers every credential it sent (GPT F1, Opus F2).** `VapixAuth` records
each `Authorization` value it sends (`sent`, a `deque(maxlen=64)`; Digest sends a new value
per request). `_check_response`, the redirect hook and `refuse_echo` pass that record to
`quotes_sent_auth(..., sent=...)`. Before this, a Digest login hash was known only for the
request at hand, so the server-report tarball — decoded after its response is gone, over
Digest in AUTO mode — reached the log entries with the hash in it. Digest matching now scans
each hex run in the text once against a set of windows, so the cost does not grow with the
number of remembered hashes.

**D10. A redirect whose target quotes the credentials is refused before it is followed
(Opus F1).** A response event hook raises `AxisEchoError` on a 3xx whose `Location` passes
`quotes_sent_auth`, so httpx never requests the target or logs its URL. Messages quote the
path the caller asked for (`_check_response(path=...)`), never `response.url` after a
redirect chose it.

**D11. The confirmation resolver runs inside the boundary (GPT F2, Opus F8).** `apply_plan`'s
`Resolve(confirm_plan)` runs before the tool body, outside its `contained` wrapper, so a crash
there was logged by the SDK with its traceback. It is now `Resolve(contained(confirm_plan))`,
and the elicitation text the human sees is scrubbed like every other output (a value under a
non-secret name can still hold the password, e.g. a credential in a URL).

**D12. Smaller correctness fixes.**
- `message/*` joins `_TEXT_TYPES`, so a download labelled `message/http` (what TRACE, the
  standard request echo, returns) is scanned (Opus F2).
- `contains_password` recognises lower-case-hex percent-encoding of a non-ASCII password
  (Opus F7-nit).
- An ONVIF SOAP fault is parsed first and each field quoted through `error_excerpt`, so a
  fault that carries the configured password keeps its class and codes while the field that
  holds the password is withheld — previously the whole fault was replaced (Opus F6).
- `check_connectivity` returning `False` for an echoing peer is documented as intended
  (fail-closed) and pinned by a test (Opus F5).

**Tests added:** `TestSentRecord` (auth), `TestEchoBeyondTheReplyBody` (client: same-connection
Digest replay, redirect, `message/http`, connectivity), `TestServerReportDigestEcho` (logs),
`TestEverythingTheClientSent` and `TestPasswordSpellingsLowerHex` (secrets), the ONVIF
fault-survives and password-withheld cases, `TestTheConfirmationPath` (apply), and the sync-tool
crash test (read tools).

**Stated limits added:**

- A Digest `response` hash replayed from a *different* connection (a separate client, or
  another process) is not recognised: the current client never sent it, so to a text filter it
  is indistinguishable from stored device data, and a spent Digest hash is not a reusable
  credential. The *same-connection* replay — an earlier request's hash echoed into a later
  reply — is refused (D9). The configured Basic token is always a needle, connection or not.

**Filed (F10–F12):**

- **F10:** the SDK's output-conversion step runs outside `contained` (`tools/base.py`), so a
  value that fails result conversion is logged by the SDK. Only an authoring bug reaches it
  today — every tool returns a typed model — but a resolver/output wrapper at registration
  would close it fully.
- **F11:** the scan reads `response.text` (UTF-8 unless the header says otherwise) while
  `response.json()` lets `json.loads` detect UTF-16/32; a peer that returns UTF-16 JSON with no
  charset is scanned differently from how it is parsed. Pre-existing; it needs a deliberate
  re-encoding peer, already a stated limit. Fix: `json.loads(response.text...)`.
- **F12:** the in-band 2xx error sinks in `api/users.py`, `api/param.py` and `api/time.py`
  quote device text uncut and do not call `error_excerpt`. They sit outside D2's two sinks and
  only fire on a genuine device error that holds the configured password. Route them through
  `error_excerpt`.

### Confirmation review of `fac5e2a`

One opus seat confirmed each fix closes its finding with no genuine-device regression
(verdict MERGE), and found three residuals, all demonstrated and fixed here (test-first,
each mutation-checked):

- **A redirect whose `Location` carries the *plain* password is now refused.** The echo check
  excludes the plain password (device parameters may legitimately hold it), but a `Location`
  is not stored data, so the redirect hook also calls `contains_password(location, ...)`. A
  debug proxy that decodes Basic and redirects to `/login?p=<pw>` is refused before the target
  is requested.
- **In MCP mode, httpx request logging is pinned to `WARNING`.** Constructing the server leaves
  the root logger at INFO, at which httpx logs every request URL — and a GET carries parameter
  values in its query string (`param.set`), so a non-secret parameter holding the password
  would reach the host log. `build_server` sets `logging.getLogger("httpx")` to `WARNING`. This
  also closes **F13** (filed and fixed together): the httpx request-URL sink in MCP mode.
- **The redirect refusal names no path.** On a second hop the request path is one the peer
  chose, so the message names only the host and the reason.
- **An ONVIF fault keeps its meaning when the password is a substring of a code.** Fault
  *codes* are QNames from a controlled vocabulary (and any reply quoting the sent credentials
  is already refused), so they are quoted verbatim; only the *reason*, free device text, goes
  through `error_excerpt`. Previously a password such as `Password` — a substring of
  `ter:PasswordTooWeak` — withheld the subcode and lost the fault's meaning.

Non-blocking confirmations the seat recorded: D9 refuses an earlier same-connection Digest
hash in every spelling tried, the `sent` record stays bounded at 64 and adds no false
positive against 3.6 MB of genuine hex, and F10–F12 are agreed non-blocking (F11 needs a
deliberate re-encoding peer and the MCP `Scrubber` removes the whole token from tool output).

## F6 and F7: fixed (2026-10-22, branch `param-update-post`)

The device contract was checked live before any code changed, through this library's own
client (AUTO authentication, echo checks on), with no state change: a list, a request with
no `action`, and an `action=update` of a parameter that does not exist, each sent by GET and
by POST.

| Device | POST `action=list` | POST without `action` | update of an unknown parameter |
|---|---|---|---|
| front_of_house, back_of_house (M3216-LVE, AXIS OS 12, Basic) | listing | `action must be specified` | same `# Error` line by GET and POST |
| intercom (I8016-LVE, Basic) | listing | `action must be specified` | same `# Error` line by GET and POST |
| mini_speaker (C1410, 11.x, Basic then Digest) | listing | `action must be specified` | same `# Error` line by GET and POST |
| nvr (S3008) | 404 | — | 404 (no `param.cgi` at all, GET included; known) |

The body-without-`action` control shows the device takes `action` from the body: a device
that ignored bodies would answer every POST that way. After the change, the new
`ParamAPI.set` wrote `Image.I0.Name` back with its current value on both cameras (`OK`,
read-back unchanged), and the speaker's refusal arrived over Digest, so the body is re-sent
correctly after the challenge.

**D13. `ParamAPI.set` sends `action=update` in a POST form body, for every parameter.** Not
only for credential-named ones: the name rule is a heuristic (a false negative leaks), one
path is simpler to test, and POST costs nothing. The URL now carries no parameter name or
value, so neither reaches the device access log, httpx's INFO request log, a proxy's log or
a peer that echoes URLs. Tested through the real client: the request is a POST with an empty
query, and httpx's log line names neither the parameter nor the value. The MCP wire test's
fake camera now reads a form body exactly as the query string (the live contract above) and
asserts the restore's update carried nothing in its URL.

**D14. An excerpt that quotes a credential the request carried is withheld, like the
configured password.** `error_excerpt(..., secrets=...)`. The caller names the credentials in
the form (`_post_form(..., secrets=...)` → `VapixClient.post(..., secrets=...)`): a
credential-named parameter's value in `ParamAPI.set`, and the `pwd` in `UsersAPI.add` and
`set_password` (the "related" note under F6). It covers three sinks: the client's 4xx
excerpt, `ParamAPI.set`'s unexpected-reply excerpt (it used a literal replace that missed a
form-encoded echo), and `UsersAPI._check_reply`'s 200 `Error` text. The device's own
`# Error: Error setting '<name>' to '<value>'!` keeps the scoped D4 replace, so the parameter
name stays readable.

**D15 (F7). The audit withholds before it cuts.** `_unreadable` cuts a library message to
120 characters for the table. It now goes through `error_excerpt(..., password=<the
device's configured password>, limit=120)`, so a message that holds the password in any
spelling is withheld whole. Before, the cut could leave a password fragment that the MCP
`Scrubber` (whole strings only) does not recognise. The audit's catalogue stand-in device
gained `client.password = ""`. The F12 sinks (2xx error text quoted uncut) stay filed; this
keeps them out of audit output in any case.

**Redirects.** httpx turns a POST answered with 301/302/303 into a bodyless GET. The device
then answers `action must be specified`, and `set()` reports the change as failed, never
as a silent success (tested). A 307/308 re-sends the body to the target the first hop chose;
that hop already received it, so this is a stated limit, not an escalation.

Each defence was proven load-bearing by removing it. 15 mutations, each turning at least one
named test red: `set()` back to GET; the secret not passed on at each of its three hops
(`set()`, `_post_form`, the client's 4xx excerpt); `error_excerpt` ignoring `secrets`;
`set()`'s unexpected reply cut plainly; `_check_reply` quoting an echoed `pwd`; `add` and
`set_password` not naming `pwd`, to the transport or to `_check_reply` (four); the audit
cutting before withholding, or withholding without the configured password; and (D16) the
refusal phrase matched by the short name only, or the full name only. One mutation
first survived: the mutation runner rewrote the same file to the same size within one
second, and Python reused the previous mutant's `.pyc` (a timestamp `.pyc` is valid when
the source's whole-second mtime and size match). With a fresh bytecode cache per run
(`PYTHONDONTWRITEBYTECODE=1`, a new `PYTHONPYCACHEPREFIX`) it is caught.

**D16. The refusal phrase is matched with the full name too.** A live refusal of an
unknown credential-named parameter showed AXIS OS 12 quotes the *full* name
(`Error setting 'root.Axiscam.Probe.Password' to '…'!`) although `set()` sends the short
one. D4's scoped replace looked only for the short spelling the VAPIX page writes, which the
unit tests had copied. So a value that is part of the name (`Probe`) garbled it
(`root.Axiscam.[redacted].Password`), and a value under 4 characters was quoted unredacted.
`_withhold_value` now matches the phrase with or without `root.`; the tests cover both
spellings, and two mutations (short-only, full-only) each turn them red. This is the same
lesson as the `param.cgi` single-parameter echo: a fixture copied from the documentation
encodes a belief about the device, and only the device's own reply settles it.

**Filed (F14), found during the live check** (fixed the same day, D17 below)**:** every device answers **HTTP 401** to an update
of a parameter nobody may write (`securityLevel` write digit 7), by GET and by POST alike, so
it predates this change. Seen on `Brand.Brand` (7707) on all four devices with `param.cgi`,
and on the I8016-LVE's `Image.I0.Name` (7707, `readonly="true"`; writable on the cameras).
The documented `# Error` line is what an *unknown* parameter gets. `ParamAPI.set` therefore
raises `AxisAuthenticationError` ("check username/password"), which `apply_param_restore`
treats as fatal. Plans skip read-only parameters when `listdefinitions` is readable, so a
restore only meets this when definitions are missing. Recommended fix: on a 401 to an update,
re-read the parameter with the same client, and if that read succeeds, report a
per-parameter refusal rather than an authentication failure. This does not affect fresh
clones or CI.

## F14: fixed (2026-10-22, branch `param-unwritable-401`)

**D17. A 401 to an update is checked with one read using the same credentials.** RFC 9110
§15.5.2 keeps 401 for refused credentials, and §11.4 says that "a server that receives
valid credentials that are not adequate to gain access ought to respond with 403". AXIS OS
answers 401 for both, so the status cannot tell a wrong password from an unwritable
parameter. `ParamAPI.set` therefore reads `Brand.Brand` once with the same credentials. Every
Axis device has that parameter, and anyone may read it (level 7707). The read carries
`usergroup=viewer`, the VAPIX way to make the device demand credentials even when anonymous
viewing is on.

- **A listing proves the credentials.** The refusal then belongs to that parameter:
  `AxisParamNotWritableError(AxisDeviceError)`. Its message names the parameter and never
  the value. `apply_param_restore` already records any `AxisDeviceError` per change, so
  restore needed no logic change. `backup restore` prints the refusal as one row, and the MCP
  `apply_plan` returns `partial`.
- **Anything else leaves the 401 an authentication error, as before.** That covers a 401,
  403 or 500, an HTML page, and a `# Error` line. This fail-closed direction matters. If a
  wrong password were misread as a per-parameter refusal, the restore would carry on, and
  every remaining parameter would cost one more failed login. With the check, a wrong
  password costs exactly one extra read before the run stops.
- **A connection error during the check propagates,** an `AxisEchoError` included. It is
  never mistaken for missing proof.
- **A 403 to an update is left alone.** It has never been observed from `param.cgi`, and
  the caller decides.

Evidence gathered before the design, all read-only or same-value:

- The 401 for an unwritable update is `param.cgi`'s own. It has a challenge, no body and no
  content type. The web server's 401 for missing or wrong credentials is a 421-byte HTML
  page. That difference is undocumented, so it is not used.
- The devices log these 401s as `param.cgi-transfer: unauthorized in an iteration` in the
  system log, never as `Authentication failed` in the audit log. Today's runs across all
  four devices produced no audit-log failed login, including on `back_of_house`, where
  `System.PreventDoSAttack.ActivatePasswordThrottling=On`. Requests made right after each
  401 were answered normally.
- `System.BoaProtViewer=password` on all four devices, so anonymous viewing is off
  everywhere. The `usergroup=viewer` safeguard for devices that do allow anonymous viewing
  was checked to be accepted, but its effect on such a device could not be observed here.

Live verification of the shipped code, all on the same day:

- `set(Brand.Brand)` with its current value raised `AxisParamNotWritableError` on all four
  devices, over Basic and over the C1410's Basic-then-Digest negotiation.
- `set(Image.I0.Name)` with its current value raised the same on the I8016-LVE. On both
  cameras it succeeded, and the read-back was unchanged.
- An unknown parameter still raised the documented `# Error` as a plain `AxisDeviceError`.
- `apply_param_restore` on `front_of_house` with a same-value plan for `Brand.Brand` and
  `Image.I0.Name` returned one refused row and one verified row, without raising.
- The audit logs since the start of the run showed 0 failed logins.

Tests:

- Through the real client (respx): the per-parameter case, a rejected login that stays an
  authentication error, four kinds of non-proof, a connection error and an echo during the
  check, and a 403.
- Through the hermetic camera in the MCP wire test, over Basic and Digest in AUTO mode. Its
  fake now answers an update of a read-only parameter with the device's 401 and quotes an
  unknown one by its full name, as the live devices do.
- At the restore, CLI and MCP `apply_plan` level: one row, the run continues, and the status
  is `partial`.
- Eight mutations, each turning at least one named test red: no check; the check always
  failing; no `usergroup`; any 2xx counted as proof; a 403 also checked; connection errors
  swallowed; the value quoted; the error class outside `AxisDeviceError`.

**Filed (F15):** `apply_param_restore` loses the results of changes it has already written
when an error that ends the run interrupts it: a connection drop, an echo, or credentials
changed mid-run. The CLI and `apply_plan` then report only the error. The user is not told
which parameters were already changed. F14 was the common way to reach this and is fixed.
The rest is rare, but the device is left part-restored with no record. Recommended fix:
raise a `RestoreInterruptedError` that carries the results so far and the cause. The CLI
prints the partial table, and `apply_plan` returns status `interrupted` with the results.

**Observed, not caused by this work (fleet, for Andy):** both cameras logged **61 failed
logins as `root`**, once a minute from 00:00:45 to 01:00:45 BST on 2026-10-22. All were on
`/axis-cgi/pwdgrp.cgi` ("Password mismatch"). The intercom logged one at 00:00:22 UTC, which
is 01:00 BST. The devices show the source as 127.0.0.1 (their local proxy), so it cannot be
traced from the device. One attempt a minute for exactly an hour, against `pwdgrp.cgi` (what
`accounts list` reads), looks like a bounded scheduled job using an old root password. Look
for a job that was running at midnight. None of today's F6, F7 or F14 work ran then.
