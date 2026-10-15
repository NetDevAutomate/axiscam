Model: gpt-5.6-sol
Verdict: BLOCK — Findings 1 and 2 must be fixed before merge.

## Findings

1. **blocker — `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/api/logs.py:253-273`, `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/client.py:488-502`**
   **Wrong:** `get_log_files()` extracts an octet-stream archive and calls `refuse_echo(text)` without the originating response. That detector can reconstruct Basic credentials but cannot know the request-specific Digest `response` hash. A valid tar containing the echoed Digest header therefore reaches parsed log output.
   **Fix:** preserve the `httpx.Response` alongside raw bytes for decoded-text consumers, accept it in `refuse_echo`, and call `quotes_sent_auth(text, response, ...)`. Add a forced-Digest tarball test.
   **Demonstrated:**
   > `digest_server_report accepted=True digest_hash_in_output=True`

2. **blocker — `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/mcp_server/deps.py:56-94`, `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/mcp_server/tools/write.py:167-176`, `/Users/ataylor/code/personal/network/axiscam/src/axis_cam/mcp_server/tools/write.py:251`**
   **Wrong:** `contained()` wraps the tool function, but `Resolve(confirm_plan)` executes before that function. An unexpected resolver exception bypasses containment and the MCP SDK logs its traceback and text. D7 therefore does not cover the complete `apply_plan` tool path.
   **Fix:** apply `contained()` to `confirm_plan` itself—or introduce an equivalent resolver wrapper—before passing it to `Resolve`. Preserve `ToolError` and `MCPError` as the existing wrapper does. Add a resolver-exception log-capture test.
   **Demonstrated:**
   > `resolver_boundary is_error=True canary_in_wire=False canary_in_logs=True traceback_in_logs=True wire='Error executing tool apply_plan'`

## Answers

**1. D6:** No, because Digest credentials embedded in decoded server-report files bypass the scan described in Finding 1. Other reviewed paths are correct: `get`/`post`, JSON parsing and `post_raw` scan before callers inspect bodies; text-labelled binary downloads scan; `discover_apis` catches only `AxisDeviceError`; module fallback handlers do not catch `AxisEchoError`; audit propagates it; fleet records an error row; and CLI handlers print only the safe refusal. `check_connectivity()` converts it to `False`, but that is fail-closed and does not continue with device data.

**2. D7:** The ordinary wrapper is correct but incomplete. It preserves signatures and coroutine form, converts unexpected tool-body exceptions to class-only `ToolError` raised from `None`, and explicitly preserves `ToolError`/`MCPError`. Existing elicitation flows and schemas still work. The uncovered pre-invocation resolver path blocks the security claim.

**3. Genuine-device regressions:** None found beyond the documented trade-offs: rare deterministic Basic-token collisions in base64 device data and loss of genuine error wording when it contains the configured password. Actual binary downloads remain unscanned unless text-labelled, avoiding material binary overhead. The new exception hierarchy correctly prevents unsupported-API fallbacks from treating echoes as absent.

## Checked and found correct

- Full suite: **1133 passed**; focused D6/D7/MCP/restore suite: **355 passed**.
- Ruff: **clean**. Pyright: **0 errors, 145 baseline warnings**.
- Normal containment probe: `signature_same=True async=True text='internal error: RuntimeError' cause=None`.
- Every registered module’s ordinary echo path, SOAP errors, restore result redaction, binary content-type checks and decoded Basic-log checks are covered and passing.
- No repository files were modified; status reports the existing untracked `/Users/ataylor/code/personal/network/axiscam/docs/plans/2026-10-15-secrets-boundary-m3-council-brief.md`.
- Unavailable MCP servers: `@mochi:mochi`; `playwright-mcp`, `kirocrew-core`, `time`, `home-assistant`, `studyloop`, `auto-improvement:auto-improvement`, `context-mode`, `kirocrew-cron`, and two unnamed servers reported by the runtime.

Probe saved for rerun:

