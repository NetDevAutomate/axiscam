"""Read tools: devices, modules, reports, fleet reads and parameter queries.

No ``from __future__ import annotations``: tool signatures are introspected
at registration and refer to the per-server device/module enums.
"""

from typing import Annotated, Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from axis_cam.audit import run_audit
from axis_cam.devices.base import AxisDevice
from axis_cam.exceptions import (
    AxisApiNotSupportedError,
    AxisError,
    AxisPermissionError,
)
from axis_cam.fleet import fleet_json, run_fleet
from axis_cam.mcp_server.deps import (
    FLEET_CONCURRENCY,
    FLEET_TIMEOUT,
    PARAMS_MAX_LIMIT,
    READ,
    ServerDeps,
)
from axis_cam.mcp_server.redact import REDACTED, is_secret_name, redact_params
from axis_cam.mcp_server.schemas import (
    DeviceList,
    ModuleList,
    ModuleRead,
    ParamItem,
    ParamPage,
    Payload,
)
from axis_cam.report import collect_report


def register(deps: ServerDeps) -> None:
    """Collect this module's tools on ``deps.tool``."""
    resolver = deps.resolver
    DeviceName = deps.DeviceName
    ModuleName = deps.ModuleName
    tool = deps.tool
    scrubber = deps.scrubber
    guarded = deps.guarded

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
