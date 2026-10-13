"""Typer option aliases shared by the device commands."""

from typing import Annotated

import typer

from axis_cam.auth import AuthMode

DeviceOption = Annotated[
    str | None,
    typer.Option(
        "--device",
        "-d",
        help="Device name from config or host address.",
    ),
]

HostOption = Annotated[
    str | None,
    typer.Option(
        "--host",
        "-H",
        help="Device IP address or hostname (overrides --device).",
    ),
]

UsernameOption = Annotated[
    str | None,
    typer.Option(
        "--username",
        "-u",
        help="Authentication username (override for config device).",
    ),
]

PasswordOption = Annotated[
    str | None,
    typer.Option(
        "--password",
        "-p",
        help="Authentication password (override for config device).",
    ),
]

PortOption = Annotated[
    int | None,
    typer.Option(
        "--port",
        "-P",
        help="TCP port. Defaults to the device's configured port, else 443.",
    ),
]

LinesOption = Annotated[
    int | None,
    typer.Option(
        "--lines",
        "-n",
        help="Number of log entries to show.",
    ),
]

AuthOption = Annotated[
    AuthMode,
    typer.Option(
        "--auth",
        help=(
            "Authentication scheme: auto (default) follows the device's challenge - Basic over "
            "HTTPS, Digest over HTTP; basic or digest forces one."
        ),
        case_sensitive=False,
    ),
]

JsonOption = Annotated[
    bool,
    typer.Option(
        "--json",
        "-j",
        help="Output in JSON format.",
    ),
]

YesOption = Annotated[
    bool,
    typer.Option(
        "--yes",
        "-y",
        help="Apply without asking for confirmation.",
    ),
]

DryRunOption = Annotated[
    bool,
    typer.Option(
        "--dry-run",
        help="Show the planned change and exit without applying it.",
    ),
]
