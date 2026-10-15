"""MCP server over the ``axis_cam`` library (read, plan, and confirmed apply).

The server is a thin adapter: every tool composes library calls that already
exist (``read()`` on a registered module, ``collect_report``, ``run_audit``,
``create_backup``, ``plan_param_restore``) and returns a Pydantic envelope.
Nothing here talks VAPIX directly. Exactly one tool writes to a device:
``apply_plan``, and only after the server has asked the human to confirm the
stored plan (MCP elicitation); hosts that cannot ask get a refusal.

Design record: ``docs/plans/2026-10-14-mcp-server-design-decision.md``.

Rules this package holds to:

* **No credential crosses MCP.** Tool inputs are configured device *names*
  (an enum), never hosts or passwords; outputs are scrubbed of the device
  password and its HTTP Basic form; parameter values whose names look like
  secrets are redacted.
* **Nothing on stdout.** On stdio, stdout *is* the wire. This package never
  imports ``axis_cam.cli`` (which owns the Rich console) and never prints.
* **``unknown`` is a first-class answer.** A module the device will not let
  us read is ``unreadable``, never an empty default.
"""
