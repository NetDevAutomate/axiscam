Model: Claude Opus 5.5 (Anthropic, `claude-opus-5.5`)

**Verdict: COMMIT-WITH-CHANGES.** Make findings 1–5 below before committing. File findings 6–8 as separate issues.

## Findings

**1. should-fix: `src/axis_cam/api/param.py:302–309`. The value is replaced before the success check, and across the whole body.**
- **What:** `body.replace(value, REDACTED)` runs before `body != "OK"` is checked.
- **Why it matters:** a successful write gets reported as a failure. Genuine refusals get reclassified as "unexpected reply", and parameter names get mangled (R3). Restore then records a false failure.
- **Demonstrated** (`probe_param_set.py`, using the suite's MagicMock pattern):
  ```
  SNMP.ReadCommunity := 'OK' reply='OK' -> AxisDeviceError: param.cgi: unexpected reply to update: '[redacted]'
  := 'K'  reply='OK' -> unexpected reply to update: 'O[redacted]'
  := 'E'  -> unexpected reply to update: "# [redacted]rror: [redacted]rror setting ..."
  := 'e'  -> Error: Error s[redacted]tting 'SNMP.R[redacted]adCommunity' to '[redacted]'!
  ...KeyPassword := '1' -> 'Network.Interface.I0.dot[redacted]x.EAPOL.KeyPassword'
  ```
- **Fix:** the code under Q3.

**2. should-fix: `src/axis_cam/secrets.py:41, 75–85`. Literal needles miss common re-spellings of the Basic token.**
- **What:** when an echo re-spells the token, the whole token gets past both the library and the MCP `Scrubber`. That is worse than the half-token this change fixes.
- **Demonstrated** (`probe_encodings.py`, token `cm9vdDpXMXJlfj4/UzNjcmV0IQ==`, output after both layers):
  ```
  URL-encoded        leaks=True -> 'auth=cm9vdDpXMXJlfj4%2FUzNjcmV0IQ%3D%3D'
  JSON \/ (PHP)      leaks=True -> '{"Authorization": "Basic cm9vdDpXMXJlfj4\\/UzNjcmV0IQ=="}'
  padding stripped   leaks=True -> 'tok=cm9vdDpXMXJlfj4/UzNjcmV0IQ'
  base64url          leaks=True
  DIGEST upper hex   leaks=True -> 'response=6629C513665A4CE987581EAAC215E959'
  ```
- **Fix:** the regex under Q2.

**3. should-fix: `src/axis_cam/secrets.py:72` (where needles come from), with `auth.py:99–136`. In AUTO mode the first Basic token is never a needle.**
- **What:** over HTTPS (the default, `config.py:201`), AUTO sends Basic first and then Digest to a Digest-only device (the 11.x case in the fleet). The final `response.request` carries only the Digest header, so the Basic token that already went out is not a needle.
- **Demonstrated** (`probe_auto_fallback.py`, where the peer quotes the earlier header across the cut):
  ```
  schemes sent: ['Basic', '', 'Digest']
  fragments in library message: ['cm9vdDpD', 'm9vdDpDY', … 'YW5hcnkt']
  fragments after MCP Scrubber: [same]
  ```
  `cm9vdDpDYW5hcnkt` decodes to `root:Canary-`.
- **Why should-fix, not blocker:** the peer has to replay an earlier header, which needs a stateful or hostile peer.
- **`response.history` can't supply the token.** `VapixAuth` changes one `Request` object in place, so the history entries show the Digest header too. Demonstrated in `probe_history.py`: `history: 401 'Digest usern'` appears twice.
- **Fix:** the Basic token depends only on the configured credentials, so always add it as a needle:
  - Signature: `redact_sent_auth(text, response, *, username=None, password=None)`, guarded with `isinstance`. MagicMock values pass through (demonstrated: returns `x`).
  - Pass `self.username`/`self.password` at `client.py:429`, and `self._client.username`/`password` at `base.py:153/164` and `onvif_users.py:297`.

**4. should-fix: `src/axis_cam/api/base.py:153, 164`. Redacting at the source silently changes data.**
- **Demonstrated** (`probe_r2_export.py`): a parameter holding base64(user:password) comes back from `export()` as `[redacted]`. `export()` is the backup payload, so that value can later become a restore target.
- **Why it matters:** this case is unlikely, but the change is silent.
- **Fix:** Q1 (refuse the reply instead of redacting it).

**5. should-fix (tests). No test guards the `_post_form` redaction, and the wire-test canary can't show finding 2.**
- **Demonstrated:** a pytest plugin that reverts only `_post_form` (`base.py:164`) leaves the suite at `1002 passed`. Control: reverting `_get_text` gives `1 failed … test_an_echoed_credential_does_not_survive_the_snippet_cut`.
- The wire canary's token `cm9vdDpDYW5hcnktVzFyZS1TM2NyZXQh` contains no `+`, `/` or `=`, so the whole class in finding 2 is invisible to it.
- **Fix, three tests:**
  - A pwdgrp echo test: `set_role` with a 200 `Error: …` body quoting the header, for both schemes.
  - Canary `Canary-W1re-S3cret~~~?a` (token `cm9vdDpDYW5hcnktVzFyZS1TM2NyZXR+fn4/YQ==`), plus URL-encoded and `\/` reflect modes.
  - An AUTO-replay case.

**6. should-fix, pre-existing, file it: `param.py:300–301`. `set()` sends secret values in the GET query string.**
- **What:** this goes against `base.py`'s own `_post_form` rule ("never in the URL"). A peer that echoes the URL on a 4xx puts the value, URL-encoded, past both layers.
- **Demonstrated** (`probe_query_echo.py`, using the wire test's own case: proxy password = configured password):
  ```
  after MCP Scrubber: Device error 404 …: {"url": "…param.cgi?action=update&Network.Proxy.Password=Canary-W1re-S3cret%21"}
  ```
- **Reach:** MCP can't trigger it, because `write.py:66` calls `plan_param_restore` with its default `include_secrets=False` (`restore.py:184`). The CLI with `--include-secrets` can. Reasoned: httpx also logs this URL at INFO.
- **Fix:** send secret-named updates with POST (reasoned; check VAPIX confirms `param.cgi` accepts POST). Also redact secret query and form values in the 4xx snippet.

**7. nit, pre-existing, file it: `src/axis_cam/audit.py:727`.**
- **What:** `str(exc)[:120]` truncates library messages a second time. Any secret only the MCP `Scrubber` knows (finding 6) can be cut into a fragment here. Reasoned.
- **Fix:** don't truncate, or truncate after scrubbing.

**8. nit, pre-existing, file it: `src/axis_cam/restore.py:280`.**
- **What:** `reads back {after!r}` prints a credential's read-back value for secret-named parameters (CLI with include_secrets). Reasoned.
- **Fix:** withhold the value when `is_secret_name` matches.

## Answers

**Q1: Source or sink.** I recommend keeping the check at the source, but making it **refuse the reply instead of redacting it**. Keep redact-before-truncate at the two non-200 sinks (`client.py:429`, `onvif_users.py:297`).

R2 is right in spirit, and item 3 breaks it (finding 4). I'd reword it as: *"data paths return what the device sent, or fail loudly; never silently altered."*

Why not sink-only:
- **The sinks that take `_get_text`/`_post_form` text:**
  - `param.py:45` `parse_param_list` (quotes the whole body)
  - `param.py:136` `parse_param_definitions`
  - `param.py:307/309` `set`
  - `users.py:99` `parse_account_list`
  - `users.py:328–329` `_check_reply`
  - the two already covered
  - `audit.py:727`, which re-truncates finished messages
- **Plumbing cost:** the first five are module-level parsers that only get text. Covering them means `_get_text` has to return the `httpx.Response`, or every API method has to catch and rewrite errors. Every future CGI parser becomes another sink to remember.
- **Digest:** these sinks quote the whole body, so the hash leaks whole, and the `Scrubber` can't catch it. They can't be left to the MCP layer.
- **What the body is:** a 200 body that quotes the request's own credential is evidence of a proxy or hostile peer, not device data.

```python
async def _get_text(self, path: str, params: dict[str, Any] | None = None) -> str:
    response = await self._client.get(path, params)
    return self._unechoed(response, path)

def _unechoed(self, response: httpx.Response, path: str) -> str:
    text, c = response.text, self._client
    clean = redact_sent_auth(text, response, username=getattr(c, "username", None),
                             password=getattr(c, "password", None))
    if clean != text:
        raise AxisDeviceError(f"{path}: the reply quotes this request's credentials; not used")
    return text
```

Effects:
- Export and backup fail loudly (`backup.py:206` records the error).
- `ParamAPI.get` returns `None`, because it already swallows `AxisDeviceError`.
- MagicMock text passes, because the comparison is by identity.
- The echo test in `test_restore` should then assert the new message.

**Q2: Encoded echoes.** Handle them by matching more widely, not by dropping the device text.

- **Handle:** URL-encoding (both escape cases), JSON `\/` and `\u002f`, stripped padding, base64url, and hex case for Digest. Each was a demonstrated whole-token leak.
- **Already safe (demonstrated):** header-name and scheme case, HTML entities, line folding, and JSON-escaped Digest quotes.

```python
_B64_SPELLINGS = {"+": r"(?:\+|%2[Bb]|\\u002[Bb]|-)", "/": r"(?:/|\\/|%2[Ff]|\\u002[Ff]|_)"}
_B64_PADDING = r"(?:=|%3[Dd]|\\u003[Dd])*"

def _token_pattern(token: str) -> str:
    return "".join(_B64_SPELLINGS.get(c, re.escape(c)) for c in token.rstrip("=")) + _B64_PADDING
# patterns = [re.escape(header), *(f"(?i:{h})" for h in hashes), *map(_token_pattern, tokens)]
# return re.sub("|".join(patterns), REDACTED, text)   # whole header tried first
```

Demonstrated in `probe_proposed_fix.py`:
- Every variant gives `leaks=False`.
- Genuine text `# Error: … 'Hall'!` is unchanged.
- In the AUTO case, both the token and the upper-cased hash come out clean.

Weighing R1 against R3:
- **Wider matching costs R3 nothing:** the needles are only the request's own credential.
- **Dropping raw text would cost R3:** it loses param.cgi, pwdgrp, SOAP and REST JSON error text.
- **Optional extra guard:** when the 4xx excerpt matches `(?i)authorization["']?\s*[:=]`, withhold it (give status, content type and length only). An echoed header dump is never useful Axis diagnostics.

**Q3: Value replacement in `ParamAPI.set`.** This is the replacement I would ship:

```python
raw = (await self._get_text(self.CGI_PATH, params)).strip()
if raw == "OK":
    return
refused = raw.startswith("# Error")
body = raw
if value and is_secret_name(param_name):
    # The documented refusal quotes the value exactly: " to '<value>'!".
    body = body.replace(f" to '{value}'", f" to '{REDACTED}'")
    if len(value) >= 4:  # any other quote; shorter values match ordinary words
        body = body.replace(value, REDACTED)
if refused:
    raise AxisDeviceError(f"param.cgi: {body.removeprefix('#').strip()}")
raise AxisDeviceError(f"param.cgi: unexpected reply to update: {body[:120]!r}")
```

- **Demonstrated on the same cases:** `'OK'` and `'K'` now succeed. `'e'`, `'E'`, `'#'` and `'1'` give `Error setting '<name, intact>' to '[redacted]'!`.
- **Why the 4-character floor:** a credential of 3 characters or fewer can't be protected by any substring rule. Also, `is_secret_name` matches widely: `Audio.A0.Passthrough := 'no'` was redacted, demonstrated. So redacting short values across the whole body would mostly hit things that aren't secrets.

**Q4: Test adequacy.** Partly proven.

- **Proven:** literal echoes for both schemes on non-200 paths. That covers REST 404s through `client.py` and SOAP through `onvif_users._post`, which the wire test's failure run reaches via `read_module onvif_users`. Also the Basic straddle on a 200 legacy-CGI body.
- **Not proven:**
  - Digest on a 200 legacy-CGI body.
  - `_post_form` (finding 5).
  - Encoded echoes (the canary can't show them).
  - AUTO replay.
  - Secret values echoed from the URL or form body (finding 6).
  - 200 JSON echoes. Reasoned, untested: `opened()` (`deps.py:105`) only catches `AxisError` and `OSError`. A pydantic `ValidationError` from a 200 echo would therefore reach FastMCP's own error text.
- **The `leaked()` heuristic is the right bar:**
  - 8 base64 characters is 6 plaintext bytes, and false positives are negligible.
  - 12 for hex is justified. There's one Digest needle per request (more than 50), so 8-hex windows would flake: about 1e-3 per needle per run, reasoned. The test's cut in the middle leaves about 16 hex characters, so the bar still catches the regression it targets.
  - Make the comparison case-insensitive: an upper-cased echo currently passes the test.

**Q5: Regressions.** Nothing beyond findings 1 and 4.

Demonstrated:
- No import cycle: each touched module imports cleanly in a fresh interpreter, and `secrets` imports only `re` at runtime.
- pyright reports 0 errors, 0 warnings, 0 informations on the touched files; ruff is clean.
- Full suite: 1002 passed.
- Cost: 0.93 ms per 387 KiB body.
- The exception hierarchy is unchanged, and MagicMock paths pass through.

Reasoned: `_check_response` now reads `response.text` in one more place. The 400 branch already reads it, and no streaming responses reach that point.

## Checked and found correct

- The snapshot matches the working tree: `git diff` equals `tracked.diff`, and both test files are identical.
- Redaction happens before the slice at `client.py:429`, and before `parse_fault` at `onvif_users.py:297`.
- `except (AttributeError, RuntimeError)` matches the RuntimeError httpx raises when no request is attached; a header that isn't a string passes through.
- Only the Digest `response` is treated as a credential; nonce, cnonce, realm and username are left alone.
- Needles run longest first, so the whole header goes before the token.
- `REDACTED` is still re-exported by `axis_cam.mcp_server.redact`.
- MCP never writes secret parameters.
- The wire test's positive controls (`served > 50`, Digest seen, the marker reaching the output, `TOOL_NAMES` coverage) rule out a pass where nothing ran.
- The brief's line references match the snapshot.

Tooling note: these MCP servers were unavailable: studyloop, playwright-mcp, home-assistant, auto-improvement, time, kirocrew-core, kirocrew-cron, kirocrew-computer (+2 more), and @mochi. The review didn't need any of them. The repository was not modified (confirmed by a final `git diff`), and no network host was contacted. The probes are in `/Users/ataylor/.kiro/crew/scratch/runtime-a7ac9770/council-m1/probes-claude-opus-5.5/`.
