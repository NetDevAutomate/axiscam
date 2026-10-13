"""Device backup: a registry-driven snapshot with an honest manifest.

AXIS OS has no native whole-device backup API, so a backup is composed from
what VAPIX lets a client read: every resource module the device advertises
(through :func:`axis_cam.report.collect_report`), the full parameter tree
(``params.json``) and, optionally, the server report. The result is a
directory::

    backup-<device>-<UTC timestamp>/
        manifest.json        what is here, what is not, and why
        device_info.json     one file per resource, model_dump(mode="json")
        ssh.json
        ...
        params.json          {"root.Group.Name": "value", ...}
        server-report.zip    only with include_server_report=True

The manifest is the point. It records a SHA-256 per file so a backup can be
verified later, and it lists what a VAPIX backup **cannot** contain (account
passwords, private keys, ACAP binaries, recordings) separately from what this
tool does not read yet, so nobody mistakes the snapshot for a full image.

Everything is written owner-only (directory ``0700``, files ``0600``).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from axis_cam import __version__
from axis_cam.exceptions import AxisApiNotSupportedError, AxisDeviceError
from axis_cam.files import write_private
from axis_cam.models import ServerReportFormat
from axis_cam.report import collect_report

if TYPE_CHECKING:
    from axis_cam.devices.base import AxisDevice

MANIFEST_VERSION = 1
MANIFEST_FILE = "manifest.json"
PARAMS_FILE = "params.json"
SERVER_REPORT_FILE = "server-report.zip"

#: What VAPIX gives no client a way to read. A restore cannot recreate these.
NOT_INCLUDED_BY_DESIGN: tuple[str, ...] = (
    "account passwords and password hashes (VAPIX never returns them)",
    "private keys of device certificates",
    "ACAP application binaries and licence keys",
    "recordings and edge-storage content",
    "the device's own TLS and SSH host keys",
)

#: Readable in principle, not read by this version.
NOT_IMPLEMENTED: tuple[str, ...] = (
    "ONVIF user accounts (a separate user database)",
    "installed ACAP application list and settings",
    "stream profiles beyond what the stream module reads",
    "view areas, PTZ presets and guard tours",
    "overlays",
)


@dataclass(frozen=True)
class BackupFile:
    """One file in a backup directory."""

    section: str
    file: str
    sha256: str
    size: int
    source: str


@dataclass
class BackupManifest:
    """Contents of ``manifest.json``.

    Attributes:
        format_version: Manifest schema version.
        created_at: ISO-8601 UTC timestamp.
        tool: Producer name and version.
        device: Host, label and identity read from ``device_info`` when present.
        files: Every file written, with its hash.
        errors: Modules the device advertises but that failed to read.
        skipped: Modules the device does not advertise.
        not_included: What is absent, split by reason.
        restore: Human-readable status of the restore path (which files a
            restore consumes and which it does not).
    """

    format_version: int
    created_at: str
    tool: dict[str, str]
    device: dict[str, str]
    files: list[BackupFile] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    not_included: dict[str, list[str]] = field(
        default_factory=lambda: {
            "by_design": list(NOT_INCLUDED_BY_DESIGN),
            "not_implemented": list(NOT_IMPLEMENTED),
        }
    )
    restore: str = (
        "params.json: `axiscam backup restore DIR` (param.cgi action=update, one parameter "
        "at a time, verified); other sections: not implemented"
    )

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BackupManifest:
        """Inverse of :meth:`to_dict`.

        Raises:
            ValueError: Unknown ``format_version``.
        """
        version = data.get("format_version")
        if version != MANIFEST_VERSION:
            raise ValueError(f"unsupported manifest format_version {version!r}")
        files = [BackupFile(**entry) for entry in data.get("files", [])]
        return cls(
            format_version=version,
            created_at=data["created_at"],
            tool=dict(data.get("tool", {})),
            device=dict(data.get("device", {})),
            files=files,
            errors=dict(data.get("errors", {})),
            skipped=list(data.get("skipped", [])),
            not_included={k: list(v) for k, v in data.get("not_included", {}).items()},
            restore=data.get("restore", ""),
        )

    def get(self, section: str) -> BackupFile | None:
        """The entry for ``section``, or ``None``."""
        return next((f for f in self.files if f.section == section), None)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_bytes(data: Any) -> bytes:
    return json.dumps(data, indent=2, sort_keys=True).encode()


def backup_dir_name(label: str, when: datetime) -> str:
    """``backup-<label>-<YYYYmmddTHHMMSSZ>`` with the label made path-safe."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", label).strip("_") or "device"
    return f"backup-{safe}-{when.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}"


