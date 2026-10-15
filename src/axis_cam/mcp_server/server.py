"""The axiscam MCP server (Phase A: read and plan, no writes to devices).

:func:`build_server` assembles an ``mcp`` v2 ``MCPServer`` over a
:class:`~axis_cam.mcp_server.devices.DeviceResolver`; :func:`main` runs it on
stdio against the config file. Every tool is a thin composition of library
calls; this module adds only the MCP boundary rules:

* the ``device`` argument is an enum of configured names (no hosts, no
  credentials as input);
* a device that will not answer is a *result* (``status`` in the envelope)
  for per-module reads, and a scrubbed tool error when it cannot be opened;
* every output passes through the :class:`~.redact.Scrubber` and parameter
  values are redacted by name;
* nothing is printed: on stdio, stdout is the wire.

No ``from __future__ import annotations`` here on purpose: tool signatures
are introspected at registration, and the device/module enums are local to
:func:`build_server`.
"""

import asyncio
import contextlib
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server import CacheHint, MCPServer
from mcp.server.elicitation import AcceptedElicitation, ElicitationResult
from mcp.server.mcpserver import Context, Elicit, Resolve
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from axis_cam import __version__
from axis_cam.api.registry import registered_modules
from axis_cam.audit import run_audit
from axis_cam.backup import MANIFEST_FILE, create_backup, load_manifest, verify_backup
from axis_cam.config import get_data_dir
from axis_cam.devices.base import AxisDevice
from axis_cam.exceptions import (
    AxisApiNotSupportedError,
    AxisError,
    AxisLockoutError,
    AxisPermissionError,
)
from axis_cam.fleet import fleet_json, run_fleet
from axis_cam.mcp_server.devices import ConfigResolver, DeviceResolver, DeviceSummary, device_enum
from axis_cam.mcp_server.plans import PlanStore, StoredPlan
from axis_cam.mcp_server.redact import REDACTED, Scrubber, is_secret_name, redact_params
from axis_cam.models import UserRole
from axis_cam.report import collect_report
from axis_cam.restore import ParamChange, RestorePlan, apply_param_restore, plan_param_restore

#: Every tool this server registers, in the order they are documented.
TOOL_NAMES: tuple[str, ...] = (
    "list_devices",
    "list_modules",
    "read_module",
    "device_report",
    "security_audit",
    "fleet_read",
    "query_params",
    "backup_create",
    "backup_list",
    "backup_verify",
    "plan_restore",
    "plan_account_change",
    "apply_plan",
)

#: tools/list is fixed for the life of the process; let clients cache it.
TOOLS_LIST_TTL_MS = 300_000
PARAMS_MAX_LIMIT = 200
FLEET_CONCURRENCY = 4
FLEET_TIMEOUT = 120.0
BACKUP_ID = re.compile(r"^backup-[A-Za-z0-9_.-]+$")

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
#: Mints server-side state (a plan, a backup on the server's disk); never writes a device.
STATEFUL = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
#: The one tool that writes to a device -- only after the human confirms.
WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False
)


def resource_module_names() -> list[str]:
    """Registered modules that can ``read()`` into one model, sorted."""
    return sorted(name for name, cls in registered_modules().items() if hasattr(cls, "read"))


# --- result models ----------------------------------------------------------------


class DeviceList(BaseModel):
    devices: list[DeviceSummary]


class ModuleList(BaseModel):
    device: str
    advertised: list[str] = Field(description="Discoverable REST modules this device advertises.")
    not_advertised: list[str] = Field(description="Modules this device does not advertise.")
    never_gated: list[str] = Field(description="CGI modules, always attempted.")


class ModuleRead(BaseModel):
    device: str
    module: str
    status: Literal["ok", "not_advertised", "unreadable", "error"]
    model: str | None = None
    value: dict[str, Any] | None = None
    reason: str | None = None


class Payload(BaseModel):
    """A library result passed through as JSON."""

    device: str
    result: dict[str, Any]


class ParamItem(BaseModel):
    name: str
    value: str
    redacted: bool = False


class ParamPage(BaseModel):
    device: str
    prefix: str
    total: int
    items: list[ParamItem]
    next_cursor: int | None = None


class BackupInfo(BaseModel):
    backup_id: str
    device: dict[str, str] = Field(default_factory=dict)
    created_at: str = ""
    files: int = 0
    errors: dict[str, str] = Field(default_factory=dict)


