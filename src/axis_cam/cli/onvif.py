"""``axiscam onvif``: manage ONVIF user accounts.

ONVIF users are a separate database from the VAPIX accounts ``axiscam
accounts`` manages; a VMS or NVR speaking ONVIF authenticates against this
list. Every change follows :mod:`axis_cam.cli.confirm`: read the current
users, show the plan, stop on ``--dry-run``, confirm (``--yes`` skips the
prompt), apply, verify, print the verified result. Passwords come from a
hidden prompt or ``--password-stdin``, never from the command line.
"""

from typing import Annotated

import typer
from rich.table import Table

from axis_cam.api.onvif_users import validate_onvif_password, validate_onvif_username
from axis_cam.auth import AuthMode
from axis_cam.cli.app import console, emit_json, onvif_app, run_async
from axis_cam.cli.confirm import WritePlan, confirm_write, read_secret
from axis_cam.cli.context import resolve_device_config, select_targets
from axis_cam.cli.fleet import (
    AllOption,
    ConcurrencyOption,
    GroupOption,
    finish_fleet,
    fleet_json,
    is_fleet,
    print_fleet_errors,
    run_fleet_sync,
)
from axis_cam.cli.options import (
    AuthOption,
    DeviceOption,
    DryRunOption,
    HostOption,
    JsonOption,
    PasswordOption,
    PortOption,
    UsernameOption,
    YesOption,
)
from axis_cam.models import OnvifAccount, OnvifAccounts, OnvifUserLevel


def _check_username(value: str) -> str:
    try:
        validate_onvif_username(value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    return value


OnvifUserArgument = Annotated[
    str,
    typer.Argument(help="ONVIF user name.", callback=_check_username),
]
LevelOption = Annotated[
    OnvifUserLevel,
    typer.Option(
        "--level", "-l", help="Access level: Administrator, Operator or User.", case_sensitive=False
    ),
]
PasswordStdinOption = Annotated[
    bool,
    typer.Option(
        "--password-stdin",
        help="Read the ONVIF user's password from standard input instead of prompting.",
    ),
]
AllowLockoutOption = Annotated[
    bool,
    typer.Option(
        "--allow-lockout",
        help="Permit removing or demoting the only ONVIF Administrator.",
    ),
]


def _describe(account: OnvifAccount) -> str:
    return f"{account.username} ({account.level.value})"


def _context(accounts: OnvifAccounts) -> tuple[str, ...]:
    listed = ", ".join(_describe(a) for a in accounts.accounts) or "none"
    return (f"{len(accounts.accounts)} ONVIF user(s): {listed}",)


def _last_admin_warning(
    accounts: OnvifAccounts, target: OnvifAccount, verb: str
) -> tuple[str, ...]:
    if target.level is not OnvifUserLevel.ADMINISTRATOR:
        return ()
    others = [a for a in accounts.administrators if a.username != target.username]
    if others:
        return ()
    return (
        f"'{target.username}' is the only ONVIF Administrator; {verb} it leaves ONVIF "
        "clients without administrative access — refused without --allow-lockout",
    )


def _print_accounts(accounts: OnvifAccounts, host: str) -> None:
    table = Table(title=f"ONVIF users: {host}")
    table.add_column("Username", style="cyan")
    table.add_column("Level", style="white")
    for account in accounts.accounts:
        level = account.level.value
        if account.level is OnvifUserLevel.ADMINISTRATOR:
            level = f"[bold red]{level}[/bold red]"
        table.add_row(account.username, level)
    if not accounts.accounts:
        table.add_row("[dim]none[/dim]", "")
    console.print(table)


def _new_password(from_stdin: bool, label: str = "New ONVIF password") -> str:
    password = read_secret(label, from_stdin=from_stdin)
    try:
        validate_onvif_password(password)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}", style="bold")
        raise typer.Exit(1) from None
    return password


def _missing(user: str) -> None:
    console.print(f"[red]Error:[/red] ONVIF user '{user}' does not exist", style="bold")
    raise typer.Exit(1)


@onvif_app.command("list")
def onvif_list(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    json_output: JsonOption = False,
    all_devices: AllOption = False,
    group: GroupOption = None,
    concurrency: ConcurrencyOption = 4,
):
    """List ONVIF users with their levels — one device, or the fleet (--all / --group)."""
    if is_fleet(all_devices, group):
        targets = select_targets(
            all_devices=all_devices,
            group=group,
            username=username,
            password=password,
            port=port,
            auth_mode=auth,
        )
        results = run_fleet_sync(
            targets, lambda dev: dev.onvif_users.list(), concurrency=concurrency, label="Reading"
        )
        if json_output:
            emit_json(fleet_json(results, lambda users: users.model_dump(mode="json")))
        else:
            table = Table(title="Fleet ONVIF users")
            for column in ("Device", "Administrators", "Operators", "Users"):
                table.add_column(
                    column, style="cyan" if column == "Device" else "white", overflow="fold"
                )
            for r in results:
                if r.ok and r.value is not None:
                    by_level = {
                        level: ", ".join(u.username for u in r.value.accounts if u.level is level)
                        or "-"
                        for level in (
                            OnvifUserLevel.ADMINISTRATOR,
                            OnvifUserLevel.OPERATOR,
                            OnvifUserLevel.USER,
                        )
                    }
                    table.add_row(
                        r.name,
                        f"[bold red]{by_level[OnvifUserLevel.ADMINISTRATOR]}[/bold red]",
                        by_level[OnvifUserLevel.OPERATOR],
                        by_level[OnvifUserLevel.USER],
                    )
                else:
                    table.add_row(r.name, "[red]error[/red]", "-", "-")
            console.print(table)
            print_fleet_errors(results)
        finish_fleet(results)
        return

    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _list() -> OnvifAccounts:
        async with target.open() as dev:
            return await dev.onvif_users.list()

    accounts = run_async(_list())
    if json_output:
        emit_json(accounts.model_dump(mode="json"))
    else:
        _print_accounts(accounts, target.host)


