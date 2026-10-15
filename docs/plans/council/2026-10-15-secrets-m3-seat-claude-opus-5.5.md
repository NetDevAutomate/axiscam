Now the diff.Probe 1: tools/list schema identity across 9199ad8 and f44827e.Model: claude-opus-5.5 (Anthropic)

**Verdict: MERGE.** Nothing blocks the merge. Findings 1–3 should be fixed as follow-ups. Findings 1 and 2 are real holes in D6/D8, but both need a peer that actively picks a redirect or a non-text content type, and neither is worse than `29d4b7c`.

Probes are in `/Users/ataylor/.kiro/crew/scratch/runtime-a7ac9770/council-m3/probes-claude-opus-5.5/`. All use respx and made-up credentials. Run them from `/Users/ataylor/code/personal/network/axiscam` with `uv run python <probe>`. For the old trees, add `PYTHONPATH=<probe dir>/old9199/src` (or `old29d4`), which were extracted with `git archive`. Mutations: `MUT=<name> PYTHONPATH=<probe dir> uv run pytest -p mutplugin …`. I changed nothing in the repository.

## Findings

**1. should-fix: `src/axis_cam/client.py:157,458,462,480`. A redirect that quotes the credentials is followed, not refused, and the URL path is then quoted.**
- **What is wrong:** `follow_redirects=True`, and `_check_response` scans only the final body. A 302 whose `Location` carries the token is itself a reply that quotes the credentials, which D6 says must be refused. Instead:
  - the new `AxisEchoError` message quotes the path, which contradicts `exceptions.py:56` ("The message never quotes the reply");
  - so does the existing 403 message;
  - httpx's INFO request log records the URL;
  - the MCP `Scrubber` removes the whole token but not a fragment.
- **Demonstrated (`p2_redirect_path.py`):**
  - `AxisEchoError: "Refused the reply from 192.0.2.10 to /r/cm9vdDpQcm9iZS1SZWRpcn45eFEh/x (HTTP 200)…"`
  - `AxisPermissionError: '…may not use /r/dDpQcm9iZS1SZWRp/x (403).' … after MCP Scrubber: True`
  - `INFO:httpx:HTTP Request: GET https://192.0.2.10/r/cm9vdDpQcm9iZS1SZWRpcn45eFEh/x "HTTP/1.1 403 Forbidden"`
  - `29d4b7c` gives the same 403 output, so the 403 case predates the branch.
- **Fix:**
  - Add an httpx `response` event hook that raises `AxisEchoError` when a 3xx `Location` passes `quotes_sent_auth`. The hook runs before httpx follows the redirect or logs the next URL.
  - In messages, quote the path the caller passed, not `response.url.path`.

**2. should-fix: `src/axis_cam/api/logs.py:272`, `client.py:44,499`. A Digest credential in a non-text server-report download reaches the log entries.**
- **What is wrong:** `get_raw` skips the scan unless the reply says it is text. `refuse_echo` gets no response object, so it knows only the configured Basic token. Digest is what AUTO mode uses over HTTP. `_TEXT_TYPES` also misses `message/http`, the standard echo (TRACE) content type.
- **Demonstrated (`p3_digest_serverreport.py`, `LogsAPI.get_logs(LogType.ALL)`):**
  - `application/octet-stream -> accepted, scheme=digest … entry: response="bac71213cb8a44c6baeb0453bdde7f84"`
  - `message/http -> accepted`
  - Control: `text/plain -> AxisEchoError`
- **Fix:**
  - Keep the `httpx.Response` for the download (for example a `get_raw` variant that returns it) and call `quotes_sent_auth(text, response, …)` on each decoded file.
  - Add `message/` to `_TEXT_TYPES`.

**3. should-fix (tests): `src/axis_cam/mcp_server/deps.py:85-94`. The sync branch of `contained` is not covered by any test.**
- **What is wrong:** three tools are sync (`list_devices`, `backup_list`, `backup_verify`), and no test exercises their crash path.
- **Demonstrated:**
  - Mutation `sync-unwrapped`: `1133 passed`.
  - Under that mutation, `p4_contained.py` gives `canary in logs: True | Traceback in logs: True`. The shipped code gives `False | False`.
- **Fix:** add a test where `backup_list` reads a malformed manifest whose text quotes a canary, then assert the canary is absent from the wire, `caplog` and stderr.

**4. nit: `client.py:304,331`. What gets scanned is not what gets parsed.**
- **What is wrong:** the scan reads `response.text` (UTF-8 unless the header says otherwise). `response.json()` parses the raw bytes, and `json.loads` detects UTF-16/32 on its own.
- **Demonstrated (`p5_parse_view.py`):** a UTF-16 JSON echo with no charset gives `get_json accepted: {… 'authorization': 'Basic cm9vdDpQcm9iZS1VdGYxNn54USE='} | token in data: True`. The same happens at `9199ad8`.
- **Context:** only a deliberately re-encoding peer does this, which is already a stated limit.
- **Fix:** `json.loads(response.text.removeprefix("\ufeff"))`. The parser then reads exactly the string that was scanned.

**5. nit: `client.py:567`. `check_connectivity` turns `AxisEchoError` into `False`.**
- **Demonstrated (`p5`):** `check_connectivity on an echoing peer: False`. At `9199ad8` the same call raised; at `29d4b7c` it returned `True`.
- **Impact:** there is no caller in `src`.
- **Fix:** re-raise `AxisEchoError`, or document that `False` covers it.

