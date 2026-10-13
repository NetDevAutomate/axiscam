"""``axiscam accounts``: manage VAPIX user accounts.

Every change goes through :mod:`axis_cam.cli.confirm`: the current accounts
are read, the planned change is shown, ``--dry-run`` stops there, otherwise
the change is confirmed (``--yes`` skips the prompt), applied, verified by the
library and the verified result printed. New passwords come from a hidden
prompt or ``--password-stdin``, never from the command line.
"""

from typing import Annotated

import typer
from rich.table import Table

from axis_cam.api.users import validate_password, validate_username
from axis_cam.auth import AuthMode
from axis_cam.cli.app import accounts_app, console, emit_json, run_async
from axis_cam.cli.confirm import WritePlan, confirm_write, read_secret
from axis_cam.cli.context import DeviceContext, resolve_device_config
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
from axis_cam.models import UserAccount, UserAccounts, UserRole


def _check_username(value: str) -> str:
    try:
        validate_username(value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None
    return value


AccountArgument = Annotated[
    str,
    typer.Argument(
        help="Account name (1-14 characters, A-Z a-z 0-9).",
        callback=_check_username,
    ),
]
RoleOption = Annotated[
    UserRole,
    typer.Option("--role", "-r", help="Access role.", case_sensitive=False),
]
PtzOption = Annotated[
    bool,
    typer.Option("--ptz/--no-ptz", help="Grant PTZ control."),
]
PasswordStdinOption = Annotated[
    bool,
    typer.Option(
        "--password-stdin",
        help="Read the new account password from standard input instead of prompting.",
    ),
]
NoStrictOption = Annotated[
    bool,
    typer.Option(
        "--no-strict",
        help="Do not ask the device to enforce its passphrase policy (strict_pwd).",
    ),
]
AllowLockoutOption = Annotated[
    bool,
    typer.Option(
        "--allow-lockout",
        help="Permit removing or de-admining the account you are logged in as.",
    ),
]


def _describe(account: UserAccount) -> str:
    role = account.role.value if account.role else "no role"
    return f"{account.username} ({role}{', ptz' if account.ptz else ''})"


def _context(accounts: UserAccounts) -> tuple[str, ...]:
    listed = ", ".join(_describe(a) for a in accounts.accounts) or "none"
    return (f"{len(accounts.accounts)} account(s): {listed}",)


def _self_warning(ctx: DeviceContext, username: str, consequence: str) -> tuple[str, ...]:
    if username == ctx.username:
        return (f"'{username}' is the account this command is logged in as; {consequence}",)
    return ()


def _print_accounts(accounts: UserAccounts, host: str) -> None:
    table = Table(title=f"Accounts: {host}")
    table.add_column("Username", style="cyan")
    table.add_column("Role", style="white")
    table.add_column("PTZ", style="white")
    for account in accounts.accounts:
        role = account.role.value if account.role else "[dim]none[/dim]"
        if account.role is UserRole.ADMIN:
            role = f"[bold red]{role}[/bold red]"
        table.add_row(account.username, role, "yes" if account.ptz else "-")
    console.print(table)


def _new_password(from_stdin: bool, strict: bool) -> str:
    password = read_secret("New password", from_stdin=from_stdin)
    try:
        validate_password(password, strict=strict)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}", style="bold")
        raise typer.Exit(1) from None
    return password


@accounts_app.command("list")
def accounts_list(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    json_output: JsonOption = False,
):
    """List user accounts with their roles."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _list() -> UserAccounts:
        async with target.open() as dev:
            return await dev.users.list()

    accounts = run_async(_list())
    if json_output:
        emit_json(accounts.model_dump(mode="json"))
    else:
        _print_accounts(accounts, target.host)


@accounts_app.command("add")
def accounts_add(
    account: AccountArgument,
    role: RoleOption,
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    ptz: PtzOption = False,
    comment: Annotated[
        str, typer.Option("--comment", help="Description stored on the device.")
    ] = "",
    password_stdin: PasswordStdinOption = False,
    no_strict: NoStrictOption = False,
    yes: YesOption = False,
    dry_run: DryRunOption = False,
):
    """Create a user account. The new password is prompted for, never passed on the command line."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)
    # Non-interactive input is consumed before anything else so a failure is immediate.
    new_password = _new_password(True, not no_strict) if password_stdin else None

    async def _add() -> None:
        nonlocal new_password
        async with target.open() as dev:
            current = await dev.users.list()
            if current.get(account) is not None:
                console.print(f"[red]Error:[/red] account '{account}' already exists", style="bold")
                raise typer.Exit(1)
            plan = WritePlan(
                target=target.host,
                action=(
                    f"Create account '{account}' with role {role.value}"
                    f"{' and PTZ control' if ptz else ''}"
                ),
                context=_context(current),
            )
            if not confirm_write(plan, yes=yes, dry_run=dry_run):
                return
            if new_password is None:
                new_password = _new_password(False, not no_strict)
            created = await dev.users.add(
                account,
                new_password,
                role,
                ptz=ptz,
                comment=comment,
                strict_password=not no_strict,
            )
            console.print(f"[green]Created and verified:[/green] {_describe(created)}")

    run_async(_add())


