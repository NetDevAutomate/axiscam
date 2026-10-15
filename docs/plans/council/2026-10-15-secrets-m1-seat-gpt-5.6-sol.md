Model: gpt-5.6-sol
Verdict: **COMMIT-WITH-CHANGES** — preserve raw data paths, remove arbitrary peer text from errors, narrow parameter-value replacement, and add transformed/pre-fragmented credential tests.

## Findings

1. **blocker** — `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/api/base.py:153,164`
   `BaseAPI._get_text()` and `_post_form()` silently mutate successful device data, violating R2. This affects parameter exports, backup inputs, restore drift checks, account lists, and logs. Keep these methods faithful and redact only when constructing exceptions or explicitly sanitized MCP output.
   **Demonstrated:** a real `httpx.Response` containing `root.Image.I0.Name=<Basic token>` produced:
   > `R2_EXPORT: {'root.Image.I0.Name': '[redacted]'}`

2. **blocker** — `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/secrets.py:57-86`
   Literal replacement does not satisfy R1’s “whole or as a fragment” guarantee. URL-encoded, JSON-escaped, HTML-encoded, folded, case-transformed Digest hex, already-truncated tokens, and decoded Basic passwords can survive. A finite set of encoding variants still cannot cover an adversarial peer. Stop embedding arbitrary response bodies and SOAP reasons in exceptions; retain structured status, endpoint, content type, length, parameter name, and SOAP codes instead.
   **Demonstrated:**
   > `URL_ENCODED_SURVIVES: True echo=cm9vdDpVbml0LVQzc3QtUGE1NSE%3D`
   > `PREFRAGMENT_SURVIVES: True echo=DpVbml0L`

3. **should-fix** — `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/api/param.py:302-305`
   `body.replace(value, REDACTED)` corrupts unrelated diagnostics for short/common secrets. Perform one context-bound replacement only inside the canonical refusal:
   ```python
   sent = f"Error setting '{short_name(param_name)}' to '{value}'!"
   safe = f"Error setting '{short_name(param_name)}' to '{REDACTED}'!"
   body = body.replace(sent, safe, 1)
   ```
   Apply this only in the `body.startswith("# Error")` branch. For an unexpected reply, omit the raw body rather than attempting broad replacement.
   **Demonstrated:** value `"1"` changed the device code:
   > `Device code 101` → `Device code [redacted]0[redacted]`

4. **should-fix** — `/Users/ataylor/code/personal/network/axiscam/tests/test_mcp_secrets_wire.py:287-296`
   The tests prove literal full-header redaction before local truncation, not R1 generally. Add cases where the peer returns only a token/hash fragment, a decoded configured password straddling the cut, URL/JSON/HTML transformations, folded Basic text, and uppercase Digest hex. Add an R2 test asserting successful parameters/logs remain byte-for-byte faithful, plus low-entropy parameter values such as `"1"` and `"e"`.
   **Reasoned from coverage and confirmed by the probes above.**

## Answers

### 1. Source or sink

**Recommendation: sink-only.** R2 is correct: the library’s data APIs and backup inputs must remain faithful. Explicit MCP redaction is acceptable, but silently changing library data is not.

Raw peer text reaches exception construction at:

- `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/client.py:410-431` — generic HTTP errors; the `httpx.Response` is already present.
- `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/api/onvif_users.py:112-134,291-304` — SOAP `Reason` and fallback body excerpt; `_call()` already has the response.
- `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/api/param.py:34-45,126-140,301-309` — list, definitions, refusal, and unexpected-reply errors. Introduce response-returning text helpers, parse `.text` unchanged for successful data, and construct safe errors while the response and submitted value are available.
- `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/api/users.py:89-99,322-329` — account-list and mutation refusal text. Keep the response until the error decision; known errors may map to fixed friendly messages, while unknown raw text should not be quoted.
- `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/api/time.py:101-106` — a peer-controlled JSON `error` is embedded after `_post()` discards response provenance. Use a response-plus-decoded-JSON helper and emit a fixed operation error.

`/Users/ataylor/code/personal/network/axiscam/src/axis_cam/backup.py:206`, `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/report.py:106`, audit, CLI, and MCP surfaces propagate these exceptions; they need safe source exceptions rather than request access themselves. Successful MCP data should be explicitly sanitized at the MCP boundary, with redaction metadata where applicable.

### 2. Encoded echoes

Header-name case does not matter because request-header lookup is case-insensitive and only the value is replaced. URL encoding, JSON `\/`, HTML entities, folding, pre-fragmentation, decoded Basic credentials, and uppercase/transformed Digest values matter because they defeat literal matching.

Do not solve this with an expanding variant list. For generic HTTP failures, report status, path, content type, and body length only. For `param.cgi`, retain operation and parameter name but omit the supplied value. For SOAP, retain HTTP status, fault code/subcodes, and the fixed `_FAULT_MEANINGS` mapping; do not expose arbitrary `Reason`. This meets R1 while retaining the diagnostically useful parts required by R3.

### 3. `ParamAPI.set`

Ship the exact canonical replacement shown in finding 3, with `count=1`, only for `# Error` replies and credential-like names. Do not quote an unexpected raw reply. This preserves genuine refusal context without replacing every occurrence of `"1"`, `"e"`, or `"public"`.

### 4. Test adequacy

No. The tests cover Basic and Digest only when a complete literal credential first reaches the helper. They miss upstream fragments, transformed Basic text, transformed Digest hex, and decoded configured-password fragments.

The 8-base64-character and 12-hex-character thresholds both represent roughly 48 bits and are a reasonable practical canary threshold. They are not proof of “any fragment”: seven Basic characters or eleven hex characters escape detection. Conversely, applying `min(len(secret), threshold)` to short/common values creates unavoidable false positives. R1 should define a meaningful minimum fragment strength rather than literally treating one-character overlap as leakage.

### 5. Regressions

The significant regressions are the R2 data mutation and broad `ParamAPI.set` replacement. No import cycle is introduced: `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/secrets.py` imports `httpx` only under `TYPE_CHECKING` and has postponed annotations. Exception inheritance is unchanged. Runtime typing is valid. Literal replacement adds linear scans to potentially large parameter/log bodies, but that is secondary to correctness. The `MagicMock` pass-through behaves as intended.

## Checked and correct

- Targeted helper and MCP wire suite: **20 passed in 1.06s**.
- Literal Basic token and Digest `response` removal occurs before local truncation.
- SOAP fault parsing still preserves code and subcodes after literal redaction.
- `REDACTED` is shared without changing the MCP exception hierarchy.
- Responses without attached requests and ordinary `MagicMock` responses remain unchanged.
- Unavailable MCP servers reported by the runtime: `@mochi:mochi`, `kirocrew-cron`, `session-db`, `auto-improvement:auto-improvement`, `playwright-mcp`, `home-assistant`, `context-mode`, `time`, `studyloop`, and two unnamed configured servers.
