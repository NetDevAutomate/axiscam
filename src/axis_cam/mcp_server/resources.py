"""Read-only resources: data that does not change while the server runs.

Resources are cacheable by contract, so live device state is never one (that
is what the read tools are for). These three are fixed for the life of the
server, or -- for a manifest -- for the life of the backup:

* ``axiscam://checks`` -- what ``security_audit`` checks, with the guide's
  hardened values;
* ``axiscam://schemas/{module}`` -- the JSON Schema of a module's
  ``read_module`` value;
* ``axiscam://backups/{backup_id}/manifest`` -- a backup's manifest, including
  which credentials its ``params.json`` holds (names only).

No ``from __future__ import annotations``: handler signatures are introspected.
"""

import json
import typing

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError
from mcp.server.mcpserver.exceptions import ToolError as _ToolError
from pydantic import BaseModel

from axis_cam.api.registry import registered_modules
from axis_cam.audit import DATA_DEPENDENT_CHECKS, GUIDE_URL, check_catalogue
from axis_cam.backup import load_manifest
from axis_cam.mcp_server.deps import ServerDeps, resource_module_names

JSON = "application/json"


def module_model(module: str) -> type[BaseModel]:
    """The Pydantic model a module's ``read()`` returns.

    Raises:
        ResourceError: Not a readable module.
    """
    if module not in resource_module_names():
        raise ResourceError(
            f"no readable module {module!r}; known: {', '.join(resource_module_names())}"
        )
    reader = getattr(registered_modules()[module], "read")  # noqa: B009 - not on BaseAPI
    model = typing.get_type_hints(reader).get("return")
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        raise ResourceError(f"module {module!r} has no declared result model")
    return model


def register(server: MCPServer, deps: ServerDeps) -> None:
    """Add the resources to ``server``."""

    @server.resource(
        "axiscam://checks",
        name="audit_checks",
        title="Security audit checks",
        description="Every check security_audit runs, with severity, guide reference and, "
        "for parameter checks, the parameter and its hardened values.",
        mime_type=JSON,
    )
    async def checks() -> str:
        return json.dumps(
            {
                "guide": GUIDE_URL,
                "checks": await check_catalogue(),
                "data_dependent": list(DATA_DEPENDENT_CHECKS),
                "note": "data_dependent checks are reported only when their data is readable "
                "(per account, per certificate, or a second finding on the same setting).",
            },
            indent=2,
        )

    @server.resource(
        "axiscam://schemas/{module}",
        name="module_schema",
        title="Module result schema",
        description="JSON Schema of the value read_module returns for a module.",
        mime_type=JSON,
    )
    def schema(module: str) -> str:
        model = module_model(module)
        return json.dumps(
            {"module": module, "model": model.__name__, "schema": model.model_json_schema()},
            indent=2,
        )

    @server.resource(
        "axiscam://backups/{backup_id}/manifest",
        name="backup_manifest",
        title="Backup manifest",
        description="A backup's manifest: files and hashes, what is not included, and which "
        "credential parameters params.json holds (names only).",
        mime_type=JSON,
    )
    def manifest(backup_id: str) -> str:
        try:
            path = deps.backup_path(backup_id)
        except _ToolError as exc:
            raise ResourceError(str(exc)) from None
        return json.dumps(load_manifest(path).to_dict(), indent=2)


__all__ = ["module_model", "register"]
