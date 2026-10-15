Model: claude-opus-5.5 (Anthropic)

**Verdict: MERGE.** Every fix closes the finding it was written for, and I found no regression that matters on a genuine device. I'd fix findings 1–2 next: each is a couple of lines.

Probes are in `/Users/ataylor/.kiro/crew/scratch/runtime-a7ac9770/council-m3fix/probes-claude-opus-5.5/`. Run them from the repo with `.venv/bin/python <probe>`. `p4_mutations.sh` mutates a `git archive` copy, so the repo stays untouched (`git status` was clean afterwards). The gate reproduced at 1152 passed. I did not re-run ruff, pyright or coverage.

## Findings

**1. should-fix (low–medium): `src/axis_cam/client.py:515-526`. A redirect whose `Location` carries the decoded (plain) password is still followed and logged.**
- **What:** the hook only checks `quotes_sent_auth`, which leaves out the plain password on purpose. That exclusion exists because stored device parameters can legitimately hold the password. A `Location` header is not stored data, and no genuine Axis redirect carries the password.
- **Why it matters:** a debug proxy that decodes Basic and redirects to `/login?u=root&p=<pw>` gets the target requested, and httpx logs the URL at INFO. `MCPServer()` turns root logging up to INFO on a RichHandler that writes to stderr, so in MCP mode that line lands in the host's log.
- **Demonstrated:**
  - `p2_d10_redirect.py`: `outcome: OK 200 final=/login`, `log leaks: ['plain password', …]`.
  - `p6_mcp_logging_level.py`: httpx's effective level goes from `WARNING` to `INFO` after `MCPServer("probe")`.
- **Fix:** in the hook, add `or contains_password(location, self.password)`. Also call `logging.getLogger("httpx").setLevel(logging.WARNING)` at MCP server startup (`mcp_server/server.py:100`), which closes the sink in finding 4 too.

**2. nit: `client.py:528`. The hook's message quotes `_path_of(response)`, which can be a path the peer chose.**
- **What:** on the second or later redirect hop, that path is a previous `Location`. This contradicts D10's statement that messages "never quote response.url after a redirect chose it".
- **Demonstrated (`p2`, two hops):** `Refused a redirect from 192.0.2.10 at /hop/<PW> …`, `message leaks: ['plain password', …]`. In MCP mode the `Scrubber` removes the plain password, but the CLI prints it.
- **Fix:** pass the caller's path in `request.extensions` (httpx copies extensions onto redirect requests), or drop the path from this message.

**3. nit: `src/axis_cam/api/onvif_users.py:129-141`. Fault codes go through `error_excerpt`, so a password that is a substring of an ONVIF constant hides the code and its meaning.**
- **Demonstrated (`p3`):** with password `Password`, the subcodes come back as `['ter:InvalidArgVal', '[19 characters withheld…]']` and the meaning is lost. At `29d4b7c` the same fault reads `the device rejected the password as too weak … (ter:PasswordTooWeak)`. Reasons are now also cut at 200 characters.
- **Fix:** look up `meaning` from the raw leaf. Quote codes verbatim when they are in the fixed vocabulary (`_FAULT_MEANINGS` keys and `env:*`), and excerpt only unknown codes and the reason.

**4. File as F13 (pre-existing, outside this diff, reasoned): in MCP mode httpx logs every request URL at INFO.**
- `param.set` sends values in the GET query (`param.py:320-321`).
- A non-secret parameter that holds the password goes through `apply_plan` and ends up in stderr. The Event action URL in `test_the_confirmation_never_shows_the_device_password` is exactly that case.
- Same fix as the second half of finding 1.

## Answers

**Q1. Do D9 and D10 close their findings? Yes, for the cases they name.**
- **D9 (`p1`, demonstrated):** an earlier request's Digest hash in a later reply is refused in every common spelling I tried: verbatim, upper case, `%`-encoded, double-encoded, `\u`-escaped, and a 12-hex window from the middle.
  - A server-report tarball holding the current hash or an earlier one is refused through `get_log_files`.
  - The configured Basic token is refused over a Digest connection.
  - These pass, as stated limits: an 11-hex window, a colon-separated hash, a hash evicted after 64 requests, and a hash from before an `async with` re-entry.
  - Re-entry builds a new `VapixAuth`. The "different connection" limit should say that it covers re-entering the same `VapixClient`.
- **D10 (`p2`, demonstrated):** a token or an upper-cased Digest hash in `Location` is refused before the target is requested, and no log line carries it. The residual gaps are findings 1 and 2.
- **Mutations (`p4`):** each of six mutations turns a test red. They drop `contained`, drop the elicitation scrub, drop the hook, drop `sent=` in `refuse_echo`, stop recording, and drop the ONVIF password argument.

**Q2. New holes, or worse behaviour on a genuine device? None that blocks.**
- **ONVIF:** a real fault keeps its class and codes (`p3`: `ter:UsernameClash` with its meaning). The only exception is the pathological password in finding 3.
- **Redirects:** legitimate ones still work (`p2`). A same-host 301 keeps Basic and returns 200, and HTTP to HTTPS (308) with Digest returns 200.
- **The `sent` record:**
  - It is bounded at 64 entries (`p1`: 64 after flooding).
  - It adds no new Basic needle (one token per credential pair), and a sibling account's token with the same password does not match.
  - Against 64 hashes and 3.6 MB of genuine hex, it gave no false positive in 0.25 s (`p3`).
  - Reasoned: windows are 48 bits, so the collision rate is about 5×10⁻¹² per position.
- **One-pass hex matching:** reasoned to be equivalent to the old substring loop, because any 12-hex match sits inside a maximal hex run.

**Q3. Are F10–F12 non-blocking? Agreed.**
- **F10 (reasoned):** only an authoring bug reaches it, since every tool returns a typed model.
- **F11 (demonstrated, `p5`):** the UTF-8 echo is `REFUSED`. The UTF-16 echo is `PASSED-THROUGH, parsed token present=True`. It needs a peer that re-encodes on purpose, and the MCP `Scrubber` removes the whole token from tool output.
- **F12 (reasoned):** credential-named update values are already withheld (`_withhold_value`), and the configured password is scrubbed from MCP output. The remaining exposure is the CLI showing it to the operator.

## Confirmed correct
- **D9:** `_remember` records every outgoing value, including the Digest retry after a 401. The redirect hop's header is the same value, so nothing is missed.
- **D9:** `refuse_echo`, `_check_response` and the hook all pass `sent`.
- **D10:** the hook raises before httpx logs or requests the next URL. `AxisEchoError` gets past the `ConnectError`/`Timeout` handlers.
- **D10:** `_check_response` messages (echo and 403) use the caller's path.
- **D11:** `contained` keeps the resolver sync and its signature intact. The end-to-end SDK tests pass and go red under mutation.
- **D12:** `message/*` is scanned. Lower-hex `%`-encoding is recognised. `check_connectivity` is documented and pinned. The non-fault ≥400 path now passes the password to `error_excerpt`.

Not available in this session, and not needed for the review: @mochi:mochi, auto-improvement, context-mode, kirocrew-computer, studyloop, session-db, kirocrew-core, playwright-mcp, home-assistant and two more.
