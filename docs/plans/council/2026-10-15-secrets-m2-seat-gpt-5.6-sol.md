Model: gpt-5.6-sol
Verdict: COMMIT-WITH-CHANGES — require Findings 1–4 before merge.

## Findings

1. **blocker — `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/mcp_server/deps.py:101-106`, `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/report.py:102-106`**
   **Wrong:** `ServerDeps.opened()` sanitizes only `AxisError` and `OSError`. Unexpected exceptions from composed operations bypass the scrubber and are logged by the MCP framework with their messages. Pydantic validation errors include rejected input values.
   **Why:** A permitted 2xx body containing only the configured plaintext password can fail model validation and place that password in server logs, even though the MCP result is generic.
   **Fix:** Catch `Exception` at the MCP device boundary and convert it to a class-only `ToolError`, matching `read_module`’s handling. Never log the unsanitized exception message or traceback at this boundary.
   **Demonstrated:**
   > `ValidationError: 1 validation error`
   > `input_value='Canary-Sup3r-S3cret!'`
   > `tool_text= Error executing tool device_report`
   > `canary_in_tool_text= False`

2. **should-fix — `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/client.py:484-505`**
   **Wrong:** `discover_apis()` catches every `AxisDeviceError`, including the new credential-echo refusal, and caches `{}`. This violates D1’s “fail loudly” requirement and makes `list_modules` treat every resource as available on an apparently legacy device.
   **Why:** Evidence that a proxy is reflecting credentials is silently downgraded to “discovery unsupported”; subsequent requests continue through the suspect peer.
   **Fix:** Introduce a dedicated `AxisCredentialEchoError` subclass and never suppress it. Suppress only a positively identified unsupported/404 discovery response.
   **Demonstrated:**
   > `discover_apis_result= {}`
   > `cached_result= {}`

3. **should-fix — `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/secrets.py:74-80`, `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/secrets.py:185-193`**
   **Wrong:** `_View` does not cover several common spellings of the configured plaintext password: form `+` for spaces, UTF-8 percent encoding, JSON-escaped quotes/backslashes, surrogate pairs, or named entities such as `&plus;`. `%XX` is decoded one byte at a time rather than as UTF-8. Multi-character named entities never reach the `\ufffd` branch because the regex excludes them.
   **Why:** An error page that decodes Basic authentication and then serializes the plaintext credential can still place it in exceptions and MCP output.
   **Fix:** Match complete raw variants of the plaintext password—`quote`, `quote_plus`, JSON string contents, and HTML escaping—or implement a UTF-8/JSON-aware source-mapped decoder. Do not collapse multi-codepoint entities to one placeholder.
   **Demonstrated:**
   > `'ab cd' 'ab+cd' -> 'decoded=ab+cd'`
   > `'päss' 'p%C3%A4ss' -> 'decoded=p%C3%A4ss'`
   > `'ab"cd' 'ab\\\"cd' -> 'decoded=ab\\\"cd'`
   > `'ab😀cd' 'ab\\ud83d\\ude00cd' -> 'decoded=ab\\ud83d\\ude00cd'`

4. **should-fix — `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/client.py:321-348`, `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/api/logs.py:222-263`**
   **Wrong:** `LogsAPI` obtains the server report through `get_raw()`, which disables success-body scanning, but then decodes and returns that content as text. An encoded Basic token therefore reaches log entries unchanged.
   **Why:** This is semantically a text sink hidden behind a binary transport path. It bypasses both `quotes_sent_auth` and the MCP scrubber’s whole-string needles.
   **Fix:** Let the logs path request scanning, or scan textual/decoded server-report content before parsing. A `scan_reply=True` option on `get_raw`, used specifically by `LogsAPI`, is the smallest change.
   **Demonstrated:**
   > `accepted= True`
   > `mcp_message= auth=cm9vdDpNYWRlVXAtV2lyZS1TZWNyZXQ%3D`
   > `encoded_token_survives= True`

## Answers

### 1. Correctness of `secrets.py`

**Recommended answer:** Correct for Authorization-token handling, except for Finding 3’s plaintext-password spellings.

Probes showed `_View.original()` correctly maps spans beginning, ending, and adjacent to escapes:

> `'%41BC' 'ABC' (0, 2) -> (0, 4) '%41B'`
> `'A%42%43' 'ABC' (1, 3) -> (1, 7) '%42%43'`

Adjacent and overlapping spans merge correctly:

> `MERGE [(0, 12), (15, 17)]`

`_token_windows` arithmetic correctly starts where at least 32 password bits are represented. Empty, one-character, ASCII, multibyte, and long multibyte usernames produced 32–40 password bits in the earliest window; a password containing `:` did not confuse the first delimiter search. Padding and stripped padding both matched:

> `abcd dTphYmNk True`
> `abcde dTphYmNkZQ== True`
> `abcdef dTphYmNkZWY= True`

Quoted and unquoted Digest `response` values were both redacted. The `\ufffd` fallback does not corrupt currently supported entities, but it also does not provide the claimed general HTML-entity support.

### 2. False positives

**Recommended answer:** Random false-positive risk is very low, but deterministic collisions with structured base64 data are possible.

