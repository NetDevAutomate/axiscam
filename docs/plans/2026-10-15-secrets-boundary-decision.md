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

- **F6 (opus): `ParamAPI.set` sends values in the GET query string**, contrary to
  `BaseAPI._post_form`'s own rule. A secret value reaches the device access log and
  httpx's INFO request log, and a peer that echoes the URL on a 4xx can show it
  URL-encoded. Reachable only from the CLI with `restore --include-secrets`; MCP never
  writes secret parameters (`write.py:66` keeps the default). Proposed fix: POST for
  updates, after confirming on a device that `param.cgi` accepts it. Related: a peer that
  echoes the `pwd` form field into a pwdgrp error. `pwd` does not match `is_secret_name`
  (CLI-only, the user's own new password).
- **F7 (opus): `audit.py:727` truncates library messages again** (`str(exc)[:120]`). After
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