class BackupBackups(BaseModel):
    backups: list[BackupInfo]


class BackupCheck(BaseModel):
    backup_id: str
    ok: bool
    problems: list[str]


class PlanResult(BaseModel):
    plan_id: str
    kind: str
    device: str
    serial: str
    expires_in_seconds: int
    plan: dict[str, Any]
    note: str = (
        "Plan only: nothing was written to the device. To apply it, call apply_plan; "
        "the server asks the human to confirm and refuses on hosts that cannot ask."
    )


class Confirmation(BaseModel):
    """What the human is asked. Rendered by the host as a form."""

    approve: bool = Field(description="Apply exactly this change to the device now.")


class AppliedChange(BaseModel):
    name: str
    ok: bool
    detail: str


class ApplyResult(BaseModel):
    plan_id: str
    device: str
    status: Literal["applied", "partial", "failed", "declined", "refused"]
    reason: str | None = None
    results: list[AppliedChange] = Field(default_factory=list)


# --- server -------------------------------------------------------------------------


def build_server(
    resolver: DeviceResolver,
    *,
    backup_root: Path | None = None,
    plans: PlanStore | None = None,
) -> MCPServer:
    """Assemble the server over ``resolver``.

    Args:
        resolver: Which devices exist and how to open them.
        backup_root: Where ``backup_create`` writes; fixed for the server's life,
            never chosen by the caller. Defaults to ``<data dir>/mcp-backups``.
        plans: Plan store (injectable for tests).
    """
    root = backup_root if backup_root is not None else get_data_dir() / "mcp-backups"
    store = plans if plans is not None else PlanStore()
    DeviceName = device_enum(resolver.names())
    ModuleName = StrEnum("ModuleName", {n: n for n in resource_module_names()})

    server = MCPServer(
        "axiscam",
        version=__version__,
        instructions=(
            "Read-only access to configured Axis devices: module reads, reports, "
            "security audits, parameter queries (credentials redacted), backups on "
            "the server's own disk, and change plans. Nothing here writes to a device."
        ),
        cache_hints={"tools/list": CacheHint(ttl_ms=TOOLS_LIST_TTL_MS, scope="public")},
    )

    def scrubber(name: str) -> Scrubber:
        conn = resolver.connection(name)
        return Scrubber(conn.username, conn.password)

    registered: dict[str, tuple[Callable[..., Any], ToolAnnotations]] = {}

    def tool(annotations: ToolAnnotations) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Collect a tool for sorted registration.

        :func:`build_server` registers them sorted by name, so ``tools/list``
        is deterministic whatever order they are written in.
        """

        def collect(fn: Callable[..., Any]) -> Callable[..., Any]:
            registered[fn.__name__] = (fn, annotations)
            return fn

        return collect

    @contextlib.asynccontextmanager
    async def opened(name: str) -> AsyncIterator[AxisDevice]:
        """Open a device; any failure becomes a scrubbed ToolError."""
        scrub = scrubber(name)
        try:
            async with resolver.open(name) as dev:
                yield dev
        except ToolError:
            raise
        except AxisError as exc:
            raise ToolError(f"{name}: {scrub.text(str(exc) or type(exc).__name__)}") from None
        except OSError as exc:
            raise ToolError(f"{name}: {scrub.text(str(exc) or type(exc).__name__)}") from None

    async def guarded[T](name: str, fn: Callable[[AxisDevice], Awaitable[T]]) -> T:
        async with opened(name) as dev:
            return await fn(dev)

    def backup_path(backup_id: str) -> Path:
        if not BACKUP_ID.fullmatch(backup_id) or ".." in backup_id:
            raise ToolError(f"not a backup id: {backup_id!r}")
        path = root / backup_id
        if not (path / MANIFEST_FILE).is_file():
            raise ToolError(f"no such backup: {backup_id}")
        return path

    # -- devices and modules ----------------------------------------------------

    @tool(READ)
    def list_devices() -> DeviceList:
        """The configured devices every other tool's `device` argument names."""
        return DeviceList(devices=[resolver.describe(n) for n in resolver.names()])

    @tool(READ)
    async def list_modules(device: DeviceName) -> ModuleList:  # type: ignore[valid-type]
        """Which readable modules this device advertises, per its live API discovery."""
        name = str(device)

        async def run(dev: AxisDevice) -> ModuleList:
            available = await dev.available_resources()
            advertised, missing, ungated = [], [], []
            for mod_name, module in dev.resources.items():
                if module.api_id is None:
                    ungated.append(mod_name)
                elif mod_name in available:
                    advertised.append(mod_name)
                else:
                    missing.append(mod_name)
            return ModuleList(
                device=name, advertised=advertised, not_advertised=missing, never_gated=ungated
            )

        return await guarded(name, run)

    @tool(READ)
    async def read_module(device: DeviceName, module: ModuleName) -> ModuleRead:  # type: ignore[valid-type]
        """Read one module's current state.

        `status` says whether the value is real: ok; not_advertised (the device
        lacks the API); unreadable (403/404, could not read -- never treat as
        disabled); or error.
        """
        name, mod = str(device), str(module)
        scrub = scrubber(name)

        async def run(dev: AxisDevice) -> ModuleRead:
            available = await dev.available_resources()
            target = available.get(mod)
            if target is None:
                return ModuleRead(
                    device=name,
                    module=mod,
                    status="not_advertised",
                    reason=f"{name} does not advertise the API behind '{mod}'",
                )
            try:
                model = await target.read()
            except AxisPermissionError as exc:
                return ModuleRead(
                    device=name, module=mod, status="unreadable", reason=scrub.text(str(exc))
                )
            except AxisApiNotSupportedError as exc:
                return ModuleRead(
                    device=name, module=mod, status="unreadable", reason=scrub.text(str(exc))
                )
            except AxisError as exc:
                return ModuleRead(
                    device=name, module=mod, status="error", reason=scrub.text(str(exc))
                )
            except Exception as exc:
                return ModuleRead(
                    device=name,
                    module=mod,
                    status="error",
                    reason=f"internal error: {type(exc).__name__}",
                )
            return ModuleRead(
                device=name,
                module=mod,
                status="ok",
                model=type(model).__name__,
                value=scrub.data(model.model_dump(mode="json")),
            )

        return await guarded(name, run)

    # -- composed reads ---------------------------------------------------------

    @tool(READ)
    async def device_report(device: DeviceName, full: bool = False) -> Payload:  # type: ignore[valid-type]
        """Identity and status; with full=true every advertised module (slower)."""
        name = str(device)

        async def run(dev: AxisDevice) -> Payload:
            report = await collect_report(dev, full=full, name=name)
            return Payload(device=name, result=scrubber(name).data(report.to_dict()))

        return await guarded(name, run)

    @tool(READ)
    async def security_audit(
        device: DeviceName,  # type: ignore[valid-type]
        status: Literal["pass", "fail", "unknown", "n/a", "info"] | None = None,
    ) -> Payload:
        """Check the device against the AXIS OS Hardening Guide.

        `unknown` means the setting could not be read; it is neither a pass nor
        a fail.
        """
        name = str(device)

        async def run(dev: AxisDevice) -> Payload:
            data = (await run_audit(dev, device_name=name)).to_dict()
            if status is not None:
                data["findings"] = [f for f in data["findings"] if f["status"] == status]
            return Payload(device=name, result=scrubber(name).data(data))

        return await guarded(name, run)

    @tool(READ)
    async def fleet_read(
        selection: Annotated[str, Field(description="'all', a group tag, or a device type.")],
        op: Literal["info", "report", "audit"],
    ) -> Payload:
        """Run one read across several devices; a device that fails is a row, not the end."""
        names = resolver.select(selection)
        if not names:
            raise ToolError(f"no configured device matches {selection!r}")

        class Target:
            def __init__(self, name: str) -> None:
                self.name = name
                self.host = resolver.describe(name).host

            def open(self) -> AxisDevice:
                return resolver.open(self.name)

        async def operation(dev: AxisDevice) -> dict[str, Any]:
            if op == "info":
                return (await dev.get_info()).model_dump(mode="json")
            if op == "report":
                return (await collect_report(dev)).to_dict()
            return (await run_audit(dev)).to_dict()

        results = await run_fleet(
            [(n, Target(n)) for n in names],
            operation,
            concurrency=FLEET_CONCURRENCY,
            timeout=FLEET_TIMEOUT,
        )
        data: Any = fleet_json(results, lambda v: v)
        for n in names:
            data = scrubber(n).data(data)
        return Payload(device=selection, result=data)

    @tool(READ)
    async def query_params(
        device: DeviceName,  # type: ignore[valid-type]
        prefix: Annotated[
            str, Field(min_length=1, description="Group prefix, e.g. 'Network.SSH'.")
        ],
        limit: Annotated[int, Field(ge=1, le=PARAMS_MAX_LIMIT)] = 50,
        cursor: Annotated[int | None, Field(ge=0)] = None,
    ) -> ParamPage:
        """Parameters under a prefix, paged. Credential-like values are redacted."""
        name = str(device)
        wanted = prefix.removeprefix("root.").rstrip(".")

        async def run(dev: AxisDevice) -> ParamPage:
            params = await dev.params.export()
            matched = sorted(
                k
                for k in params
                if (short := k.removeprefix("root.")) == wanted or short.startswith(wanted + ".")
            )
            start = cursor or 0
            page = matched[start : start + limit]
            safe = redact_params({k: params[k] for k in page})
            items = [
                ParamItem(name=k, value=safe[k], redacted=safe[k] == REDACTED and is_secret_name(k))
                for k in page
            ]
            nxt = start + limit if start + limit < len(matched) else None
            return ParamPage(
                device=name, prefix=wanted, total=len(matched), items=items, next_cursor=nxt
            )

        page = await guarded(name, run)
        return ParamPage.model_validate(scrubber(name).data(page.model_dump()))

    # -- backups (written to the server's own disk) -----------------------------

    @tool(STATEFUL)
    async def backup_create(device: DeviceName) -> BackupInfo:  # type: ignore[valid-type]
        """Snapshot the device into the server's backup directory; returns a backup_id."""
        name = str(device)

        async def run(dev: AxisDevice) -> BackupInfo:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            path, manifest = await asyncio.wait_for(create_backup(dev, root, name=name), 180)
            return BackupInfo(
                backup_id=path.name,
                device=dict(manifest.device),
                created_at=manifest.created_at,
                files=len(manifest.files),
                errors=scrubber(name).data(dict(manifest.errors)),
            )

        return await guarded(name, run)

    @tool(READ)
    def backup_list() -> BackupBackups:
        """Backups in the server's backup directory, newest first."""
        if not root.is_dir():
            return BackupBackups(backups=[])
        found = []
        for path in sorted(root.iterdir(), reverse=True):
            if BACKUP_ID.fullmatch(path.name) and (path / MANIFEST_FILE).is_file():
                manifest = load_manifest(path)
                found.append(
                    BackupInfo(
                        backup_id=path.name,
                        device=dict(manifest.device),
                        created_at=manifest.created_at,
                        files=len(manifest.files),
                        errors=dict(manifest.errors),
                    )
                )
        return BackupBackups(backups=found)

    @tool(READ)
    def backup_verify(backup_id: str) -> BackupCheck:
        """Re-hash a backup's files against its manifest."""
        problems = verify_backup(backup_path(backup_id))
        return BackupCheck(backup_id=backup_id, ok=not problems, problems=problems)

    # -- plans (minted, never applied in Phase A) -------------------------------

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

    locks: dict[str, asyncio.Lock] = {}

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
        live = await dev.params.export()
        drifted = [c["name"] for c in wanted if live.get(c["name"]) != c["current"]]
        if drifted:
            return ApplyResult(
                plan_id=plan.plan_id,
                device=plan.device,
                status="refused",
                reason="the device changed since the plan was made: " + ", ".join(drifted),
            )
        restore = RestorePlan(
            changes=[ParamChange(c["name"], c["current"], c["target"]) for c in wanted]
        )
        results = [
            AppliedChange(
                name=r.change.name,
                ok=r.ok,
                detail=r.detail
                if not is_secret_name(r.change.name)
                else ("verified" if r.ok else "failed (credential: detail withheld)"),
            )
            for r in await apply_param_restore(dev, restore)
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

    if set(registered) != set(TOOL_NAMES):
        raise RuntimeError(
            f"tool set drifted from TOOL_NAMES: {sorted(set(registered) ^ set(TOOL_NAMES))}"
        )
    for tool_name in sorted(registered):
        fn, annotations = registered[tool_name]
        server.add_tool(fn, annotations=annotations)
    return server


def main() -> None:
    """Run the server on stdio against the axiscam config file."""
    build_server(ConfigResolver()).run("stdio")


__all__ = ["TOOL_NAMES", "build_server", "main", "resource_module_names"]
