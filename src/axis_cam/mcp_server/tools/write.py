"""Plan and apply: the only path by which this server changes a device.

Plans are minted by ``plan_restore`` and ``plan_account_change``;
``apply_plan`` applies one only after the human confirms the stored plan.

No ``from __future__ import annotations``: tool signatures are introspected
at registration and refer to the per-server device/module enums.
"""

import asyncio
from typing import Annotated, Literal

from mcp.server.elicitation import AcceptedElicitation, ElicitationResult
from mcp.server.mcpserver import Context, Elicit, Resolve
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from axis_cam.devices.base import AxisDevice
from axis_cam.exceptions import (
    AxisError,
    AxisLockoutError,
)
from axis_cam.mcp_server.deps import (
    STATEFUL,
    WRITE,
    ServerDeps,
)
from axis_cam.mcp_server.plans import StoredPlan
from axis_cam.mcp_server.redact import REDACTED, is_secret_name
from axis_cam.mcp_server.schemas import (
    AppliedChange,
    ApplyResult,
    Confirmation,
    PlanResult,
)
from axis_cam.models import UserRole
from axis_cam.restore import (
    ParamChange,
    RestoreDriftError,
    RestorePlan,
    apply_param_restore,
    plan_param_restore,
)


def register(deps: ServerDeps) -> None:
    """Collect this module's tools on ``deps.tool``."""
    resolver = deps.resolver
    store = deps.store
    DeviceName = deps.DeviceName
    tool = deps.tool
    scrubber = deps.scrubber
    guarded = deps.guarded
    backup_path = deps.backup_path

    # -- plans (minted here; applied only by apply_plan after confirmation) ---

    @tool(STATEFUL)
    async def plan_restore(device: DeviceName, backup_id: str) -> PlanResult:  # type: ignore[valid-type]
        """Diff a backup's parameters against the device. Writes nothing; returns a plan."""
        name = str(device)
        path = backup_path(backup_id)

        async def run(dev: AxisDevice) -> PlanResult:
            try:
                plan = await plan_param_restore(dev, path)
            except ValueError as exc:
                raise ToolError(str(exc)) from None
            serial = (
                plan.device_identity.get("serial_number") or (await dev.get_info()).serial_number
            )
            changes = [
                {
                    "name": c.name,
                    "current": REDACTED if is_secret_name(c.name) else c.current,
                    "target": REDACTED if is_secret_name(c.name) else c.target,
                }
                for c in plan.changes
            ]
            payload = {"backup_id": backup_id, "changes": changes, "skipped": plan.skip_counts()}
            private = {
                "changes": [
                    {"name": c.name, "current": c.current, "target": c.target} for c in plan.changes
                ]
            }
            stored = store.mint("param_restore", name, serial, payload, private=private)
            return PlanResult(
                plan_id=stored.plan_id,
                kind=stored.kind,
                device=name,
                serial=serial,
                expires_in_seconds=store.ttl,
                plan=scrubber(name).data(payload),
            )

        return await guarded(name, run)

    @tool(STATEFUL)
    async def plan_account_change(
        device: DeviceName,  # type: ignore[valid-type]
        account: Annotated[str, Field(pattern=r"^[A-Za-z0-9]{1,14}$")],
        action: Literal["set_role", "remove"],
        role: Literal["viewer", "operator", "admin"] | None = None,
    ) -> PlanResult:
        """Plan a VAPIX account role change or removal; writes nothing.

        Password changes are not offered: a password would have to cross MCP.
        """
        name = str(device)
        if action == "set_role" and role is None:
            raise ToolError("set_role needs a role")

        async def run(dev: AxisDevice) -> PlanResult:
            accounts = await dev.users.list()
            target = accounts.get(account)
            if target is None:
                raise ToolError(f"{name} has no account {account!r}")
            new_role = UserRole(role) if role else None
            authenticated_as = resolver.connection(name).username
            admins = [a for a in accounts.accounts if a.role is UserRole.ADMIN]
            loses_admin = target.role is UserRole.ADMIN and (
                action == "remove" or new_role is not UserRole.ADMIN
            )
            refusal = None
            if loses_admin and len(admins) <= 1:
                refusal = "it is the only administrator; the library refuses this"
            elif (loses_admin or action == "remove") and account == authenticated_as:
                refusal = "it is the account this server authenticates as; the library refuses this"
            serial = (await dev.get_info()).serial_number
            payload = {
                "account": account,
                "action": action,
                "current_role": target.role.value if target.role else None,
                "new_role": new_role.value if new_role else None,
                "would_be_refused": refusal,
            }
            stored = store.mint("account_change", name, serial, payload)
            return PlanResult(
                plan_id=stored.plan_id,
                kind=stored.kind,
                device=name,
                serial=serial,
                expires_in_seconds=store.ttl,
                plan=payload,
            )

        return await guarded(name, run)

    # -- apply (the only device write; needs a human confirmation) --------------

    locks = deps.locks

    def describe_plan(plan: StoredPlan) -> str:
        """The confirmation text, rendered from the STORED plan (never from model input)."""
        head = f"Apply this change to {plan.device} (serial {plan.serial})?"
        if plan.kind == "param_restore":
            lines = [
                f"  {c['name']}: {c['current']!r} -> {c['target']!r}"
                for c in plan.payload["changes"]
            ]
            body = f"Restore {len(lines)} parameter(s) from {plan.payload['backup_id']}:"
            return "\n".join([head, body, *lines])
        p = plan.payload
        what = "remove" if p["action"] == "remove" else f"set role to {p['new_role']}"
        return f"{head}\nAccount {p['account']} (now {p['current_role']}): {what}."

    def confirm_plan(plan_id: str, ctx: Context) -> Elicit[Confirmation]:
        """Resolver: refuse hosts that cannot ask a human, then ask."""
        capabilities = ctx.client_capabilities
        if capabilities is None or capabilities.elicitation is None:
            raise ToolError(
                "this MCP host cannot show a confirmation (no elicitation capability), "
                "so apply_plan is disabled here; the plan is unchanged. Apply it with the "
                "axiscam CLI instead."
            )
        plan = store.get(plan_id)
        if plan is None:
            raise ToolError(f"no such plan (unknown or expired): {plan_id}")
        return Elicit(describe_plan(plan), Confirmation)

    async def apply_restore(dev: AxisDevice, plan: StoredPlan) -> ApplyResult:
        wanted = plan.private["changes"]
        restore = RestorePlan(
            changes=[ParamChange(c["name"], c["current"], c["target"]) for c in wanted],
            device_identity={"serial_number": plan.serial},
        )
        try:
            applied = await apply_param_restore(dev, restore)
        except RestoreDriftError as exc:
            return ApplyResult(
                plan_id=plan.plan_id, device=plan.device, status="refused", reason=str(exc)
            )
        results = [
            AppliedChange(
                name=r.change.name,
                ok=r.ok,
                detail=r.detail
                if not is_secret_name(r.change.name)
                else ("verified" if r.ok else "failed (credential: detail withheld)"),
            )
            for r in applied
        ]
        failed = sum(not r.ok for r in results)
        status = "applied" if not failed else ("failed" if failed == len(results) else "partial")
        return ApplyResult(plan_id=plan.plan_id, device=plan.device, status=status, results=results)

    async def apply_account(dev: AxisDevice, plan: StoredPlan) -> ApplyResult:
        p = plan.payload
        if p["would_be_refused"]:
            return ApplyResult(
                plan_id=plan.plan_id,
                device=plan.device,
                status="refused",
                reason=p["would_be_refused"],
            )
        current = (await dev.users.list()).get(p["account"])
        now = current.role.value if current and current.role else None
        if current is None or now != p["current_role"]:
            return ApplyResult(
                plan_id=plan.plan_id,
                device=plan.device,
                status="refused",
                reason=f"the account changed since the plan was made (now {now})",
            )
        try:
            if p["action"] == "remove":
                await dev.users.remove(p["account"])
            else:
                await dev.users.set_role(p["account"], UserRole(p["new_role"]))
        except AxisLockoutError as exc:
            return ApplyResult(
                plan_id=plan.plan_id, device=plan.device, status="refused", reason=str(exc)
            )
        except AxisError as exc:
            return ApplyResult(
                plan_id=plan.plan_id,
                device=plan.device,
                status="failed",
                results=[AppliedChange(name=p["account"], ok=False, detail=str(exc))],
            )
        return ApplyResult(
            plan_id=plan.plan_id,
            device=plan.device,
            status="applied",
            results=[AppliedChange(name=p["account"], ok=True, detail="verified")],
        )

    @tool(WRITE)
    async def apply_plan(
        plan_id: str,
        answer: Annotated[ElicitationResult[Confirmation], Resolve(confirm_plan)],
    ) -> ApplyResult:
        """Apply a plan from plan_restore or plan_account_change, after the human confirms.

        The server shows the human the stored plan and asks; a declined answer
        writes nothing. The plan is single-use, bound to the device's serial
        number, and refused if the device changed since it was made. Hosts
        that cannot ask the human get an error and nothing is written.
        """
        plan = store.get(plan_id)
        if plan is None:
            raise ToolError(f"no such plan (unknown or expired): {plan_id}")
        if not isinstance(answer, AcceptedElicitation) or not answer.data.approve:
            return ApplyResult(
                plan_id=plan_id,
                device=plan.device,
                status="declined",
                reason="the human did not approve; nothing was written (the plan is kept)",
            )
        plan = store.take(plan_id)  # single use from here on, whatever the outcome
        if plan is None:
            raise ToolError(f"plan already used or expired: {plan_id}")
        lock = locks.setdefault(plan.device, asyncio.Lock())
        async with lock:

            async def run(dev: AxisDevice) -> ApplyResult:
                serial = (await dev.get_info()).serial_number
                if serial.upper() != plan.serial.upper():
                    return ApplyResult(
                        plan_id=plan_id,
                        device=plan.device,
                        status="refused",
                        reason=f"device serial is {serial}, the plan was made for {plan.serial}",
                    )
                if plan.kind == "param_restore":
                    return await apply_restore(dev, plan)
                return await apply_account(dev, plan)

            result = await guarded(plan.device, run)
        return ApplyResult.model_validate(scrubber(plan.device).data(result.model_dump()))
