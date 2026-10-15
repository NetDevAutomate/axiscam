"""Backup tools: create, list and verify on the server's own disk.

No ``from __future__ import annotations``: tool signatures are introspected
at registration and refer to the per-server device/module enums.
"""

import asyncio

from axis_cam.backup import MANIFEST_FILE, create_backup, load_manifest, verify_backup
from axis_cam.devices.base import AxisDevice
from axis_cam.mcp_server.deps import (
    BACKUP_ID,
    READ,
    STATEFUL,
    ServerDeps,
)
from axis_cam.mcp_server.schemas import (
    BackupBackups,
    BackupCheck,
    BackupInfo,
)


def register(deps: ServerDeps) -> None:
    """Collect this module's tools on ``deps.tool``."""
    root = deps.root
    DeviceName = deps.DeviceName
    tool = deps.tool
    scrubber = deps.scrubber
    guarded = deps.guarded
    backup_path = deps.backup_path

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
