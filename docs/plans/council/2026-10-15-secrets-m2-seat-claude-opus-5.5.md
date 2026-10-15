Model: claude-opus-5.5 (Anthropic)

**Verdict: COMMIT-WITH-CHANGES.** Make findings 1–4 below; findings 5–8 are optional.

The probes are in `/Users/ataylor/.kiro/crew/scratch/runtime-a7ac9770/council-m2/probes-claude-opus-5.5/`. All of them use in-process `httpx.MockTransport` or respx, and every credential is made up. Run each with `uv run python <file>` from the repository root. To run the mutations: `MUT=<name> PYTHONPATH=<probe dir> uv run pytest -p mutplugin …`. The full suite at `9199ad8` gave `1052 passed`, and I modified nothing in the repository.

## Findings

**1. should-fix: `src/axis_cam/client.py:477-480` (and `:504-506`). The refusal raises `AxisDeviceError`, and 16 of 26 modules turn it into a default model that the MCP server reports as `ok`.**

- **What is wrong:** about 30 module methods already catch `AxisDeviceError` and return a default object, for example `network.py:60` and `oauth.py:54`. The new refusal raises that same class, so those methods catch it too. `discover_apis` also catches it and caches `{}`, so `list_modules` then reports every module as advertised.
- **Why it matters:** decision D1's reason for refusing was "return what the device sent, or fail loudly". For most modules that does not happen. `read_module`'s own contract says "`status` says whether the value is real". Instead it reports a made-up `enabled: false` for OAuth as real data.
- **Demonstrated:**
  - `p3_paths.py`: `returned a model, no error (16): action:ActionConfig, … network:NetworkConfig, … oauth:OAuthConfig, … virtualhost:VirtualHostConfig`
  - `p5_mcp.py`: `read_module oauth    status='ok' reason='None' value={"enabled": false, "credentials": [] …`
  - The proposed test (question 4) gives `16 failed, 10 passed` today.
- **Fix:** add `class AxisEchoError(AxisConnectionError)` and raise it from the refusal.
  - `audit._read` already re-raises `AxisConnectionError`, `read_module` would report `error`, and fleet would show an error row.
  - With this fix patched in (`PROBE_FIX=1`): `26 passed`.
  - Existing suites with the patch: `1 failed, 166 passed`. The one failure is `test_restore::…success_reply_is_refused`, which asserts the old class and only needs updating.

**2. should-fix: `src/axis_cam/api/logs.py:238,263` with `client.py:347`. An echoed reply reaches `axis-cam logs all` output.**

- **What is wrong:** `get_server_report` uses `get_raw`, which does not scan replies. If the body is not a tar archive, `get_log_files` decodes it as text, and every line it cannot parse is kept as a log entry.
- **Why it matters:** this is exactly the echo-to-output path the milestone exists to close. It is reached through the binary-download exemption.
- **Demonstrated:** `entries carrying the Basic token: 1 -> ['authorization: Basic cm9vdDpQcm9iZS1Qd35+fj94OSE=']`.
- **Fix:** in `_check_response`, scan the reply when its `Content-Type` is `text/*`, `application/json` or `application/xml`, even when `scan_reply=False`. A tarball or JPEG is never text; an echo page always is.
- **Demonstrated (fix patched in):** `refused: AxisDeviceError Refused the reply from 192.0.2.10 to /axis-cgi/serverreport.cgi`.

**3. should-fix: `src/axis_cam/cli/backup.py:350`. Restore prints the credential it just wrote.**

- **What is wrong:** with `--include-secrets`, the results table prints `result.change.target` for every parameter.
- **Why it matters:** the plan view (`:247`) says `(credential, value not shown)`, and D5 withholds the read-back value. The same table then prints the value in clear, which defeats D5.
- **Demonstrated:** `root.SNMP.ReadCommunity zq-rotated-9Xk verified` (`test_p5_restore_table.py`).
- **Fix:** print `"(credential)" if is_secret_name(result.change.name) else result.change.target`.

**4. should-fix (tests): two defences have no test pinning them.**

- **What is wrong:** you can remove the HTML-entity decoding, or move the `_token_windows` start later, and every test still passes.
- **Why it matters:** claim 2 is not proven.
- **Demonstrated (mutations):** `no-html-entities 144 passed`, `windows-start+1 144 passed`, `windows-start+2 144 passed`, `windows-start-1 1 failed`.
- **Demonstrated (consequence, `p4_boundary.py`):** with `start+2`, 4 password bytes pass through: `as shipped : x [redacted] y` / `start+2    : x dDpVbml0 y`.
- **Fix:**
  - Add `TOKEN.replace("/", "&#x2F;").replace("+", "&#43;")` to the spelling parametrize.
  - Add an oracle test: for each username in `["", "a", "root", "admin", "jöhn", "用户"]` and each password with 4 or more bytes, every 8-character window that fully covers 4 or more password bytes (computed from bit offsets) must be redacted when echoed alone.