For roughly 25 Basic windows, the upper bound in 100 KB of random base64 is about `25×100000/64^8 ≈ 9×10⁻⁹`; at 2.3 MB it is about `2×10⁻⁷`. Digest’s 21 twelve-hex windows have a comparable worst-case rate only in uninterrupted random hex; ordinary text is far lower. Colon-delimited MAC addresses and fingerprints cannot match twelve contiguous hex characters. A twelve-hex serial has roughly `21/16^12 ≈ 7×10⁻¹⁴` risk.

The realistic worst case is structured base64 derived from a common password:

> `root.Custom.CertificateValue=MTIzNDU2 refused= True`

Here username `ab`, password `12345678`, and legitimate base64 text encoding `123456` collide deterministically. Keep the eight-character threshold because D2 deliberately chose truncation protection, but document this rare integrity tradeoff and preserve the explicit refusal message.

### 3. Missed paths

**Recommended answer:** Fix Findings 1 and 4; the remaining principal paths are safe.

- `get_json` checks the response before parsing; JSON decode errors report position, not body content.
- Pydantic validation is safe inside `read_module`, which converts unexpected exceptions to their class name. It is unsafe in `device_report`, audit, backup, and fleet paths because generic exceptions reach MCP framework logging—Finding 1.
- `discover_apis` suppresses the security refusal—Finding 2.
- Dedicated log CGIs use `_get_text` and are scanned. Server-report fallback bypasses scanning—Finding 4.
- Audit converts `AxisDeviceError` to `UNKNOWN`; report and fleet record sanitized library errors. Generic validation exceptions remain the gap.
- `deps.opened` scrubs expected `AxisError` strings but not unexpected exceptions.
- HTTPX does not log Authorization headers by default. F6 remains valid: `ParamAPI.set` puts secret values in a GET URL, which HTTPX’s INFO request log can expose; it is already filed and was not re-opened here.
- Historical backup manifests may contain pre-fix error text; `backup_list` does not rescrub it. Treat old manifests as sensitive or migrate their `errors` fields.

### 4. Tests

**Recommended answer:** Claims 1–4 are substantially proved, but not exhaustively; claim 5 is not proved by the two named files.

`/Users/ataylor/code/personal/network/axiscam/tests/test_secrets.py` covers token spellings, fragments, padding, AUTO Basic reconstruction, Digest hash case, header-dump withholding, and 2xx detection. `/Users/ataylor/code/personal/network/axiscam/tests/test_mcp_secrets_wire.py` exercises all current MCP tools/resources over real HTTP authentication. It misses Findings 1, 3, and 4. Claim 5’s secret `ParamAPI.set` and restore read-back cases instead live in `/Users/ataylor/code/personal/network/axiscam/tests/test_restore.py`.

The most valuable missing test is the MCP composed-read logging boundary:

```python
async def test_device_report_never_logs_validation_input(capfd):
    try:
        SshConfig.model_validate({"enabled": CANARY, "users": []})
    except ValidationError as error:
        validation_error = error

    device = FakeDevice(
        "192.0.2.1",
        [FakeModule("ssh", validation_error, api_id="ssh")],
    )
    server = build_server(two_cameras(back_of_house=device))

    async with Client(server) as client:
        result = await client.call_tool(
            "device_report",
            {"device": "back_of_house", "full": True},
        )

    captured = capfd.readouterr()
    wire = "".join(getattr(item, "text", "") for item in result.content)
    assert CANARY not in wire
    assert CANARY not in captured.out
    assert CANARY not in captured.err
```

### 5. Design

**Recommended answer:** Keep central refusal plus sink redaction; it is simpler than making every parser secret-aware. Add a dedicated credential-echo exception so unsupported-API fallbacks cannot swallow the security signal, and add a sanitized generic MCP exception boundary.

Refusing a credential-bearing 2xx reply is correct for read operations: returning altered data would violate data fidelity. Fleet audit already degrades `AxisDeviceError` to per-check `UNKNOWN`, while `read_module` returns `status="error"` with a safe reason. “Error” is preferable to “unreadable” because reflection indicates an integrity failure, not merely missing permissions. The discovery suppression is the behavior that must change.

## Checked and correct

- Focused boundary suite: `60 passed in 5.33s`.
- Secret ParamAPI, restore, and SOAP cases: `17 passed, 67 deselected`.
- Header replacement occurs before fragment replacement and truncation.
- `_merge`, escape-boundary mapping, token arithmetic, padding, base64url folding, and quoted/unquoted Digest handling behaved correctly.
- Configured Basic reconstruction covers AUTO mode’s lost first attempt.
- `ParamAPI.set` checks raw `OK` before withholding, and restore suppresses secret read-back values.
- Current MCP wire tests cover every registered tool and resource with positive authentication controls.
- Unavailable MCP servers: `@mochi:mochi`, `kirocrew-computer`, `time`, `kirocrew-cron`, `kirocrew-core`, `home-assistant`, `studyloop`, `auto-improvement:auto-improvement`, `playwright-mcp`, plus two unnamed servers reported by the runtime.
