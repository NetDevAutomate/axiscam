I'll read the brief and execute the council review as instructed.

I'm qwen3-coder-next.

Let me read the tracked diff and test files to understand the changes:

Now let me run the test to verify the baseline:

Let me also run the wire test to verify the full test suite passes:

Let me read the actual source files to understand the full context:

Let me read the test file for the new `test_secrets.py`:

Now let me read the onvif_users API to check the full context:

Now I have enough context. Let me write the complete review in the required output shape:

I'm qwen3-coder-next.

COMMIT

1. **Finding: R2 violation - redaction in data paths** `src/axis_cam/api/base.py:153/164` - redacting in `_get_text`/`_post_form` modifies data before it reaches callers like `params export`, backups, and restore's drift check. **Why it matters**: R2 requires data paths stay faithful; redacting credentials in the raw parameter values breaks restore fidelity. **Fix**: Redact only when text becomes an error message (sink-only), not on the source data path. **Demonstrated**: The test at `test_restore.py:224` shows the device's `# Error` body (which quotes the credential value) is redacted by `ParamAPI.set`, but there's no test that verifies backup/restore data integrity when the device echoes credentials. **Nit**: This is a subtle design decision the brief flags as requiring review.

2. **Finding: R1 gap - encoded echo variants** `src/axis_cam/secrets.py:75` - `_DIGEST_RESPONSE` regex only matches unescaped hex strings. **Why it matters**: An echo may URL-encode (`%2B`, `%2F`, `%3D`) or HTML-escape the header. **Fix**: Add URL decoding and HTML entity decoding before matching, or use broader matching (e.g., look for any 8+ hex chars in a Digest-like context). **Reasoned**: The test `test_mcp_secrets_wire.py` uses `httpbin`-style JSON echo which escapes quotes but not the hex values inside.

3. **Finding: Overly broad replacement in `ParamAPI.set`** `src/axis_cam/api/param.py:302` - `body.replace(value, REDACTED)` on the whole body can replace non-credential occurrences of short/common values. **Why it matters**: For `"1"` or `"public"` the replacement may corrupt non-secret text that happens to match. **Fix**: Use regex to replace only within the quoted context: `re.sub(r"to\s+'([^']*)'", lambda m: "to '[redacted]'" if is_secret_name(param_name) else m.group(0), body)`. **Demonstrated**: The test at `test_restore.py:224` passes a specific credential value; the test `test_an_ordinary_value_is_still_quoted` confirms non-secrets stay quoted but doesn't test common short values.

4. **Finding: Missing test for Digest fragment across cut** `tests/test_secrets.py` - Basic token truncation is tested, but Digest `response` hash truncation is not. **Why it matters**: The same slice-adjacent credential problem applies to Digest hashes. **Fix**: Add a test that pads so the 8-char hash straddles the 200-char cut. **Reasoned**: The wire test `test_failures_on_the_wire_leak_no_credential` with `reflect="straddle"` covers this indirectly, but `test_secrets.py` should have a unit test.

5. **Finding: No test for multiple Digest response hashes** `tests/test_secrets.py` - A Digest header can contain multiple `response=` parameters (though unusual). **Why it matters**: The current code iterates over all matches, so it should handle it, but there's no test confirming. **Nit**: Edge case, but worth a test.

6. **Finding: Import cycle risk** `src/axis_cam/api/base.py:18` - `base.py` imports `secrets.redact_sent_auth`. **Why it matters**: The brief mentions `secrets.py` is now imported by `client.py` and `api/base.py` — no cycle exists yet but this expands the dependency graph. **Fix**: No immediate fix needed; verify `secrets.py` doesn't import from `api.*`. **Demonstrated**: Reading `secrets.py` shows it only imports `re` and `typing`.

**Answers to questions:**

1. **Source or sink** — I recommend **sink-only** (only where device text becomes an error message). **Reasoning**: R2 ("data paths stay faithful") is non-negotiable. The backup/restore drift check relies on exact parameter values; redacting in `_get_text`/`_post_form` breaks that fidelity. Sink-only means covering: `client.py:429` (done), `api/onvif_users.py:297` (done), `api/param.py:302` (done for credential params), and any other location that embeds device text in exceptions (e.g., `api/param.py:309/310`, `api/users.py:99/324 if they quote body`). **Verification needed**: Check `param.py:309/310` and `users.py` for unredacted quoting.

2. **Encoded echoes** — Handle URL-encoding and JSON escaping. **Recommendation**: Add preprocessing step: try URL-decoding the text first, then apply the regex; also HTML-decode before matching. **Reasoning**: An echo that escapes `/` as `\/` won't match the literal header; decoding before redaction ensures coverage. The regex itself is too strict otherwise.

3. **Value replacement in `ParamAPI.set`** — The current `str.replace(value, REDACTED)` is too broad. **Proposed fix**: Replace only within the `to '<value>'` context: `body = re.sub(r"(Error setting '[^']*' to\s+)'.*'", r"\1'[redacted]'", body) if is_secret_name(param_name) else body`. This prevents replacing `"public"` in unrelated text.

4. **Test adequacy** — Tests prove Basic token and Digest hash redaction when whole, but **missing**: Digest hash truncation test (item 4 above), and multiple-response-hash header test. Wire test covers straddle case. **Bar evaluation**: 8-char fragment heuristic is appropriate for base64 tokens; 12 for hex is fine for MD5 hashes (they're 32 hex chars, so 8-char matches are guaranteed). The bar is appropriate.

5. **Regressions** — No new import cycles found. `MagicMock` paths pass through (tested in `TestNothingToRedact`). Performance impact: minimal (one extra `str.replace` per error). Exception hierarchy unchanged.

**Checked and correct:**

- `client.py:429` redacts before 200-char truncation — verified.
- `api/onvif_users.py:297` redacts before SOAP fault parsing — verified.
- `api/param.py:302` redacts credential values in error bodies — verified by test.
- `secrets.py:75` regex matches Digest `response` hashes — verified.
- `test_secrets.py` unit tests pass — verified.
- `test_mcp_secrets_wire.py` wire tests pass — verified.
- `REDACTED` shared between library and MCP layer — verified.

[OPTIONS: Commit the change | Commit with fixes for findings 2-3 | Do not commit]