@accounts_app.command("set-password")
def accounts_set_password(
    account: AccountArgument,
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    password_stdin: PasswordStdinOption = False,
    no_strict: NoStrictOption = False,
    yes: YesOption = False,
    dry_run: DryRunOption = False,
):
    """Change an account's password (rotate credentials)."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)
    new_password = _new_password(True, not no_strict) if password_stdin else None

    async def _set_password() -> None:
        nonlocal new_password
        async with target.open() as dev:
            current = await dev.users.list()
            existing = current.get(account)
            if existing is None:
                console.print(f"[red]Error:[/red] account '{account}' does not exist", style="bold")
                raise typer.Exit(1)
            plan = WritePlan(
                target=target.host,
                action=f"Change the password of {_describe(existing)}",
                context=_context(current),
                warnings=_self_warning(
                    target,
                    account,
                    "update the config file or the next command will fail to authenticate",
                ),
            )
            if not confirm_write(plan, yes=yes, dry_run=dry_run):
                return
            if new_password is None:
                new_password = _new_password(False, not no_strict)
            await dev.users.set_password(account, new_password, strict_password=not no_strict)
            console.print(
                f"[green]Password changed:[/green] {account}. The device acknowledged the change; "
                "a password cannot be verified by reading, so test it by logging in."
            )

    run_async(_set_password())


@accounts_app.command("set-role")
def accounts_set_role(
    account: AccountArgument,
    role: RoleOption,
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    ptz: PtzOption = False,
    allow_lockout: AllowLockoutOption = False,
    yes: YesOption = False,
    dry_run: DryRunOption = False,
):
    """Change an account's role."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _set_role() -> None:
        async with target.open() as dev:
            current = await dev.users.list()
            existing = current.get(account)
            if existing is None:
                console.print(f"[red]Error:[/red] account '{account}' does not exist", style="bold")
                raise typer.Exit(1)
            plan = WritePlan(
                target=target.host,
                action=(
                    f"Change {_describe(existing)} to role {role.value}"
                    f"{' with PTZ control' if ptz else ' without PTZ control'}"
                ),
                context=_context(current),
                warnings=_lockout_warnings(
                    target, current, existing, operation="set-role", new_role=role
                ),
            )
            if not confirm_write(plan, yes=yes, dry_run=dry_run):
                return
            updated = await dev.users.set_role(account, role, ptz=ptz, allow_lockout=allow_lockout)
            console.print(f"[green]Updated and verified:[/green] {_describe(updated)}")

    run_async(_set_role())


@accounts_app.command("remove")
def accounts_remove(
    account: AccountArgument,
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
    """Remove a user account."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _remove() -> None:
        async with target.open() as dev:
            current = await dev.users.list()
            existing = current.get(account)
            if existing is None:
                console.print(f"[red]Error:[/red] account '{account}' does not exist", style="bold")
                raise typer.Exit(1)
            plan = WritePlan(
                target=target.host,
                action=f"Remove {_describe(existing)}",
                context=_context(current),
                warnings=_lockout_warnings(target, current, existing, operation="remove"),
            )
            if not confirm_write(plan, yes=yes, dry_run=dry_run):
                return
            await dev.users.remove(account, allow_lockout=allow_lockout)
            console.print(f"[green]Removed and verified:[/green] {account} is no longer listed")

    run_async(_remove())


def _lockout_warnings(
    ctx: DeviceContext,
    accounts: UserAccounts,
    target: UserAccount,
    *,
    operation: str,
    new_role: UserRole | None = None,
) -> tuple[str, ...]:
    """Say up front what the library's lockout guard will refuse.

    ``remove`` of any account you are logged in as, and loss of administrator
    access for yourself, need ``--allow-lockout``; removing or de-admining the
    only administrator is refused outright.
    """
    is_self = target.username == ctx.username
    loses_admin = target.role is UserRole.ADMIN and (
        operation == "remove" or new_role is not UserRole.ADMIN
    )
    if loses_admin:
        others = [a for a in accounts.admins if a.username != target.username]
        if not others:
            return (
                f"'{target.username}' is the only administrator; the device will refuse "
                "this (add another administrator first)",
            )
        if is_self:
            return (
                f"'{target.username}' is the account this command is logged in as and would "
                "lose administrator access; refused without --allow-lockout",
            )
        return ()
    if operation == "remove" and is_self:
        return (
            f"'{target.username}' is the account this command is logged in as; "
            "refused without --allow-lockout",
        )
    return ()