**5. nit: `src/axis_cam/secrets.py:79`. Some spellings are not decoded.**

- **What is wrong:** the decoder does not handle HTML5 named entities (`&plus;`, `&sol;`, `&equals;`) or double URL-encoding. For a token where every password window contains `+` or `/`, the whole token survives.
- **Demonstrated:** `excerpt='<p>cm9vdDp&plus;MT9&plus;fkFBfj9&plus;</p>' … contains the token: True`. The same happens with `%252B`.
- **Reasoned:** PHP's `htmlentities(…, ENT_HTML5)` produces these entities.
- **Fix:** match any named entity with `&[A-Za-z][A-Za-z0-9]{1,31};` and decode it with `html.unescape`. Record double encoding as a stated limit.

**6. nit: `secrets.py:214-217`. Two edge cases in `_token_windows`.**

- **Short passwords:** for passwords under 4 bytes it still emits windows that cover fewer than 4 password bytes. Demonstrated: `user='abc' pw='abc' … extra=['OmFiYw==', 'jOmFiYw=']`. Fix: return `{token}` when the password has fewer than 4 bytes.
- **`:` in the username:** RFC 7617 forbids this and Axis names cannot contain it, but httpx accepts it. It moves the boundary and garbles another credential of the same user. Demonstrated: `GARBLED 'value=c3Z[redacted]PdGhlci1WYWx1ZS0wMA=='`. Document it.

**7. nit: refusing a reused password stored in base64 depends on the username length modulo 3.**

- **Demonstrated (`p2`):** `user='user' (len%3=1) -> refused=True`, `user='admin' (len%3=2) -> refused=False`, and the same password stored plain gives `refused= False`.
- **Why it matters:** the decision exempts plain-text password reuse from refusal, but this form of reuse is refused, and only for some usernames.
- **Reasoned:** I know of no Axis parameter that stores base64 credentials.
- **Fix:** add a line to the stated limits.

**8. nit: `secrets.py:84`. The header-dump rule fires on an ordinary JSON key.**

- **Demonstrated:** `'{"error": {"authorization": "insufficient scope"}}'` gives `[50 characters withheld …]`.
- **Fix:** require a scheme after the separator, e.g. `[:=]\s*["']?(?:basic|digest|bearer)\b`.

## Answers

**Question 1: is `secrets.py` correct? Yes, apart from findings 5 and 6.**
- `_View.original` fuzz: `mismatches: 0 / 20000`. Spans that start on, end on, or sit next to an escape map to whole escapes (`'%41[redacted]%42'`, `'[redacted]%3D%3Dz'`).
- `_merge`: `[(0, 8), (10, 21)]`. Overlapping spans merge, and adjacent ones become a single marker.
- `_token_windows`: matches the brute-force oracle exactly for every password of 4 bytes or more. That includes empty, multibyte and CJK usernames and passwords containing `:`. All 12 mismatches are passwords under 4 bytes.
- Padding: whole, unpadded, last-8-unpadded and `%3D` spellings are all redacted.
- The `\ufffd` branch is reachable for code points that `html.unescape` turns into `''` (for example `&#1;`), and it keeps the 1:1 mapping, which is correct. No accepted entity decodes to more than one character.
- Digest: quoted, unquoted, spaced and upper-case hex are all parsed. `RESPONSE=` is not, but httpx only emits lower case. A `response=` inside `uri` only adds a harmless extra needle.

**Question 2: false positives? Recommended answer: negligible on real device data.**
- 3,000 random credentials against a realistic 1,500-line listing (MACs, SHA-256 values, base64, PEM): `basic 0/3000, digest 0/3000`.
- Expected rate: about 17 windows × 2.3 MB × 64⁻⁸ ≈ 1.4×10⁻⁷ refusals per reply. Hex matches use the per-request hash, so there is no recurring false positive. MAC addresses and serials happen to be 12 hex characters, but matching one still needs the 12-hex odds.
- Worst realistic refusal case: finding 7.
- Garbling only affects error text, through the plain password, which D2 accepted: `pw='admin' -> '/axis-cgi/[redacted]/param.cgi'`.
- Cost per 2.3 MB: 27–40 ms for a listing, 114 ms for entity-dense XML, 216 ms for a pathological all-`%41` body. That is acceptable.

