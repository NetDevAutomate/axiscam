"""Command-line interface for AXIS Camera Manager.

The application object lives in :mod:`axis_cam.cli.app`; each command group is
one module. Importing this package registers every command.

Usage:
    axiscam --help
    axiscam info --device camera1
    axiscam logs system --device camera1 --lines 50
"""

from axis_cam.cli import (  # noqa: F401  (imported for their command registrations)
    accounts,
    automation,
    config,
    device,
    download,
    logs,
    media,
    network,
    security,
    services,
    stream,
)
from axis_cam.cli.app import app, console, main, run_async
from axis_cam.cli.context import DeviceContext, get_device_class, resolve_device_config

__all__ = [
    "DeviceContext",
    "app",
    "console",
    "get_device_class",
    "main",
    "resolve_device_config",
    "run_async",
]
