"""Fleet fan-out: run one read-only operation against many configured devices.

``--all`` / ``--group NAME`` on a command selects targets from the config file
(:func:`axis_cam.cli.context.select_targets`); :func:`run_fleet` wraps the
library's :func:`axis_cam.fleet.run_fleet` with a console spinner. A device
that fails — wrong password, unreachable, an API it does not have — is one
row in the result, never the end of the run; the exit status says whether any
device failed.

Only read-only commands fan out. Writes stay one device at a time: the
write-safety pattern (plan → confirm → apply → verify) is per device by design.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

import typer

from axis_cam.cli.app import console, emit_json, run_async
from axis_cam.fleet import DEFAULT_CONCURRENCY, FleetResult, fleet_json
from axis_cam.fleet import run_fleet as _run_fleet

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from axis_cam.cli.context import DeviceContext
    from axis_cam.devices.base import AxisDevice

AllOption = Annotated[
    bool,
    typer.Option("--all", help="Run against every device in the config file."),
]
GroupOption = Annotated[
    str | None,
    typer.Option(
        "--group",
        "-g",
        help="Run against the configured devices in this group (a `groups:` tag or a device type).",
    ),
]
ConcurrencyOption = Annotated[
    int,
    typer.Option(
        "--concurrency",
        min=1,
        max=16,
        help="Devices worked on at once (fleet runs).",
        show_default=True,
    ),
]


def is_fleet(all_devices: bool, group: str | None) -> bool:
    """Whether ``--all`` or ``--group`` was given."""
    return all_devices or group is not None


async def run_fleet[T](
    targets: list[tuple[str, DeviceContext]],
    operation: Callable[[AxisDevice], Awaitable[T]],
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    label: str = "Working",
) -> list[FleetResult[T]]:
    """:func:`axis_cam.fleet.run_fleet` with a console spinner for progress."""
    with console.status(f"[bold blue]{label}: 0/{len(targets)} devices[/bold blue]") as status:
        return await _run_fleet(
            targets,
            operation,
            concurrency=concurrency,
            on_progress=lambda done, total: status.update(
                f"[bold blue]{label}: {done}/{total} devices[/bold blue]"
            ),
        )


def print_fleet_errors(results: list[FleetResult[Any]]) -> None:
    """One line per device that failed, after the main table."""
    failed = [r for r in results if not r.ok]
    if failed:
        console.print(f"[red]{len(failed)} device(s) failed:[/red]")
        for r in failed:
            console.print(f"  [red]{r.name}[/red] ({r.host}): {r.error}")


def finish_fleet(results: list[FleetResult[Any]], *, also_fail: bool = False) -> None:
    """Exit 1 when any device failed (or ``also_fail`` says the results themselves do)."""
    if any(not r.ok for r in results) or also_fail:
        raise typer.Exit(1)


def run_fleet_sync[T](
    targets: list[tuple[str, DeviceContext]],
    operation: Callable[[AxisDevice], Awaitable[T]],
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    label: str = "Working",
) -> list[FleetResult[T]]:
    """Synchronous wrapper for Typer command bodies."""
    return run_async(run_fleet(targets, operation, concurrency=concurrency, label=label))


__all__ = [
    "DEFAULT_CONCURRENCY",
    "AllOption",
    "ConcurrencyOption",
    "FleetResult",
    "GroupOption",
    "emit_json",
    "finish_fleet",
    "fleet_json",
    "is_fleet",
    "print_fleet_errors",
    "run_fleet",
    "run_fleet_sync",
]
