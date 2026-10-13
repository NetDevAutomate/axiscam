"""Device report: a registry-driven read of a device's resources.

The report does not know which modules exist. It asks the device for the
resources it advertises (:meth:`AxisDevice.available_resources`), reads each
one, and records the model dump under the module's name. Adding a module to
the registry adds it to ``--full`` reports with no change here.

Per-module failures that mean "this device could not answer for this API"
(:class:`AxisDeviceError`, :class:`AxisApiNotSupportedError`) or "this account
may not use this API" (:class:`AxisPermissionError`, a 403) are recorded in
``errors`` and the report continues. A 401 and connection errors propagate: a
report of twenty-seven "unauthorised" entries is not a report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from axis_cam.exceptions import AxisApiNotSupportedError, AxisDeviceError, AxisPermissionError

if TYPE_CHECKING:
    from axis_cam.devices.base import AxisDevice

#: Sections in the default (non ``--full``) report: enough to identify the
#: device and see how it is wired into the network.
SUMMARY_SECTIONS: tuple[str, ...] = (
    "device_info",
    "time",
    "network",
    "lldp",
    "stream",
    "firewall",
    "ntp",
)


@dataclass
class DeviceReport:
    """Result of :func:`collect_report`.

    Attributes:
        device: Name or host the report was generated for.
        generated_at: Aware UTC timestamp.
        sections: Module name → ``model_dump(mode="json")`` of what was read.
        errors: Module name → error message for modules that failed to read.
        skipped: Requested modules the device does not advertise, in registry
            order. Not an error: the API is absent on this device.
    """

    device: str
    generated_at: datetime
    sections: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dictionary (sections nested, so names cannot collide)."""
        return {
            "device": self.device,
            "generated_at": self.generated_at.isoformat(),
            "sections": self.sections,
            "errors": self.errors,
            "skipped": list(self.skipped),
        }


async def collect_report(
    device: AxisDevice,
    *,
    full: bool = False,
    name: str | None = None,
) -> DeviceReport:
    """Read the device's resources into a report.

    Args:
        device: An open device.
        full: Read every available resource rather than :data:`SUMMARY_SECTIONS`.
        name: Label for the report; defaults to the device host.

    Returns:
        The collected report. ``sections`` holds what was read, ``errors`` what
        failed per module, ``skipped`` what the device does not advertise.

    Raises:
        AxisAuthenticationError: Credentials were rejected.
        AxisConnectionError: The device could not be reached.
    """
    available = await device.available_resources()
    requested = device.resources if full else _summary(device.resources)

    report = DeviceReport(
        device=name or device.host,
        generated_at=datetime.now(UTC),
        skipped=[section for section in requested if section not in available],
    )
    for section in requested:
        if section not in available:
            continue
        try:
            model = await available[section].read()
        except (AxisDeviceError, AxisApiNotSupportedError, AxisPermissionError) as exc:
            # A 403 is "this account may not use this API", a per-module fact;
            # a 401 (credentials rejected) is not caught here and aborts the run.
            report.errors[section] = str(exc)
        else:
            report.sections[section] = model.model_dump(mode="json")
    return report


def _summary(resources: dict[str, Any]) -> dict[str, Any]:
    """The summary subset of ``resources``, in :data:`SUMMARY_SECTIONS` order."""
    return {section: resources[section] for section in SUMMARY_SECTIONS if section in resources}


def render_text(report: DeviceReport) -> str:
    """Short human-readable summary of a report.

    Reads the dumped sections defensively: a field missing from a model, or a
    section that failed, simply leaves its line out.
    """
    lines = [f"Device Report: {report.device}", "=" * 50]
    info = report.sections.get("device_info", {})
    for label, key in (
        ("Model", "product_number"),
        ("Serial", "serial_number"),
        ("Firmware", "firmware_version"),
    ):
        if info.get(key):
            lines.append(f"{label}: {info[key]}")
    interfaces = report.sections.get("network", {}).get("interfaces") or []
    if interfaces:
        iface = interfaces[0]
        if iface.get("ip_address"):
            lines.append(f"IP: {iface['ip_address']}")
        if iface.get("mac_address"):
            lines.append(f"MAC: {iface['mac_address']}")
    neighbors = report.sections.get("lldp", {}).get("neighbors") or []
    if neighbors and neighbors[0].get("sys_name"):
        lines.append(f"Connected to: {neighbors[0]['sys_name']}")
    if report.errors:
        lines.append("")
        lines.append(f"Errors ({len(report.errors)}):")
        lines.extend(f"  {section}: {message}" for section, message in report.errors.items())
    if report.skipped:
        lines.append("")
        lines.append(f"Not advertised by device: {', '.join(report.skipped)}")
    return "\n".join(lines)