async def create_backup(
    device: AxisDevice,
    destination_root: str | Path,
    *,
    name: str | None = None,
    include_server_report: bool = False,
) -> tuple[Path, BackupManifest]:
    """Snapshot everything the device lets us read into a new directory.

    Args:
        device: An open device with administrator credentials.
        destination_root: Parent directory; the backup directory is created
            inside it.
        name: Label for the device (defaults to its host).
        include_server_report: Also download the server report (zip with image).

    Returns:
        The backup directory and its manifest.

    Raises:
        AxisAuthenticationError: Credentials were rejected.
        AxisConnectionError: The device could not be reached.
        FileExistsError: The backup directory already exists.
    """
    created_at = datetime.now(UTC)
    label = name or device.host
    report = await collect_report(device, full=True, name=label)

    # Per-section payloads, in registry order; params and the server report after.
    payloads: list[tuple[str, str, bytes, str]] = []  # (section, file, bytes, source)
    for section, data in report.sections.items():
        module = device.resources.get(section)
        source = "unknown" if module is None else (module.api_id or "cgi")
        payloads.append((section, f"{section}.json", _json_bytes(data), source))

    errors = dict(report.errors)
    try:
        params = await device.params.export()
    except (AxisDeviceError, AxisApiNotSupportedError) as exc:
        errors["params"] = str(exc)
    else:
        payloads.append(("params", PARAMS_FILE, _json_bytes(params), "param.cgi"))

    if include_server_report:
        server_report = await device.serverreport.download_report(
            format=ServerReportFormat.ZIP_WITH_IMAGE
        )
        if server_report.success:
            payloads.append(
                ("server_report", SERVER_REPORT_FILE, server_report.content, "serverreport.cgi")
            )
        else:
            errors["server_report"] = server_report.error or "download failed"

    backup_dir = Path(destination_root) / backup_dir_name(label, created_at)
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=False)

    manifest = BackupManifest(
        format_version=MANIFEST_VERSION,
        created_at=created_at.isoformat(),
        tool={"name": "axiscam", "version": __version__},
        device=_device_identity(device.host, label, report.sections.get("device_info")),
        errors=errors,
        skipped=list(report.skipped),
    )
    for section, file_name, content, source in payloads:
        write_private(backup_dir / file_name, content)
        manifest.files.append(
            BackupFile(
                section=section,
                file=file_name,
                sha256=_sha256(content),
                size=len(content),
                source=source,
            )
        )
    write_private(backup_dir / MANIFEST_FILE, _json_bytes(manifest.to_dict()))
    return backup_dir, manifest


def _device_identity(host: str, label: str, info: dict[str, Any] | None) -> dict[str, str]:
    identity = {"host": host, "name": label}
    for key in ("product_number", "product_full_name", "serial_number", "firmware_version"):
        value = (info or {}).get(key)
        if value:
            identity[key] = str(value)
    return identity


def load_manifest(backup_dir: str | Path) -> BackupManifest:
    """Read and parse ``manifest.json``.

    Raises:
        FileNotFoundError: No manifest in the directory.
        ValueError: Unsupported or malformed manifest.
    """
    path = Path(backup_dir) / MANIFEST_FILE
    return BackupManifest.from_dict(json.loads(path.read_text()))


def verify_backup(backup_dir: str | Path) -> list[str]:
    """Check every file the manifest lists against its recorded hash.

    Returns:
        Problems found, one line each; empty when the backup is intact.
        Extra files in the directory are reported too: a backup should contain
        exactly what its manifest says.
    """
    root = Path(backup_dir)
    try:
        manifest = load_manifest(root)
    except FileNotFoundError:
        return [f"{MANIFEST_FILE} is missing"]
    except (ValueError, KeyError) as exc:
        return [f"{MANIFEST_FILE} is unreadable: {exc}"]

    problems: list[str] = []
    expected = {entry.file for entry in manifest.files} | {MANIFEST_FILE}
    for entry in manifest.files:
        path = root / entry.file
        if not path.exists():
            problems.append(f"{entry.file}: missing")
            continue
        content = path.read_bytes()
        if len(content) != entry.size:
            problems.append(f"{entry.file}: size {len(content)} != {entry.size}")
        if _sha256(content) != entry.sha256:
            problems.append(f"{entry.file}: sha256 mismatch")
    for path in sorted(root.iterdir()):
        if path.name not in expected:
            problems.append(f"{path.name}: not listed in the manifest")
    return problems
