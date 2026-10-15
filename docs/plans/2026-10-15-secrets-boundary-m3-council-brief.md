# Council brief: secrets boundary, milestone 3 (merge review)

**Line 1 of your answer must state which model you are.**

## Your role

You are one of two independent reviewers from different labs. This is the last review
before the branch `secrets-boundary` is merged into `main` in a personal home-network tool
(`axis_cam`, Python 3.12, for Axis cameras the owner runs at home). The change is
**defensive**: it keeps HTTP credentials out of exception messages, logs and MCP output when
something between the client and the camera echoes requests.

Rules:

- **Read-only on the repository** at `/Users/ataylor/code/personal/network/axiscam`. Do not
  edit, create or delete files in it, and run no state-changing git command.
- **No network.**
- You **may** run tests and write probes under
  `/Users/ataylor/.kiro/crew/scratch/runtime-a7ac9770/council-m3/probes-<your-model>/`. Use
  only made-up credentials.

  ```bash
  cd /Users/ataylor/code/personal/network/axiscam
  export TMPDIR="$(getconf DARWIN_USER_TEMP_DIR)"
  uv run pytest -q -p no:cacheprovider -o addopts=""
  ```

- Say which findings you **demonstrated** (quote output) and which you **reasoned**.

## What to review

The milestone-3 commit `f44827e` (the working tree is that commit):

```bash
git --no-pager diff 9199ad8 f44827e -- src tests
```

It implements decisions D6–D8 in `docs/plans/2026-10-15-secrets-boundary-decision.md`
(section "Milestone 2"), which answer the milestone-2 council. Read that section first. The
milestone-2 seats are under `docs/plans/council/2026-10-15-secrets-m2-seat-*.md`. The decisions
are settled: review whether the code **implements them correctly**, not whether they are right,
unless the code shows a decision cannot work.

In short:

- **D6.** Any reply that quotes the request's credentials is refused, whatever its status, with
  `AxisEchoError(AxisConnectionError)` (`client.py` `_check_response`, `refuse_echo`).
  `secrets.py` is now detection only (`quotes_sent_auth`, `contains_password`,
  `error_excerpt`, `token_windows`).
- **D7.** Every MCP tool is wrapped (`mcp_server/deps.py` `contained`): an unexpected exception
  becomes `ToolError("internal error: <Class>")` raised from `None`.
- **D8.** Content-type scanning of binary downloads, the `logs.get_log_files` decoded-text check,
  the `cli/backup.py` restore table, entity and double-URL decoding, short passwords, the Digest
  regex, and the plain-password spellings.

Gate at `f44827e`: 1133 tests pass, coverage 78.57 % (floor 75), ruff clean, pyright 0 errors /
145 warnings (the baseline). Ten mutations were checked, and each one turns a test red.

## Questions

1. **Is D6 implemented without a hole?** Is there any path where a reply reaches parsing,
   quoting, logging or MCP output without passing `_check_response`'s scan? Consider every
   `VapixClient` method, `post_raw`, `get_raw`/`get_binary` with and without a text content
   type, `discover_apis`, and any place that catches `AxisConnectionError` or `AxisError` and
   carries on (`check_connectivity`, `fleet`, the CLI). Does any caller turn `AxisEchoError`
   into "absent" or "unreadable" and continue as though nothing happened?
2. **Is D7 correct?** Does the wrapper preserve every tool's schema, its sync or async form,
   the elicitation resolvers on `apply_plan`, `ToolError` text and `MCPError`? Is there a tool
   path where an exception's text still reaches a log or the client?
3. **Regressions.** Does anything behave worse for a *genuine* device than at `29d4b7c`
   (before this branch)? For example: a legitimate reply refused, an error message less
   useful, a slowdown that matters, or a changed exception type that a caller relied on.
4. **Verdict.** `MERGE` or `BLOCK`, with exactly what blocks it. Non-blocking findings can be
   listed as follow-ups.

## Output shape

1. Line 1: which model you are.
2. Verdict in one line.
3. Findings, numbered: severity (`blocker` / `should-fix` / `nit`), `file:line`, what is wrong,
   the fix, demonstrated or reasoned.
4. Answers to questions 1–3.
5. What you checked and found correct, one line each.

Keep it under about 1,500 words.
