"""The security-audit tool.

No ``from __future__ import annotations``: tool signatures are introspected
at registration and refer to the per-server device/module enums.
"""

from typing import Literal

from axis_cam.audit import run_audit
from axis_cam.devices.base import AxisDevice
from axis_cam.mcp_server.deps import (
    READ,
    ServerDeps,
)
from axis_cam.mcp_server.schemas import (
    Payload,
)


def register(deps: ServerDeps) -> None:
    """Collect this module's tools on ``deps.tool``."""
    DeviceName = deps.DeviceName
    tool = deps.tool
    scrubber = deps.scrubber
    guarded = deps.guarded

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
