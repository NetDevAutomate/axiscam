"""``axiscam security``: firewall, SSH, certificates — and the hardening audit."""

from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from axis_cam.audit import GUIDE_URL, AuditReport, Status, run_audit
from axis_cam.auth import AuthMode
from axis_cam.cli.app import (
    console,
    emit_json,
    run_async,
    security_app,
)
from axis_cam.cli.context import resolve_device_config
from axis_cam.cli.options import (
    AuthOption,
    DeviceOption,
    HostOption,
    PasswordOption,
    PortOption,
    UsernameOption,
)
from axis_cam.models import Certificate, FirewallPolicy

JsonFlag = Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")]


def _on_off(value: bool | None, *, on: str = "Enabled", off: str = "Disabled") -> str:
    if value is None:
        return "[dim]not reported[/dim]"
    return f"[green]{on}[/green]" if value else f"[red]{off}[/red]"


@security_app.command("firewall")
def security_firewall(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    json_output: JsonFlag = False,
):
    """Show firewall state: activated, default policy, active and pending rules."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _show_firewall():
        async with target.open() as dev:
            config = await dev.firewall.read()
            if json_output:
                emit_json(config.model_dump(mode="json"))
                return

            policy_colour = "green" if config.default_policy is FirewallPolicy.DROP else "yellow"
            lines = [
                f"Activated: {_on_off(config.activated, on='Yes', off='No')}",
                f"Default policy: [{policy_colour}]{config.default_policy.value}[/{policy_colour}]",
            ]
            if config.test_time_left:
                lines.append(f"Test mode: {config.test_time_left}s left")
            console.print(Panel("\n".join(lines), title=f"Firewall: {target.host}"))

            for title, rules in (
                (f"Active rules ({len(config.rules)})", config.rules),
                (f"Pending rules ({len(config.pending_rules)})", config.pending_rules),
            ):
                if not rules:
                    continue
                table = Table(title=title)
                table.add_column("Type", style="cyan")
                table.add_column("Match", style="white")
                table.add_column("Limit", style="white")
                for rule in rules:
                    match = " ".join(
                        filter(None, (rule.ip, rule.ip_range, rule.mac, rule.port, rule.port_range))
                    )
                    table.add_row(rule.rule_type, match or "any", rule.limit or "-")
                console.print(table)
            if not config.rules and not config.pending_rules:
                console.print("[yellow]No firewall rules configured[/yellow]")

    run_async(_show_firewall())


@security_app.command("ssh")
def security_ssh(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    json_output: JsonFlag = False,
):
    """Show SSH state: enabled (Network.SSH.Enabled) and the SSH users."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _show_ssh():
        async with target.open() as dev:
            config = await dev.ssh.read()
            if json_output:
                emit_json(config.model_dump(mode="json"))
                return

            console.print(
                Panel(
                    f"Status: {_on_off(config.enabled)}\nSSH users: {len(config.users)}",
                    title=f"SSH Configuration: {target.host}",
                )
            )
            if config.users:
                table = Table(title=f"SSH users ({len(config.users)})")
                table.add_column("Username", style="cyan")
                table.add_column("Comment", style="white")
                for user in config.users:
                    table.add_row(user.username, user.comment or "-")
                console.print(table)

    run_async(_show_ssh())


def _cert_row(cert: Certificate) -> tuple[str, ...]:
    valid_to = cert.not_after.strftime("%Y-%m-%d") if cert.not_after else "-"
    if cert.not_after is None:
        status = "[dim]unparsed[/dim]"
    elif cert.expires_within(0):
        status = "[red]expired[/red]"
    elif cert.expires_within(90):
        status = "[yellow]expires soon[/yellow]"
    else:
        status = "[green]valid[/green]"
    subject = cert.subject if len(cert.subject) <= 40 else cert.subject[:37] + "..."
    return (
        cert.alias,
        subject or "-",
        "self-signed" if cert.self_signed else ("CA" if cert.is_ca else "issued"),
        cert.key_type or "-",
        cert.keystore or "-",
        valid_to,
        status,
    )


