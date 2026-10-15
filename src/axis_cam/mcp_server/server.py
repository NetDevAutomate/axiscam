"""The axiscam MCP server: read and plan tools, and one confirmed write.

:func:`build_server` is the composition root: it builds the shared
:class:`~axis_cam.mcp_server.deps.ServerDeps`, lets each tool module register
its tools, then adds them to an ``mcp`` v2 ``MCPServer`` sorted by name.
:func:`main` runs it on stdio against the config file.

Layout:

* ``deps.py`` -- constants, annotations, the per-server bundle (resolver, plan
  store, backup root, device/module enums, scrubbing and opening helpers);
* ``schemas.py`` -- result models;
* ``tools/read.py``, ``audit.py``, ``backup.py``, ``write.py`` -- the tools;
* ``resources.py`` -- read-only, immutable resources.

Boundary rules every module holds to:

* the ``device`` argument is an enum of configured names (no hosts, no
  credentials as input);
* a device that will not answer is a *result* (``status`` in the envelope)
  for per-module reads, and a scrubbed tool error when it cannot be opened;
* every output passes through the :class:`~.redact.Scrubber` and parameter
  values are redacted by name;
* nothing is printed: on stdio, stdout is the wire.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mcp.server import CacheHint, MCPServer

from axis_cam import __version__
from axis_cam.config import get_data_dir
from axis_cam.mcp_server import resources
from axis_cam.mcp_server.deps import build_deps, resource_module_names
from axis_cam.mcp_server.devices import ConfigResolver
from axis_cam.mcp_server.plans import PlanStore
from axis_cam.mcp_server.tools import audit, backup, read, write

if TYPE_CHECKING:
    from pathlib import Path

    from axis_cam.mcp_server.devices import DeviceResolver

#: Every tool this server registers, grouped by module.
TOOL_NAMES: tuple[str, ...] = (
    # tools/read.py
    "list_devices",
    "list_modules",
    "read_module",
    "device_report",
    "fleet_read",
    "query_params",
    # tools/audit.py
    "security_audit",
    # tools/backup.py
    "backup_create",
    "backup_list",
    "backup_verify",
    # tools/write.py
    "plan_restore",
    "plan_account_change",
    "apply_plan",
)

#: tools/list is fixed for the life of the process; let clients cache it.
TOOLS_LIST_TTL_MS = 300_000

INSTRUCTIONS = (
    "Access to configured Axis devices: module reads, reports, security audits, "
    "parameter queries (credentials redacted), backups on the server's own disk, "
    "and change plans. Only apply_plan writes to a device, and only after the "
    "server has asked the human to confirm the stored plan; on hosts that cannot "
    "ask, it refuses and writes nothing. Resources: axiscam://checks (what the "
    "audit checks), axiscam://schemas/{module} (a module's result schema), "
    "axiscam://backups/{backup_id}/manifest (a backup's manifest)."
)


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
    deps = build_deps(
        resolver,
        root=backup_root if backup_root is not None else get_data_dir() / "mcp-backups",
        store=plans if plans is not None else PlanStore(),
    )
    server = MCPServer(
        "axiscam",
        version=__version__,
        instructions=INSTRUCTIONS,
        # private: the device enum in every schema is this user's config, not shareable
        cache_hints={"tools/list": CacheHint(ttl_ms=TOOLS_LIST_TTL_MS, scope="private")},
    )
    # Constructing the server raises the root logger to INFO, at which httpx logs
    # every request URL. A GET carries parameter values in its query string
    # (`param.set`), and a followed redirect's URL is a peer's; neither belongs in
    # a log. The client refuses an echoing redirect before it is followed, but pin
    # httpx to WARNING so an ordinary request URL is never logged either.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    for module in (read, audit, backup, write):
        module.register(deps)

    if set(deps.registered) != set(TOOL_NAMES):
        raise RuntimeError(
            f"tool set drifted from TOOL_NAMES: {sorted(set(deps.registered) ^ set(TOOL_NAMES))}"
        )
    for tool_name in sorted(deps.registered):
        fn, annotations = deps.registered[tool_name]
        server.add_tool(fn, annotations=annotations)
    resources.register(server, deps)
    return server


def main() -> None:
    """Run the server on stdio against the axiscam config file."""
    build_server(ConfigResolver()).run("stdio")


__all__ = ["TOOL_NAMES", "build_server", "main", "resource_module_names"]
