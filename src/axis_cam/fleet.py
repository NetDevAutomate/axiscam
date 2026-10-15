"""Run one read-only operation against many devices — no console.

:func:`run_fleet` opens each target and runs the operation with bounded
concurrency. A device that fails — wrong password, unreachable, an API it does
not have, a timeout — is one row in the result, never the end of the run. A
bug in the operation itself propagates: it must not be reported as a device
failure.

Progress is reported through ``on_progress(done, total)`` so a CLI can drive a
spinner and an MCP server can stay silent: on stdio, a stray console write is
a corrupted JSON-RPC frame.

Only read-only operations fan out. Writes stay one device at a time: the
write-safety pattern (plan → confirm → apply → verify) is per device by design.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from axis_cam.exceptions import AxisError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from axis_cam.devices.base import AxisDevice


class Openable(Protocol):
    """A fleet target: an address to report and a way to open the device.

    :class:`axis_cam.connection.DeviceConnection` is one; the MCP server
    passes a small adapter over its device resolver.
    """

    @property
    def host(self) -> str:
        """Address shown in the result row."""
        ...

    def open(self) -> AxisDevice:
        """A fresh device object (an async context manager)."""
        ...


#: How many devices are worked on at once. Cameras are small computers; a
#: full report or backup per device is real work for them.
DEFAULT_CONCURRENCY = 4


@dataclass(frozen=True)
class FleetResult[T]:
    """One device's outcome: a value, or the error that stood in for it."""

    name: str
    host: str
    value: T | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True when the operation returned a value."""
        return self.error is None


async def run_fleet[T](
    targets: Sequence[tuple[str, Openable]],
    operation: Callable[[AxisDevice], Awaitable[T]],
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: float | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[FleetResult[T]]:
    """Open each target and run ``operation`` on it, ``concurrency`` at a time.

    Args:
        targets: ``(name, connection)`` pairs, in the order results are wanted.
        operation: Coroutine function run against each open device.
        concurrency: Devices worked on at once.
        timeout: Seconds allowed per device (open + operation); ``None`` for
            no limit. A device that overruns gets a ``timed out`` error row.
        on_progress: Called with ``(done, total)`` after each device finishes.

    Returns:
        One result per target, in target order. ``AxisError`` subclasses,
        ``OSError`` and timeouts become the device's ``error``; anything else
        propagates.
    """
    semaphore = asyncio.Semaphore(concurrency)
    total = len(targets)
    done = 0

    async def one(name: str, conn: Openable) -> FleetResult[T]:
        nonlocal done
        async with semaphore:
            try:
                async with asyncio.timeout(timeout):
                    async with conn.open() as dev:
                        value = await operation(dev)
                result: FleetResult[T] = FleetResult(name=name, host=conn.host, value=value)
            except TimeoutError:
                result = FleetResult(
                    name=name, host=conn.host, error=f"timed out after {timeout:g} s"
                )
            except (AxisError, OSError) as exc:
                result = FleetResult(
                    name=name, host=conn.host, error=str(exc) or type(exc).__name__
                )
            done += 1
            if on_progress is not None:
                on_progress(done, total)
            return result

    return list(await asyncio.gather(*(one(name, conn) for name, conn in targets)))


def fleet_json(
    results: Sequence[FleetResult[Any]], to_dict: Callable[[Any], Any]
) -> dict[str, Any]:
    """``{"devices": {name: {"host", "ok", "result" | "error"}}, "failed": [...]}``."""
    return {
        "devices": {
            r.name: {
                "host": r.host,
                "ok": r.ok,
                **({"result": to_dict(r.value)} if r.ok else {"error": r.error}),
            }
            for r in results
        },
        "failed": [r.name for r in results if not r.ok],
    }


__all__ = ["DEFAULT_CONCURRENCY", "FleetResult", "Openable", "fleet_json", "run_fleet"]
