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
