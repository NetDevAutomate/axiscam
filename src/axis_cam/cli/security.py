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
from axis_cam.cli.context import resolve_device_config, select_targets
from axis_cam.cli.fleet import (
    AllOption,
    ConcurrencyOption,
    FleetResult,
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


def _print_fleet_audit(results: list[FleetResult[AuditReport]]) -> None:
    """Checks as rows, devices as columns; only checks that fail or are unknown somewhere."""
    reports = [r for r in results if r.ok and r.value is not None]
    headline = Table(title="Security audit: fleet summary")
    for column in ("Device", "Product", "AXIS OS", "Failing", "Passing", "Unknown"):
        headline.add_column(column, style="cyan" if column == "Device" else "white")
    for r in results:
        if r.ok and r.value is not None:
            c = r.value.counts()
            headline.add_row(
                r.name,
                r.value.product or "-",
                r.value.firmware or "-",
                f"[bold red]{c['fail']}[/bold red]" if c["fail"] else "0",
                str(c["pass"]),
                f"[yellow]{c['unknown']}[/yellow]" if c["unknown"] else "0",
            )
        else:
            headline.add_row(r.name, "[red]error[/red]", "-", "-", "-", "-")
    console.print(headline)
    if not reports:
        return

    short = {
        Status.PASS: "[green]·[/green]",
        Status.FAIL: "[bold red]FAIL[/bold red]",
        Status.UNKNOWN: "[yellow]?[/yellow]",
        Status.NOT_APPLICABLE: "[dim]n/a[/dim]",
        Status.INFO: "[cyan]i[/cyan]",
    }
    by_device = {r.name: {f.check_id: f for f in r.value.findings} for r in reports if r.value}
    check_titles: dict[str, str] = {}
    for r in reports:
        for f in r.value.findings if r.value else []:
            check_titles.setdefault(f.check_id, f.title)
    rows = [
        cid
        for cid in check_titles
        if any(
            (f := by_device[d].get(cid)) is not None and f.status in (Status.FAIL, Status.UNKNOWN)
            for d in by_device
        )
    ]
    matrix = Table(
        title="Checks failing or unknown on at least one device (· pass, ? unknown)",
        caption="Check ids as in --json; `security audit --device NAME` for evidence and remedies.",
    )
    matrix.add_column("Check", style="cyan", no_wrap=True)
    for name in by_device:
        matrix.add_column(name, justify="center", no_wrap=True)
    for cid in rows:
        cells = [
            short[by_device[d][cid].status] if cid in by_device[d] else "[dim]-[/dim]"
            for d in by_device
        ]
        matrix.add_row(cid, *cells)
    console.print(matrix)


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
        bool, typer.Option("--show-all", "-a", help="Also list passing and n/a checks.")
    ] = False,
    no_fail: Annotated[
        bool,
        typer.Option("--no-fail", help="Exit 0 even when checks fail (for reporting pipelines)."),
    ] = False,
    all_devices: AllOption = False,
    group: GroupOption = None,
    concurrency: ConcurrencyOption = 4,
):
    """Audit a device — or the fleet (--all / --group) — against the AXIS OS Hardening Guide.

    Read-only. Each check reads a parameter or a REST API and says pass, FAIL,
    unknown (could not read — never counted as either), n/a (the product does
    not have the setting) or info. Exit status is 1 when any check fails or,
    for a fleet, any device could not be audited.
    """
    if is_fleet(all_devices, group):
        targets = select_targets(
            all_devices=all_devices,
            group=group,
            username=username,
            password=password,
            port=port,
            auth_mode=auth,
        )
        names = {ctx.host: name for name, ctx in targets}

        async def _audit_one(dev) -> AuditReport:
            return await run_audit(dev, device_name=names.get(dev.client.host, dev.client.host))

        results = run_fleet_sync(targets, _audit_one, concurrency=concurrency, label="Auditing")
        if json_output:
            emit_json(fleet_json(results, lambda report: report.to_dict()))
        else:
            _print_fleet_audit(results)
            print_fleet_errors(results)
        any_failing = any(
            r.ok and r.value is not None and r.value.by_status(Status.FAIL) for r in results
        )
        finish_fleet(results, also_fail=any_failing and not no_fail)
        return

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