```diff
--- /dev/null
+++ /Users/ataylor/.kiro/crew/scratch/runtime-a7ac9770/council-m3/probes-gpt-5.6-sol/probe_review.py
@@ -0,0 +1,156 @@
+"""Offline milestone-3 council probes; all credentials are made up."""
+
+from __future__ import annotations
+
+import asyncio
+import inspect
+import io
+import logging
+import re
+import sys
+import tarfile
+from pathlib import Path
+
+import httpx
+from mcp import Client
+from mcp.server.mcpserver.exceptions import ToolError
+
+from axis_cam.api.logs import LogsAPI
+from axis_cam.client import VapixClient
+from axis_cam.exceptions import AxisEchoError
+from axis_cam.mcp_server.deps import contained
+from axis_cam.mcp_server.plans import PlanStore
+from axis_cam.mcp_server.server import build_server
+
+sys.path.insert(0, str(Path.cwd() / "tests"))
+from mcp_fakes import two_cameras  # noqa: E402
+
+CANARY = "Probe-Only-N0t-A-Real-Secret!"
+
+
+class Human:
+    async def __call__(self, _context: object, _params: object) -> object:
+        raise AssertionError("elicitation callback must not be reached")
+
+
+class ExplodingStore(PlanStore):
+    def get(self, plan_id: str):  # type: ignore[no-untyped-def]
+        raise RuntimeError(f"resolver leaked {CANARY} for {plan_id}")
+
+
+class Capture(logging.Handler):
+    def __init__(self) -> None:
+        super().__init__()
+        self.lines: list[str] = []
+
+    def emit(self, record: logging.LogRecord) -> None:
+        self.lines.append(self.format(record))
+
+
+async def probe_resolver_boundary() -> None:
+    capture = Capture()
+    root = logging.getLogger()
+    root.addHandler(capture)
+    old_level = root.level
+    root.setLevel(logging.DEBUG)
+    try:
+        server = build_server(two_cameras(), plans=ExplodingStore())
+        async with Client(server, elicitation_callback=Human()) as client:
+            result = await client.call_tool("apply_plan", {"plan_id": "probe-plan"})
+    finally:
+        root.setLevel(old_level)
+        root.removeHandler(capture)
+    wire = "".join(getattr(item, "text", "") for item in result.content)
+    logs = "\n".join(capture.lines)
+    print(
+        "resolver_boundary",
+        f"is_error={result.is_error}",
+        f"canary_in_wire={CANARY in wire}",
+        f"canary_in_logs={CANARY in logs}",
+        f"traceback_in_logs={'Traceback' in logs}",
+        f"wire={wire!r}",
+    )
+
+
+async def probe_connectivity_swallow() -> None:
+    client = VapixClient("192.0.2.10", "probe", CANARY)
+
+    async def echo(_path: str) -> None:
+        raise AxisEchoError("safe refusal")
+
+    client.get = echo  # type: ignore[method-assign]
+    print("connectivity_echo", f"result={await client.check_connectivity()!r}")
+
+
+async def probe_wrapper() -> None:
+    async def target(value: str, enabled: bool = False) -> str:
+        raise RuntimeError(f"hidden {CANARY}")
+
+    wrapped = contained(target)
+    try:
+        await wrapped("x")
+    except ToolError as exc:
+        print(
+            "contained",
+            f"signature_same={inspect.signature(wrapped) == inspect.signature(target)}",
+            f"async={inspect.iscoroutinefunction(wrapped)}",
+            f"text={str(exc)!r}",
+            f"cause={exc.__cause__!r}",
+        )
+
+
+async def probe_digest_server_report() -> None:
+    seen: dict[str, str] = {}
+
+    def archive(text: str) -> bytes:
+        payload = text.encode()
+        output = io.BytesIO()
+        with tarfile.open(fileobj=output, mode="w") as tar:
+            info = tarfile.TarInfo("var/log/system.log")
+            info.size = len(payload)
+            tar.addfile(info, io.BytesIO(payload))
+        return output.getvalue()
+
+    def handler(request: httpx.Request) -> httpx.Response:
+        authorization = request.headers.get("Authorization", "")
+        if not authorization.startswith("Digest "):
+            return httpx.Response(
+                401,
+                headers={
+                    "WWW-Authenticate": 'Digest realm="probe", nonce="abc123", algorithm=MD5, qop="auth"'
+                },
+            )
+        seen["authorization"] = authorization
+        return httpx.Response(
+            200,
+            content=archive(f"authorization: {authorization}\n"),
+            headers={"Content-Type": "application/octet-stream"},
+        )
+
+    async with VapixClient(
+        "192.0.2.10", "probe", CANARY, port=443, use_https=True, auth_mode="digest"
+    ) as client:
+        assert client._client is not None and client._auth is not None
+        await client._client.aclose()
+        client._client = httpx.AsyncClient(
+            auth=client._auth, transport=httpx.MockTransport(handler), follow_redirects=True
+        )
+        files = await LogsAPI(client).get_log_files()
+    output = "\n".join(files.values())
+    digest = re.search(r'(?i)response="?([0-9a-f]+)', seen["authorization"]).group(1)  # type: ignore[union-attr]
+    print(
+        "digest_server_report",
+        "accepted=True",
+        f"digest_hash_in_output={digest in output}",
+    )
+
+
+async def main() -> None:
+    await probe_wrapper()
+    await probe_connectivity_swallow()
+    await probe_digest_server_report()
+    await probe_resolver_boundary()
+
+
+if __name__ == "__main__":
+    asyncio.run(main())
```