**Question 3: missed paths? Yes, two:** the log tarball (finding 2) and the restore table (finding 3). Finding 1 is a correctness problem rather than a leak.

These paths are clean:
- `get_json`: replies are scanned before parsing, and the JSON error message does not quote the body.
- Pydantic validation errors: they only see replies that passed the scan. The MCP SDK hides crash text from the client (`base.py:156-161`), so the only remaining case is the stated plain-password limit.
- Audit, report and fleet: they only `str()` library messages, which are now clean. F7 is already filed.
- `deps.opened` and `write.py:290` scrub their output.
- 401/403 messages are fixed text.
- Transport errors carry no body.
- httpx INFO logs show the URL only (F6, filed). The wire test captures DEBUG-level logs and asserts nothing leaks.

**Question 4: do the tests prove claims 1–5?** Claims 3, 4 and 5 are proven. Claims 1 and 2 are not fully:
- the HTML-entity decoding and the window boundary can be removed without any test failing (finding 4);
- nothing tests that binary downloads are skipped (reasoned);
- the 2xx refusal is only exercised on GET `param.cgi`.

The single most valuable missing test is below, for `tests/test_mcp_secrets_wire.py`. It uses that file's `config_dir`, `HOST`, `REALM` and `BASIC_TOKEN`. It fails 16 of 26 cases today and passes all 26 with the fix from finding 1:

```python
def _echo_everything(request: httpx.Request) -> httpx.Response:
    """A proxy that reflects the request into every 200 (not only param.cgi)."""
    if request.headers.get("Authorization") != f"Basic {BASIC_TOKEN}":
        return httpx.Response(401, headers={"WWW-Authenticate": f'Basic realm="{REALM}"'})
    lines = "".join(f"{k}: {v}\n" for k, v in request.headers.items())
    return httpx.Response(200, text=f"{request.method} {request.url.path}\n{lines}")


@pytest.mark.parametrize("module", resource_module_names())
async def test_a_peer_echoing_every_reply_never_reads_as_ok(module, config_dir, tmp_path):
    server = build_server(ConfigResolver(), backup_root=tmp_path / "backups")
    with respx.mock(assert_all_called=False) as router:
        router.route(host=HOST).mock(side_effect=_echo_everything)
        async with Client(server) as client:
            result = await client.call_tool("read_module", {"device": "cam", "module": module})
    status = (result.structured_content or {}).get("status")
    assert result.is_error or status != "ok", result.structured_content
```

**Question 5: design.**
- **Simpler alternative:** for error bodies, withhold the whole body when `quotes_sent_auth` (plus the plain-password match) fires, instead of redacting spans. That removes the position mapping (`_View.original`), `_merge` and span replacement. It gives a stronger guarantee: no residue around markers and no sub-8-character leftovers. Requirement R3 is unaffected, because genuine Axis text never quotes the request's credentials. This is not the "drop all peer text" option that D2 rejected. I'd do it as a follow-up; the current code is demonstrably correct.
- **Refuse or degrade?** Refusing is right, but the current exception class is wrong (finding 1).
  - Today the audit gives `unknown: 32`, each saying "the device did not answer this API (Refused the reply …)". That is honest but mislabelled.
  - `read_module` gives `ok` with made-up defaults for 16 modules, which is wrong.
  - Degrading each module to "unreadable" would blame one API for a problem with the whole path to the device.
  - Recommended: `AxisEchoError(AxisConnectionError)`, so the audit aborts with the reason and fleet shows one error row per device.

## Checked and found correct

- Header replaced whole first, then spans worked out on a fresh view of the text.
- AUTO mode's configured token is always a needle (test plus wire `replay` mode).
- Redaction happens before the cut in `error_excerpt` and `onvif_users._call`. Fault reasons are redacted before parsing.
- `ParamAPI.set` checks `OK` before any redaction, and short secret values keep the refusal readable.
- `restore` withholds the read-back value of a credential.
- 401/403/400-plain-HTTP messages never quote the body. `_path_of` uses the path only, not the query.
- `get_raw` was rewritten with the same error semantics as before.
- The full suite passes (1052) and the 60 secrets tests pass.

The MCP servers @mochi:mochi, playwright-mcp, kirocrew-core, session-db, kirocrew-computer, time, kirocrew-cron, auto-improvement and studyloop (plus 2 more) were not available in this seat; the review did not need them.
