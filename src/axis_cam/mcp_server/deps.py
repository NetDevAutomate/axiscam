"""What every tool module needs, built once per server by :func:`build_deps`.

The tool modules (``tools/read.py``, ``audit.py``, ``backup.py``, ``write.py``)
each expose ``register(deps)``. They receive this bundle instead of reaching for
globals, so a test can build a server over a fake resolver, a temporary backup
root and its own plan store without patching anything.

No ``from __future__ import annotations``: ``guarded`` is generic and the
dataclass is introspected at runtime.
"""

import asyncio
import contextlib
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from axis_cam.api.registry import registered_modules
from axis_cam.backup import MANIFEST_FILE
from axis_cam.devices.base import AxisDevice
from axis_cam.exceptions import AxisError
from axis_cam.mcp_server.devices import DeviceResolver, device_enum
from axis_cam.mcp_server.plans import PlanStore
from axis_cam.mcp_server.redact import Scrubber

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

ToolFn = Callable[..., Any]


def resource_module_names() -> list[str]:
    """Registered modules that can ``read()`` into one model, sorted."""
    return sorted(name for name, cls in registered_modules().items() if hasattr(cls, "read"))


@dataclass
class ServerDeps:
    """Shared state and helpers for one server instance.

    Attributes:
        resolver: Configured devices.
        store: Plan store.
        root: Fixed backup directory on the server's disk.
        DeviceName: Enum of configured device names (the ``device`` argument type).
        ModuleName: Enum of readable module names.
        registered: Tools collected by :meth:`tool`, registered sorted later.
        locks: One lock per device, held while a plan is applied.
    """

    resolver: DeviceResolver
    store: PlanStore
    root: Path
    DeviceName: type[StrEnum]
    ModuleName: type[StrEnum]
    registered: dict[str, tuple[ToolFn, ToolAnnotations]] = field(default_factory=dict)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def tool(self, annotations: ToolAnnotations) -> Callable[[ToolFn], ToolFn]:
        """Collect a tool for sorted registration.

        :func:`~axis_cam.mcp_server.server.build_server` registers them sorted
        by name, so ``tools/list`` is deterministic whatever order the tool
        modules are imported or written in.
        """

        def collect(fn: ToolFn) -> ToolFn:
            if fn.__name__ in self.registered:
                raise RuntimeError(f"tool {fn.__name__!r} registered twice")
            self.registered[fn.__name__] = (fn, annotations)
            return fn

        return collect

    def scrubber(self, name: str) -> Scrubber:
        """Removes this device's password (and its Basic form) from output."""
        conn = self.resolver.connection(name)
        return Scrubber(conn.username, conn.password)

    @contextlib.asynccontextmanager
    async def opened(self, name: str) -> AsyncIterator[AxisDevice]:
        """Open a device; any failure becomes a scrubbed ToolError."""
        scrub = self.scrubber(name)
        try:
            async with self.resolver.open(name) as dev:
                yield dev
        except ToolError:
            raise
        except (AxisError, OSError) as exc:
            raise ToolError(f"{name}: {scrub.text(str(exc) or type(exc).__name__)}") from None

    async def guarded[T](self, name: str, fn: Callable[[AxisDevice], Awaitable[T]]) -> T:
        """Run ``fn`` on the opened device, failures scrubbed."""
        async with self.opened(name) as dev:
            return await fn(dev)

    def backup_path(self, backup_id: str) -> Path:
        """The directory for ``backup_id`` inside the fixed root, or a ToolError."""
        if not BACKUP_ID.fullmatch(backup_id) or ".." in backup_id:
            raise ToolError(f"not a backup id: {backup_id!r}")
        path = self.root / backup_id
        if not (path / MANIFEST_FILE).is_file():
            raise ToolError(f"no such backup: {backup_id}")
        return path


def build_deps(resolver: DeviceResolver, *, root: Path, store: PlanStore) -> ServerDeps:
    """Build the bundle; the enums are fixed for the server's lifetime."""
    return ServerDeps(
        resolver=resolver,
        store=store,
        root=root,
        DeviceName=device_enum(resolver.names()),
        ModuleName=cast(
            "type[StrEnum]", StrEnum("ModuleName", {n: n for n in resource_module_names()})
        ),
    )


__all__ = [
    "BACKUP_ID",
    "FLEET_CONCURRENCY",
    "FLEET_TIMEOUT",
    "PARAMS_MAX_LIMIT",
    "READ",
    "STATEFUL",
    "WRITE",
    "ServerDeps",
    "build_deps",
    "resource_module_names",
]