**6. nit: `src/axis_cam/api/onvif_users.py:299-303`. When a genuine SOAP fault contains the configured password, the fault structure is lost, not just the wording.**
- **Demonstrated (`p8_onvif_fault.py`):** with the password `2003`, which appears in the SOAP 1.2 namespace URL:
  - now: `AxisUserError: … [485 characters withheld…]`
  - `29d4b7c`: `AxisSoapFault: … (ter:UsernameClash)`
- **Fix:** parse the fault first and withhold only `reason`. Correct the stated limit, which says only the device's wording is lost.

**7. nit: `src/axis_cam/secrets.py:221-231`. One password spelling is missed.**
- **What is wrong:** UTF-8 percent-encoding with lower-case hex, for a non-ASCII password, is not recognised.
- **Demonstrated (`p7_spellings.py`):** `quote lower hex withheld=False`. Every other spelling I tried was withheld.
- **Fix:** add lower-cased `quote` variants to the spelling set.

**8. nit, pre-existing: `src/axis_cam/mcp_server/tools/write.py:153-179`.**
- **What is wrong:** the `confirm_plan` resolver and the SDK's output conversion run outside `contained`, so a crash there is still logged with its traceback. The `describe_plan` elicitation text is not passed through the `Scrubber`.
- **Reasoned:** nothing device-secret is reachable today, because secret parameters are already `REDACTED` in the payload.
- **Fix:** wrap resolvers with `contained` and scrub `describe_plan`'s output.

**9. nit, pre-existing: `api/users.py:99`, `api/param.py:63,154`, `api/time.py:106`.** These in-band 2xx error sinks quote device text uncut and never call `error_excerpt` (reasoned). They sit outside D2's two sinks. Fix: route them through `error_excerpt`.

## Answers

**Q1: Is D6 implemented without a hole? Nearly, with three exceptions.**
- **Main path:** all seven request methods call `_check_response`, and there is no other httpx client in `src`. The scan runs before every status branch.
- **Callers:** module fallbacks do not swallow the refusal; mutation `echo-is-device-error` gives `24 failed`.
  - `discover_apis` propagates it and caches nothing.
  - The audit re-raises it.
  - Fleet shows one error row.
  - Report, backup and restore propagate it.
  - `read_module` reports `status="error"`.
  - The CLI exits 1.
- **Holes:**
  - the redirect `Location` (F1);
  - non-text downloads combined with Digest (F2);
  - the scan view differing from the parse view (F4, stated-limit adjacent).
- **"Absent" or "unreadable":** the only place that turns the refusal into either is `check_connectivity` (F5), and nothing in `src` calls it.

**Q2: Is D7 correct? Yes.**
- **Demonstrated (`p1_tools_list.py`):**
  - `tools/list` is identical at `9199ad8` and `f44827e`: `wire identical: True`, `meta identical: True`.
  - The 13 tools keep their form: 3 sync and 10 async.
  - `apply_plan` keeps its resolver parameter `['answer']`.
- **Demonstrated (`p4`):**
  - `ToolError` text is kept: `'kept: P4-Canary~S3cret!'`.
  - `MCPError` passes through unchanged.
  - A crash becomes `internal error: <Class>` with `cause=None`, and the SDK logs one INFO line.
- **Remaining text paths:** the 403 path quoting from F1, plus the resolver and output-conversion paths in F8.

**Q3: Regressions for a genuine device? None that matters.**
- **Speed:** the scan costs about 30 ms per MB. That is 845 ms for a 26 MB escape-dense log through `refuse_echo` and 161 ms for a 5 MB `text/plain` download (`p6_timing.py`). Both are small next to the download itself.
- **Refusals:** my probes refused no genuine-looking reply.
- **Small losses:**
  - the ONVIF fault class when the password appears in the fault XML (F6);
  - `check_connectivity`'s changed meaning (F5);
  - server logs no longer show tracebacks for genuine tool bugs, which D7 does on purpose. Optionally log the traceback frames without the message at DEBUG.
- **Exception type:** the echo refusal changed from `AxisDeviceError` to `AxisEchoError`. It only fires on an echo, and no `src` caller relied on the old class.

## Checked and found correct

- Full suite: `1133 passed in 8.68s`. `ruff check` and `ruff format --check` are clean.
- The `contained` wrapper keeps the tools' signatures; mutation `no-wraps` gives `52 failed`.
- Mutations that each turn tests red: `async-unwrapped` (1), `no-text-scan` (1), `refuse-echo-noop` (2), `excerpt-ignores-password` (1), `onvif-no-withhold` (1), `scan-2xx-only` (14).
- A sync tool crash: at `9199ad8` the canary and a traceback reached the logs; now one line with neither (`p4_out_9199.txt` against `p4_out.txt`).
- A 404 echo page is refused without its body being quoted; a genuine 404 message does not quote the path.
- Downloads that say they are text are scanned with the full request (test, and the `p3` text/plain control).
- D8 spellings are refused: double and triple `%`, `&plus;`/`&sol;`, lower-case `&#x2b;`, `&amp;#43;`.
- Passwords under 4 bytes give no windows; `abcd` gives exactly `['dTphYmNk']`.
- The Digest regex ignores case.
- `error_excerpt` checks for the password before cutting, and the ONVIF path withholds the whole excerpt.
- The `backup restore` table prints `(credential, value not shown)`.

These MCP servers were unavailable in this seat: @mochi:mochi, time, kirocrew-core, kirocrew-computer, session-db, auto-improvement, context-mode, studyloop, playwright-mcp, plus 2 more. The review did not need any of them.
