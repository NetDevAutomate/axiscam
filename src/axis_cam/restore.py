"""Restore device parameters from a backup — plan, apply, verify.

Phase 5 is deliberately narrow: only the parameter tree (``params.json`` from
:mod:`axis_cam.backup`) is restored, through ``param.cgi?action=update``, the
one write path VAPIX documents for it. Per-module REST writes (``PATCH`` on the
device-configuration APIs) are each a separate contract to verify on a device
and are not attempted here.

The shape is the write-safety pattern from Phase 2:

1. :func:`plan_param_restore` reads the device's current parameters and returns
   the :class:`ParamChange` list — only parameters whose value differs. It never
   writes. Parameters that cannot or should not be restored are listed with a
   reason so the plan is honest about what it will not do.
2. :func:`apply_param_restore` writes each change individually, re-reads the
   parameter, and records the outcome per change. A device refusal (``# Error``,
   typically a read-only parameter) is recorded and the run continues; an
   authentication or connection failure aborts.

Network parameters are excluded unless asked for: restoring an IP address or
VLAN to a device you are talking to over that network can end the conversation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from axis_cam.api.param import short_name
from axis_cam.backup import PARAMS_FILE, load_manifest
from axis_cam.exceptions import AxisApiNotSupportedError, AxisDeviceError

if TYPE_CHECKING:
    from axis_cam.devices.base import AxisDevice

#: Top-level groups that describe the device rather than configure it. Their
#: parameters are read-only by nature; the device refuses writes with
#: "# Error: Error setting ...". Skipping them keeps the plan honest and short.
IDENTITY_GROUPS: frozenset[str] = frozenset(
    {"Brand", "Properties", "BasicDeviceInfo", "ApiDiscovery", "API", "Browser"}
)

#: Groups whose restore can cut the connection the restore itself is using.
NETWORK_GROUPS: frozenset[str] = frozenset({"Network"})

#: Where the device reports its serial number (verified on AXIS OS 12.11).
SERIAL_PARAM = "root.Properties.System.SerialNumber"


class SkipReason(str, Enum):
    """Why a backed-up parameter is not in the change list."""

    UNCHANGED = "unchanged"
    IDENTITY = "identity group (read-only by nature)"
    NETWORK = "network group (excluded; pass include_network=True)"
    MISSING_ON_DEVICE = "not present on this device"


@dataclass(frozen=True)
class ParamChange:
    """One parameter the restore would set."""

    name: str  # full name, root.Group.Name
    current: str
    target: str

    @property
    def group(self) -> str:
        """Top-level group (``Network`` for ``root.Network.eth0.IPAddress``)."""
        return short_name(self.name).split(".", 1)[0]


@dataclass
class RestorePlan:
    """Outcome of :func:`plan_param_restore`.

    Attributes:
        changes: Parameters whose value differs, in backup order.
        skipped: Backed-up parameters left alone, grouped by reason (counts are
            what a human needs; the full lists are available for ``--verbose``).
        backup_dir: Where the parameters came from.
        device_identity: ``device`` block of the backup manifest, so a plan can
            be refused when it targets a different serial number.
    """

    changes: list[ParamChange] = field(default_factory=list)
    skipped: dict[SkipReason, list[str]] = field(default_factory=dict)
    backup_dir: Path | None = None
    device_identity: dict[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """True when there is nothing to write."""
        return not self.changes

    def skip_counts(self) -> dict[str, int]:
        """``{reason: count}`` for display."""
        return {reason.value: len(names) for reason, names in self.skipped.items() if names}


@dataclass(frozen=True)
class ChangeResult:
    """Outcome of applying one :class:`ParamChange`."""

    change: ParamChange
    ok: bool
    detail: str  # "verified", or the device's refusal / verification mismatch


def load_backup_params(backup_dir: str | Path) -> tuple[dict[str, str], dict[str, str]]:
    """Read ``params.json`` and the device identity from a backup directory.

    Raises:
        FileNotFoundError: No manifest or no ``params.json`` in the backup.
        ValueError: The manifest is unreadable, or ``params.json`` is not the
            flat ``{"root.X.Y": "value"}`` shape the backup writes.
    """
    root = Path(backup_dir)
    manifest = load_manifest(root)
    if manifest.get("params") is None:
        raise FileNotFoundError(f"{root}: the backup contains no {PARAMS_FILE}")
    data = json.loads((root / PARAMS_FILE).read_text())
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        raise ValueError(f"{PARAMS_FILE} is not a flat mapping of parameter name to value")
    return data, dict(manifest.device)


def diff_params(
    current: dict[str, str],
    target: dict[str, str],
    *,
    include_network: bool = False,
) -> RestorePlan:
    """Compute the changes that would bring ``current`` to ``target``.

    Pure function: no device access. Keys are full names (``root.X.Y``).
    """
    plan = RestorePlan(skipped={reason: [] for reason in SkipReason})
    for name, wanted in target.items():
        group = short_name(name).split(".", 1)[0]
        if name not in current:
            plan.skipped[SkipReason.MISSING_ON_DEVICE].append(name)
        elif current[name] == wanted:
            plan.skipped[SkipReason.UNCHANGED].append(name)
        elif group in IDENTITY_GROUPS:
            plan.skipped[SkipReason.IDENTITY].append(name)
        elif group in NETWORK_GROUPS and not include_network:
            plan.skipped[SkipReason.NETWORK].append(name)
        else:
            plan.changes.append(ParamChange(name=name, current=current[name], target=wanted))
    return plan


async def plan_param_restore(
    device: AxisDevice,
    backup_dir: str | Path,
    *,
    include_network: bool = False,
) -> RestorePlan:
    """Read the device's parameters and diff them against a backup. Never writes.

    Raises:
        ValueError: The backup was taken from a different device (serial number
            mismatch) — restoring one camera's parameters onto another is almost
            never what was meant; copy the backup and edit the manifest to force it.
        FileNotFoundError / ValueError: See :func:`load_backup_params`.
        AxisAuthenticationError / AxisConnectionError: Propagate.
    """
    target, identity = load_backup_params(backup_dir)
    current = await device.params.export()
    backed_up_serial = identity.get("serial_number")
    if backed_up_serial:
        live_serial = current.get(SERIAL_PARAM)
        if live_serial and live_serial.upper() != backed_up_serial.upper():
            raise ValueError(
                f"backup is from serial {backed_up_serial}, this device is {live_serial}; "
                "refusing to restore across devices"
            )
    plan = diff_params(current, target, include_network=include_network)
    plan.backup_dir = Path(backup_dir)
    plan.device_identity = identity
    return plan


async def apply_param_restore(device: AxisDevice, plan: RestorePlan) -> list[ChangeResult]:
    """Write every change in ``plan``, one parameter at a time, verifying each.

    A refusal by the device (``# Error`` body — usually a read-only parameter
    the identity list did not cover) is recorded for that change and the run
    continues with the next. A mismatch on re-read is recorded as a failure
    too: the device said OK but did not keep the value.

    Raises:
        AxisAuthenticationError / AxisConnectionError: Propagate immediately.
    """
    results: list[ChangeResult] = []
    for change in plan.changes:
        try:
            await device.params.set(change.name, change.target)
        except (AxisDeviceError, AxisApiNotSupportedError) as exc:
            results.append(ChangeResult(change, False, str(exc)))
            continue
        after = await device.params.get(change.name)
        if after == change.target:
            results.append(ChangeResult(change, True, "verified"))
        else:
            results.append(
                ChangeResult(change, False, f"device accepted the update but reads back {after!r}")
            )
    return results
