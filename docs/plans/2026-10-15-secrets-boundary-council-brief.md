# Council brief: keeping sent credentials out of error text (milestone 1)

**Line 1 of your answer must state which model you are.** It is a signal, not the record.

## Your role

You are one of four independent reviewers from different model families. You do not see
the other reviewers' answers and they do not see yours. A coordinator will reconcile the
four answers by argument, checking every factual claim against the source, so a claim you
cannot point to in the code is worth less than no claim.

This is a review of a **defensive** change in a personal, MIT-style home-network tool
(`axis_cam`, a Python 3.12 library + CLI + MCP server for Axis network cameras the owner
runs at home). The change keeps HTTP credentials out of exception messages and MCP output.

Rules for this review:

- **Read-only on the repository** at `/Users/ataylor/code/personal/network/axiscam`. Do
  not edit, create or delete any file in it, and run no git command that changes state.
- **No network.** Do not contact any host or device. Everything you need is local.
- You **may** run targeted tests, and you may write throwaway probe scripts that import
  `axis_cam` under `$KIROCREW_SCRATCH/council-m1/probes-<your-model>/` to check a claim
  with data. The test command (sqlite needs this TMPDIR on this Mac):

  ```bash
  cd /Users/ataylor/code/personal/network/axiscam
  export TMPDIR="$(getconf DARWIN_USER_TEMP_DIR)"
  uv run pytest -q -p no:cacheprovider -o addopts="" tests/test_secrets.py
  ```

  For a probe: `uv run python $KIROCREW_SCRATCH/council-m1/probes-<model>/probe.py`.
- Prefer a finding you **demonstrated** (a probe or test output you quote) over one you
  reasoned about. Say which kind each finding is.

## The artefact

Frozen snapshot (the repo may move on while you work; review the snapshot):

- `$KIROCREW_SCRATCH/council-m1/tracked.diff` — the change to tracked files, against
  commit in `$KIROCREW_SCRATCH/council-m1/BASE_SHA`.
- `$KIROCREW_SCRATCH/council-m1/test_secrets.py` — new unit tests for the helper.
- `$KIROCREW_SCRATCH/council-m1/test_mcp_secrets_wire.py` — new end-to-end test: the MCP
  server over the real HTTP stack (config file → client → `httpx` → `respx` mock device),
  asserting no credential reaches any tool output, resource, log or stderr.

The rest of the repository is context; read whatever you need.

## What was found, and what the change does

The new end-to-end test found one real gap. The library embeds a **truncated** snippet of
device text in error messages, e.g. `client.py:431` (`body[:200]`). A device never echoes
the request headers, but a misbehaving proxy or peer can. If the echoed `Authorization`
header straddles the cut, the message carries **half** of the base64 token. The MCP layer's
whole-string `Scrubber` (`src/axis_cam/mcp_server/redact.py:30`, built from username and
password at `mcp_server/deps.py:94`) cannot match half a token, so the fragment reached MCP
output. Digest has a second form of the same problem: the per-request `response` hash is not
a configured value at all, so no downstream scrubber knows it.

The change:

1. `src/axis_cam/secrets.py:57` — new `redact_sent_auth(text, response)`: reads the
   `Authorization` header from `response.request` and replaces the whole header value, the
   bare Basic token, and every Digest `response` hash with `[redacted]`. Returns the text
   unchanged when no request is attached (`httpx` raises `RuntimeError` from
   `Response.request` then) or for a `MagicMock` response.
2. Applied **before truncation** at `client.py:429` (generic 4xx/5xx) and
   `api/onvif_users.py:297` (SOAP faults: before `parse_fault`, so a fault `Reason` cannot
   carry the credential either).
3. Applied at the **source** in `api/base.py:153` and `:164` (`BaseAPI._get_text` /
   `_post_form`), so every legacy-CGI 200 body is redacted before any module parses it or
   quotes it in an error (`param.py:307/309`, `users.py:99`, `users.py:324`, logs).
4. `api/param.py:302` — `ParamAPI.set` replaces the sent value in the device's refusal
   text when the parameter name is credential-like (`is_secret_name`), because the device's
   `# Error: Error setting 'X' to '<value>'!` quotes the value and restore prints the error.
5. `REDACTED` moved into `axis_cam.secrets` and is shared with the MCP layer.

Gate on the snapshot: 1002 tests pass, coverage 77.98 % (floor 75), ruff clean, pyright
0 errors / 145 warnings (the baseline). Each new unit test was mutation-checked: removing
the behaviour it guards turns exactly that test red.

## Requirements (authoritative for scope)

- **R1.** No credential the client sent (Basic token, Digest `response` hash) and no
  configured password may appear, whole or as a fragment, in any library exception message
  or any MCP output (tools, resources, logs, stderr), including when a peer echoes the
  request headers.
- **R2.** Data paths stay faithful: what the device returns as data (parameters, account
  lists, logs, backups) must not be silently altered. *This is the coordinator's proposed
  requirement, and item 3 above may break it. Challenge it if it is wrong.*
- **R3.** Genuine Axis error text stays diagnosable (`param.cgi` refusals, SOAP fault codes).
- **R4.** No behaviour change for the suite's `MagicMock`-based unit tests.

## Questions — answer every one

1. **Source or sink.** Item 3 redacts in `BaseAPI._get_text` / `_post_form`, i.e. on the
   data path that also feeds `params export`, backups and restore's drift check. Is that
   acceptable under R2, or should redaction happen only where device text becomes an error
   message? If sink-only, name every sink in `src/axis_cam` that must be covered and how
   each gets the request it needs. Recommend one answer.
2. **Encoded echoes.** The helper matches the header and token literally. An echo may
   transform them: URL-encoding (`+`→`%2B`, `/`→`%2F`, `=`→`%3D`), JSON escaping of `/` as
   `\/`, HTML entities, header-name case, line folding. Which of these matter enough to
   handle, and how — wider matching, or not embedding raw device text in messages at all
   (status, content type and length only, or a sanitized excerpt)? Weigh R1 against R3.
3. **The value replacement in `ParamAPI.set`** (`param.py:302`) uses `str.replace(value,
   REDACTED)` over the whole body. What happens for short or common values (`"1"`,
   `"public"`, `"e"`)? Propose the exact replacement you would ship.
4. **Test adequacy.** Do the unit tests and the wire test prove R1 for both schemes? What
   case is missing? Is the wire test's fragment heuristic (`leaked()`: 8-character
   substrings, 12 for hex) the right bar — too strict, too loose?
5. **Regressions.** Anything in the diff that changes behaviour beyond the intent (typing,
   import cycles — `secrets.py` is now imported by `client.py` and `api/base.py` — the
   exception hierarchy, performance, the `MagicMock` paths)?
6. **Verdict.** `COMMIT`, `COMMIT-WITH-CHANGES` (list exactly which) or `DO-NOT-COMMIT`
   (say what blocks it), for a **local** commit on `main`.

## Output shape (must deliver all of it)

1. Line 1: which model you are.
2. Verdict (question 6) in one line.
3. Findings, numbered, each with: severity (`blocker` / `should-fix` / `nit`), `file:line`,
   what is wrong, why it matters, the fix, and whether you **demonstrated** it (quote the
   probe or test output) or **reasoned** it.
4. Answers to questions 1–5, each with a recommended answer and the reasoning.
5. Anything you checked and found correct (one line each), so agreement is visible too.

Keep it under about 2,000 words. Do not restate the brief.
