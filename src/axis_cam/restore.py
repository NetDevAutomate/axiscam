"""Restore device parameters from a backup — plan, apply, verify.

Phase 5 is deliberately narrow: only the parameter tree (``params.json`` from
:mod:`axis_cam.backup`) is restored, through ``param.cgi?action=update``, the
one write path VAPIX documents for it. Per-module REST writes (``PATCH`` on the
device-configuration APIs) are each a separate contract to verify on a device
and are not attempted here.

The shape is the write-safety pattern from Phase 2:

1. :func:`plan_param_restore` reads the device's current parameters and their
   definitions (``listdefinitions``, which says who may write each one) and
   returns the :class:`ParamChange` list — only parameters whose value differs
   and which the device says are writable. It never writes. Everything it will
   not touch is listed with a reason so the plan is honest.
2. :func:`apply_param_restore` writes each change individually, re-reads the
   parameter, and records the outcome per change. A device refusal (``# Error``)
   is recorded and the run continues; an authentication or connection failure
   aborts.

Network parameters are excluded unless asked for: restoring an IP address or
VLAN to a device you are talking to over that network can end the conversation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from axis_cam.api.param import ParamDefinition, short_name
from axis_cam.backup import PARAMS_FILE, load_manifest
from axis_cam.exceptions import AxisApiNotSupportedError, AxisDeviceError
from axis_cam.secrets import is_secret_name

if TYPE_CHECKING:
    from axis_cam.devices.base import AxisDevice

#: Groups whose restore can cut the connection the restore itself is using.
NETWORK_GROUPS: frozenset[str] = frozenset({"Network"})

#: Where the device reports its serial number (verified on AXIS OS 12.11).
SERIAL_PARAM = "root.Properties.System.SerialNumber"


class SkipReason(str, Enum):
    """Why a backed-up parameter is not in the change list."""

    UNCHANGED = "unchanged"
    READ_ONLY = "read-only on this device (listdefinitions securityLevel)"
    NETWORK = "network group (excluded; pass include_network=True)"
    CREDENTIAL = "credential (excluded; pass include_secrets=True)"
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

    The file is checked against the manifest's hash first: a restore must not
    write values from a file the backup does not vouch for.

    Raises:
        FileNotFoundError: No manifest or no ``params.json`` in the backup.
        ValueError: The manifest is unreadable, ``params.json`` does not match
            its recorded hash, or it is not the flat ``{"root.X.Y": "value"}``
            shape the backup writes.
    """
    root = Path(backup_dir)
    manifest = load_manifest(root)
    entry = manifest.get("params")
    if entry is None:
        raise FileNotFoundError(f"{root}: the backup contains no {PARAMS_FILE}")
    raw = (root / entry.file).read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry.sha256:
        raise ValueError(
            f"{entry.file} does not match the hash in the manifest; "
            "the backup is damaged or was edited (run `backup verify`)"
        )
    data = json.loads(raw)
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        raise ValueError(f"{PARAMS_FILE} is not a flat mapping of parameter name to value")
    return data, dict(manifest.device)


def diff_params(
    current: dict[str, str],
    target: dict[str, str],
    definitions: dict[str, ParamDefinition] | None = None,
    *,
    include_network: bool = False,
    include_secrets: bool = False,
) -> RestorePlan:
    """Compute the changes that would bring ``current`` to ``target``.

    Pure function: no device access. Keys are full names (``root.X.Y``).
    With ``definitions`` (from :meth:`ParamAPI.definitions`), parameters the
    device declares read-only are skipped up front instead of being tried
    and refused; without them every differing parameter is a change and the
    device's ``# Error`` reply decides at apply time. Credential parameters
    (:func:`axis_cam.secrets.is_secret_name`) are skipped unless
    ``include_secrets``: restoring an old community string or password over
    a rotated one is rarely what a restore means.
    """
    plan = RestorePlan(skipped={reason: [] for reason in SkipReason})
    for name, wanted in target.items():
        group = short_name(name).split(".", 1)[0]
        definition = definitions.get(name) if definitions else None
        if name not in current:
            plan.skipped[SkipReason.MISSING_ON_DEVICE].append(name)
        elif current[name] == wanted:
            plan.skipped[SkipReason.UNCHANGED].append(name)
        elif definition is not None and not definition.writable:
            plan.skipped[SkipReason.READ_ONLY].append(name)
        elif is_secret_name(name) and not include_secrets:
            plan.skipped[SkipReason.CREDENTIAL].append(name)
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
    include_secrets: bool = False,
) -> RestorePlan:
    """Read the device's parameters and definitions, diff against a backup. Never writes.

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
    definitions = await device.params.definitions()
    plan = diff_params(
        current,
        target,
        definitions,
        include_network=include_network,
        include_secrets=include_secrets,
    )
    plan.backup_dir = Path(backup_dir)
    plan.device_identity = identity
    return plan


class RestoreDriftError(ValueError):
    """The device is not in the state the plan was made against; nothing was written.

    Attributes:
        names: Planned parameters whose live value no longer matches the plan's
            ``current`` (empty when the refusal is a serial-number mismatch).
    """

    def __init__(self, message: str, names: list[str] | None = None) -> None:
        super().__init__(message)
        self.names = list(names or [])


async def apply_param_restore(device: AxisDevice, plan: RestorePlan) -> list[ChangeResult]:
    """Write every change in ``plan``, one parameter at a time, verifying each.

    Before the first write the device is read again: if its serial number is
    not the backup's, or any planned parameter no longer holds the value the
    plan saw, :class:`RestoreDriftError` is raised and nothing is written.
    The plan was a diff against a moment that has passed (a human read it,
    someone else may have changed the device); applying it now would
    overwrite that change without anyone having seen it. Drifted parameters
    are named, never their values (some are credentials).

    A refusal by the device (``# Error`` body — a value it will not accept, or
    a parameter its definitions did not flag) is recorded for that change and
    the run continues with the next. A mismatch on re-read is recorded as a
    failure too: the device said OK but did not keep the value.

    Raises:
        RestoreDriftError: The device changed since the plan, or is another device.
        AxisAuthenticationError / AxisConnectionError: Propagate immediately.
    """
    if not plan.changes:
        return []
    live = await device.params.export()
    planned_serial = plan.device_identity.get("serial_number")
    live_serial = live.get(SERIAL_PARAM)
    if planned_serial and live_serial and live_serial.upper() != planned_serial.upper():
        raise RestoreDriftError(
            f"device serial is {live_serial}, the plan was made for {planned_serial}; "
            "nothing was written"
        )
    drifted = [c.name for c in plan.changes if live.get(c.name) != c.current]
    if drifted:
        raise RestoreDriftError(
            "the device changed since the plan was made, nothing was written: "
            + ", ".join(drifted),
            drifted,
        )
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
