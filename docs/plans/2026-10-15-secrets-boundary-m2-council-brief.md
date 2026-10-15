# Council brief: secrets boundary, milestone 2 (implementation review)

**Line 1 of your answer must state which model you are.** It is a signal, not the record.

## Your role

You are one of three independent reviewers from different model families. You do not see
the other reviewers' answers. A coordinator reconciles them by argument and re-runs every
claim marked "demonstrated", so a finding you cannot show with a probe or a test is worth
less than one you can.

This is a **defensive** change in a personal home-network tool (`axis_cam`, Python 3.12,
for Axis cameras the owner runs at home). It keeps HTTP credentials out of exception
messages and MCP output when something between the client and the camera echoes requests.

Rules:

- **Read-only on the repository** at `/Users/ataylor/code/personal/network/axiscam`: do not
  edit, create or delete files in it, and run no git command that changes state (no
  checkout, stash, reset, commit).
- **No network.** Contact no host.
- You **may** run tests and write probe scripts under
  `/Users/ataylor/.kiro/crew/scratch/runtime-a7ac9770/council-m2/probes-<your-model>/`:

  ```bash
  cd /Users/ataylor/code/personal/network/axiscam
  export TMPDIR="$(getconf DARWIN_USER_TEMP_DIR)"
  uv run pytest -q -p no:cacheprovider -o addopts="" tests/test_secrets.py tests/test_mcp_secrets_wire.py
  uv run python /Users/ataylor/.kiro/crew/scratch/runtime-a7ac9770/council-m2/probes-<model>/probe.py
  ```

- Use only made-up credentials in probes. Say which findings you **demonstrated** (quote the
  output) and which you **reasoned**.

## The artefact

The change is commit `9199ad8` on branch `secrets-boundary` (the working tree is that
commit). Review it with `git --no-pager show 9199ad8 --stat` and
`git --no-pager diff 29d4b7c 9199ad8 -- src tests`. The core is `src/axis_cam/secrets.py`.

Background you should read first (authoritative for scope):

- `docs/plans/2026-10-15-secrets-boundary-decision.md`: what the milestone-1 council
  decided (D1–D5), the stated limits, and what was filed rather than fixed (F6, F7).
- The milestone-1 seats are under `docs/plans/council/2026-10-15-secrets-m1-seat-*.md` if
  you want the reasoning behind a decision. Do not re-argue a decision unless the
  implementation shows it was wrong.

## What the implementation claims

1. `quotes_sent_auth(text, response, username=, password=)`: true when a reply contains the
   request's `Authorization` value, or a fragment of a Basic token or Digest `response` hash,
   in any common spelling. `VapixClient._check_response` refuses any reply below 400 for
   which this is true, except binary downloads (`get_raw`, `get_binary`).
2. `redact_sent_auth`: replaces the header whole, then every span covered by such a
   fragment, and the configured plain password (4+ characters) whole.
   - **Spellings:** `_View` undoes `%XX`, `\uXXXX`, `\/` and HTML entities, maps decoded
     positions back to the original text, and folds base64url onto base64.
   - **Fragments:** 8 base64 characters, starting where the window covers at least 4 bytes
     of the password (`_token_windows`); 12 hex characters of a hash, case-insensitive.
3. `error_excerpt`: withholds a body that dumps request headers; otherwise
   redact-then-cut. Used at `client.py` (4xx/5xx) and `api/onvif_users.py` (SOAP).
4. The configured Basic token is always a needle (AUTO mode's earlier Basic attempt).
5. `ParamAPI.set` (`api/param.py`, `_withhold_value`) and `restore.apply_param_restore`
   read-back.
6. Performance: the coordinator measured about 60–70 ms per 2.3 MB reply.

Gate at `9199ad8`: 1052 tests pass, coverage 78.35 % (floor 75), ruff clean, pyright
0 errors / 145 warnings (the project baseline). The coordinator mutation-checked five
defences (decoding, the configured token, the 2xx refusal, the header-dump withhold,
base64url folding): removing each turns its test red.

## Questions — answer every one

1. **Correctness of `secrets.py`.** Find inputs where it is wrong, especially:
   - `_View.original()` with spans that start or end on an escape, or next to one;
   - overlapping and adjacent spans in `_merge`;
   - the `_token_windows` start arithmetic for different username lengths, including
     empty and multi-byte usernames, and passwords containing `:`;
   - padding handling;
   - `\ufffd` for multi-character entities;
   - Digest headers with quoted or unquoted `response`.

   Demonstrate with probes.
2. **False positives.** Is there genuine Axis device data, or ordinary text, that makes
   `quotes_sent_auth` refuse a legitimate reply (which would break reads of a real device)
   or makes `redact_sent_auth` garble a legitimate error message? Think about parameter
   listings (about 1,500 lines), certificates, logs, base64 in parameter values, and hex
   (MAC addresses, fingerprints, serials). Estimate the rates and demonstrate the worst
   case you can construct from realistic data.
3. **Missed paths.** Is there any path where device text still reaches an exception
   message, log record or MCP output without going through these functions? Examples to
   check: `get_json` and pydantic validation errors, `discover_apis`, `logs.py`, audit,
   report, fleet, the MCP `deps.opened` scrubber, httpx's own logging.
4. **Tests.** Do `tests/test_secrets.py` and `tests/test_mcp_secrets_wire.py` actually prove
   claims 1–5? Name the single most valuable missing test, with its code.
5. **Design.** Anything simpler that gives the same guarantee? Is a 2xx refusal the right
   behaviour for a *read* tool (a fleet audit), or should it degrade to "unreadable"? Check
   what `audit.py` and the MCP `read_module` actually do with the refusal.
6. **Verdict.** `COMMIT` (merge the branch into `main` as is), `COMMIT-WITH-CHANGES` (list
   exactly which) or `DO-NOT-COMMIT` (what blocks it).

## Output shape (must deliver all of it)

1. Line 1: which model you are.
2. Verdict in one line.
3. Findings, numbered, each with: severity (`blocker` / `should-fix` / `nit`), `file:line`,
   what is wrong, why it matters, the fix, and **demonstrated** (quote output) or
   **reasoned**.
4. Answers to questions 1–5, each with a recommended answer.
5. What you checked and found correct, one line each.

Keep it under about 2,000 words. Do not restate the brief.