@onvif_app.command("add")
def onvif_add(
    user: OnvifUserArgument,
    level: LevelOption,
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    password_stdin: PasswordStdinOption = False,
    yes: YesOption = False,
    dry_run: DryRunOption = False,
):
    """Create an ONVIF user. The password is prompted for, never passed on the command line."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)
    new_password = _new_password(True) if password_stdin else None

    async def _add() -> None:
        nonlocal new_password
        async with target.open() as dev:
            current = await dev.onvif_users.list()
            if current.get(user) is not None:
                console.print(f"[red]Error:[/red] ONVIF user '{user}' already exists", style="bold")
                raise typer.Exit(1)
            plan = WritePlan(
                target=target.host,
                action=f"Create ONVIF user '{user}' with level {level.value}",
                context=_context(current),
            )
            if not confirm_write(plan, yes=yes, dry_run=dry_run):
                return
            if new_password is None:
                new_password = _new_password(False)
            created = await dev.onvif_users.add(user, new_password, level)
            console.print(f"[green]Created and verified:[/green] {_describe(created)}")

    run_async(_add())


@onvif_app.command("set-password")
def onvif_set_password(
    user: OnvifUserArgument,
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    password_stdin: PasswordStdinOption = False,
    yes: YesOption = False,
    dry_run: DryRunOption = False,
):
    """Change an ONVIF user's password (rotate the credentials a VMS uses)."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)
    new_password = _new_password(True) if password_stdin else None

    async def _set_password() -> None:
        nonlocal new_password
        async with target.open() as dev:
            current = await dev.onvif_users.list()
            existing = current.get(user)
            if existing is None:
                _missing(user)
                return
            plan = WritePlan(
                target=target.host,
                action=f"Change the password of ONVIF user {_describe(existing)}",
                context=_context(current),
                warnings=(
                    "every ONVIF client using this user (VMS, NVR, Home Assistant) must be "
                    "updated or it will lose the stream",
                ),
            )
            if not confirm_write(plan, yes=yes, dry_run=dry_run):
                return
            if new_password is None:
                new_password = _new_password(False)
            await dev.onvif_users.set_password(user, new_password)
            console.print(
                f"[green]Password changed:[/green] {user}. The device accepted the change; "
                "ONVIF never returns passwords, so verify by connecting the client."
            )

    run_async(_set_password())


@onvif_app.command("set-level")
def onvif_set_level(
    user: OnvifUserArgument,
    level: LevelOption,
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    password_stdin: PasswordStdinOption = False,
    allow_lockout: AllowLockoutOption = False,
    yes: YesOption = False,
    dry_run: DryRunOption = False,
):
    """Change an ONVIF user's level. The device requires the user's password with the change.

    Enter the current password to keep the user's ONVIF clients working, or a
    new one to rotate it in the same step. It is prompted for, never passed on
    the command line.
    """
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)
    user_password = _new_password(True, "ONVIF user password") if password_stdin else None

    async def _set_level() -> None:
        nonlocal user_password
        async with target.open() as dev:
            current = await dev.onvif_users.list()
            existing = current.get(user)
            if existing is None:
                _missing(user)
                return
            warnings = (
                _last_admin_warning(current, existing, "demoting")
                if level is not OnvifUserLevel.ADMINISTRATOR
                else ()
            )
            plan = WritePlan(
                target=target.host,
                action=f"Change ONVIF user {_describe(existing)} to level {level.value}",
                context=(
                    *_context(current),
                    "the device requires the user's password with a level change; "
                    "the current one keeps ONVIF clients working, a new one rotates it",
                ),
                warnings=warnings,
            )
            if not confirm_write(plan, yes=yes, dry_run=dry_run):
                return
            if user_password is None:
                user_password = _new_password(False, "ONVIF user password (current or new)")
            updated = await dev.onvif_users.set_level(
                user, level, user_password, allow_lockout=allow_lockout
            )
            console.print(f"[green]Updated and verified:[/green] {_describe(updated)}")

    run_async(_set_level())


@onvif_app.command("remove")
def onvif_remove(
    user: OnvifUserArgument,
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    allow_lockout: AllowLockoutOption = False,
    yes: YesOption = False,
    dry_run: DryRunOption = False,
):
    """Remove an ONVIF user."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _remove() -> None:
        async with target.open() as dev:
            current = await dev.onvif_users.list()
            existing = current.get(user)
            if existing is None:
                _missing(user)
                return
            plan = WritePlan(
                target=target.host,
                action=f"Remove ONVIF user {_describe(existing)}",
                context=_context(current),
                warnings=_last_admin_warning(current, existing, "removing"),
            )
            if not confirm_write(plan, yes=yes, dry_run=dry_run):
                return
            await dev.onvif_users.remove(user, allow_lockout=allow_lockout)
            console.print(f"[green]Removed and verified:[/green] {user} is no longer listed")

    run_async(_remove())