@security_app.command("certs")
def security_certs(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    json_output: JsonFlag = False,
):
    """Show the certificate store: device certificates, CA certificates, keystores."""
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _show_certs():
        async with target.open() as dev:
            config = await dev.cert.read()
            if json_output:
                emit_json(config.model_dump(mode="json"))
                return

            stores = ", ".join(f"{k.id} ({k.security_level})" for k in config.keystores) or "-"
            console.print(
                Panel(
                    f"Default keystore: [cyan]{config.default_keystore or '-'}[/cyan]\n"
                    f"Keystores: {stores}\n"
                    f"Device certificates: {len(config.certificates)}   "
                    f"CA certificates: {len(config.ca_certificates)}",
                    title=f"Certificates: {target.host}",
                )
            )
            if config.certificates:
                table = Table(title=f"Device certificates ({len(config.certificates)})")
                for column in ("Alias", "Subject", "Kind", "Key", "Keystore", "Valid to", "Status"):
                    table.add_column(column, style="cyan" if column == "Alias" else "white")
                for cert in config.certificates:
                    table.add_row(*_cert_row(cert))
                console.print(table)
            else:
                console.print("[yellow]No device certificates[/yellow]")

    run_async(_show_certs())


_STATUS_STYLE = {
    Status.PASS: "[green]pass[/green]",
    Status.FAIL: "[bold red]FAIL[/bold red]",
    Status.UNKNOWN: "[yellow]unknown[/yellow]",
    Status.NOT_APPLICABLE: "[dim]n/a[/dim]",
    Status.INFO: "[cyan]info[/cyan]",
}


def _print_audit(report: AuditReport, *, show_passing: bool) -> None:
    counts = report.counts()
    headline = (
        f"[bold red]{counts['fail']} failing[/bold red]  "
        f"[green]{counts['pass']} passing[/green]  "
        f"[yellow]{counts['unknown']} unknown[/yellow]  "
        f"[dim]{counts['n/a']} n/a[/dim]  [cyan]{counts['info']} info[/cyan]"
    )
    console.print(
        Panel(
            f"{report.product or '-'} · AXIS OS {report.firmware or '-'}\n{headline}\n"
            f"[dim]Reference: AXIS OS Hardening Guide ({GUIDE_URL})[/dim]",
            title=f"Security audit: {report.device_name}",
        )
    )
    order = [Status.FAIL, Status.UNKNOWN, Status.INFO] + (
        [Status.PASS, Status.NOT_APPLICABLE] if show_passing else []
    )
    table = Table(show_lines=False)
    table.add_column("Status", style="white", no_wrap=True)
    table.add_column("Sev", style="white", no_wrap=True)
    table.add_column("Check", style="cyan", overflow="fold")
    table.add_column("Evidence", style="white", overflow="fold")
    table.add_column("Recommendation", style="white", overflow="fold")
    for status in order:
        for f in report.by_status(status):
            table.add_row(
                _STATUS_STYLE[f.status], f.severity.value, f.title, f.evidence, f.recommendation
            )
    console.print(table)
    if not show_passing:
        console.print("[dim]Passing and n/a checks hidden; --all shows them.[/dim]")


@security_app.command("audit")
def security_audit(
    device: DeviceOption = None,
    host: HostOption = None,
    username: UsernameOption = None,
    password: PasswordOption = None,
    port: PortOption = None,
    auth: AuthOption = AuthMode.AUTO,
    json_output: JsonFlag = False,
    show_all: Annotated[
        bool, typer.Option("--all", "-a", help="Also list passing and n/a checks.")
    ] = False,
    no_fail: Annotated[
        bool,
        typer.Option("--no-fail", help="Exit 0 even when checks fail (for reporting pipelines)."),
    ] = False,
):
    """Audit the device against the AXIS OS Hardening Guide. Read-only.

    Each check reads a parameter or a REST API and says pass, FAIL, unknown
    (could not read — never counted as either), n/a (the product does not have
    the setting) or info. Exit status is 1 when any check fails.
    """
    target = resolve_device_config(device, host, username, password, port, auth_mode=auth)

    async def _audit() -> AuditReport:
        async with target.open() as dev:
            return await run_audit(dev, device_name=device or target.host)

    report = run_async(_audit())
    if json_output:
        emit_json(report.to_dict())
    else:
        _print_audit(report, show_passing=show_all)
    if report.by_status(Status.FAIL) and not no_fail:
        raise typer.Exit(1)
