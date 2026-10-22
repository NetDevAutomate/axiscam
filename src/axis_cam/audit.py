"""Security audit against the AXIS OS Hardening Guide.

Every check is a composition of things the library already reads: the
parameter tree (``param.cgi``) and the REST readers (SSH, firewall, SNMP,
crypto policy, certificates, NTP, accounts, ONVIF users, device info). The
audit itself writes nothing.

The reference is the AXIS OS Hardening Guide (``help.axis.com/en-us/axis-os-
hardening-guide``, July 2026 edition, fetched 2026-10-13). Its "Basic hardening
via VAPIX API" table names a parameter and a hardened value for each basic
recommendation; those are the ``PARAM_CHECKS`` below, quoted as the guide gives
them. The remaining checks (accounts, TLS, syslog, SNMP, NTP, certificates,
firmware) follow the guide's prose sections named in each check's ``reference``.

Three results are possible for a check, and the third is the one that matters
most for an audit: **pass**, **fail**, and **unknown** — the device did not
expose the setting, or reading it failed. "Could not read" is never reported as
either pass or fail. A parameter the guide names but the product does not have
(``Network.FTP.Enabled`` on AXIS OS 12, which removed FTP) is ``not applicable``:
the recommendation is satisfied by the setting's absence.
"""

from __future__ import annotations

import asyncio
import functools
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

from axis_cam.exceptions import (
    AxisApiNotSupportedError,
    AxisAuthenticationError,
    AxisConnectionError,
    AxisDeviceError,
    AxisPermissionError,
)
from axis_cam.models import OnvifUserLevel, UserRole
from axis_cam.secrets import error_excerpt

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from axis_cam.devices.base import AxisDevice

GUIDE_URL = "https://help.axis.com/en-us/axis-os-hardening-guide"

#: Service accounts Axis software creates; their presence is expected, not a finding.
KNOWN_SERVICE_ACCOUNTS: frozenset[str] = frozenset(
    {"AxisDeviceMgmt", "webrtcacapuser", "StreamStorage", "ACCAdmin", "axisconnect"}
)

#: Days before expiry at which a device certificate is reported.
CERT_EXPIRY_WARNING_DAYS = 90


class Status(str, Enum):
    """Outcome of one check."""

    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"  # could not read, or the device does not expose the setting
    NOT_APPLICABLE = "n/a"  # the product does not have the setting; nothing to harden
    INFO = "info"  # reported for the record, no recommendation attached


class Severity(str, Enum):
    """How much a failing check matters, per the guide's framing."""

    HIGH = "high"  # credentials or control exposed (plain HTTP, anonymous, default community)
    MEDIUM = "medium"  # attack surface the guide says to remove after commissioning
    LOW = "low"  # hygiene (server banners, access log)
    INFO = "info"


@dataclass(frozen=True)
class Finding:
    """One check's result.

    Attributes:
        check_id: Stable identifier (``discovery.bonjour``).
        title: What is being checked, in the guide's words.
        status: Outcome.
        severity: Weight of a failure.
        evidence: What was read (``Network.Bonjour.Enabled=yes``), or why it could not be.
        recommendation: What to change, usually the guide's own VAPIX call.
        reference: Section of the hardening guide.
    """

    check_id: str
    title: str
    status: Status
    severity: Severity
    evidence: str = ""
    recommendation: str = ""
    reference: str = ""


@dataclass
class AuditReport:
    """All findings for one device, with the counts a reader needs first."""

    host: str
    device_name: str
    generated_at: str
    product: str = ""
    firmware: str = ""
    findings: list[Finding] = field(default_factory=list)

    def by_status(self, status: Status) -> list[Finding]:
        """Findings with ``status``."""
        return [f for f in self.findings if f.status is status]

    def counts(self) -> dict[str, int]:
        """``{status: count}`` for every status."""
        return {s.value: len(self.by_status(s)) for s in Status}

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {
            "host": self.host,
            "device_name": self.device_name,
            "generated_at": self.generated_at,
            "product": self.product,
            "firmware": self.firmware,
            "guide": GUIDE_URL,
            "counts": self.counts(),
            "findings": [
                {
                    "id": f.check_id,
                    "title": f.title,
                    "status": f.status.value,
                    "severity": f.severity.value,
                    "evidence": f.evidence,
                    "recommendation": f.recommendation,
                    "reference": f.reference,
                }
                for f in self.findings
            ],
        }


# --- parameter checks: the guide's "Basic hardening via VAPIX API" table ---------


@dataclass(frozen=True)
class ParamCheck:
    """A parameter the guide names, and the value it asks for."""

    check_id: str
    title: str
    param: str  # without ``root.``
    hardened: tuple[str, ...]  # acceptable values (case-insensitive)
    severity: Severity
    reference: str
    #: Products without the parameter satisfy the recommendation by absence.
    absent_is_na: bool = True


PARAM_CHECKS: tuple[ParamCheck, ...] = (
    ParamCheck(
        "discovery.bonjour",
        "Bonjour discovery disabled",
        "Network.Bonjour.Enabled",
        ("no",),
        Severity.MEDIUM,
        "Disable unused services → Network discovery protocols",
    ),
    ParamCheck(
        "discovery.upnp",
        "UPnP discovery disabled",
        "Network.UPnP.Enabled",
        ("no",),
        Severity.MEDIUM,
        "Disable unused services → Network discovery protocols",
    ),
    ParamCheck(
        "discovery.upnp_nat",
        "UPnP NAT traversal disabled",
        "Network.UPnP.NATTraversal.Enabled",
        ("no",),
        Severity.HIGH,
        "Disable unused services → Network discovery protocols",
    ),
    ParamCheck(
        "discovery.zeroconf",
        "Zero-Conf IP address configuration disabled",
        "Network.ZeroConf.Enabled",
        ("no",),
        Severity.LOW,
        "Disable unused services → Network discovery protocols",
    ),
    ParamCheck(
        "discovery.ws_discovery",
        "WS-Discovery (ONVIF discovery) disabled",
        "WebService.DiscoveryMode.Discoverable",
        ("no",),
        Severity.MEDIUM,
        "Disable unused services → Network discovery protocols",
    ),
    ParamCheck(
        "remote.o3c",
        "One-click cloud connection (O3C) disabled",
        "RemoteService.Enabled",
        ("no",),
        Severity.MEDIUM,
        "Basic hardening via VAPIX API",
    ),
    ParamCheck(
        "access.ssh",
        "SSH maintenance access disabled",
        "Network.SSH.Enabled",
        ("no",),
        Severity.MEDIUM,
        "Disable unused services → SSH access",
    ),
    ParamCheck(
        "access.ftp",
        "FTP maintenance access disabled",
        "Network.FTP.Enabled",
        ("no",),
        Severity.HIGH,
        "Legacy hardening → FTP access",
    ),
    ParamCheck(
        "access.arp_ping",
        "ARP/Ping IP address configuration disabled",
        "Network.ARPPingIPAddress.Enabled",
        ("no",),
        Severity.MEDIUM,
        "Legacy hardening → ARP/Ping",
    ),
    ParamCheck(
        "access.script_editor",
        "Script editor environment disabled",
        "System.EditCgi",
        ("no",),
        Severity.HIGH,
        "Legacy hardening → Script editor environment",
    ),
    ParamCheck(
        "access.web_interface",
        "Web interface disabled for daily operation",
        "System.WebInterfaceDisabled",
        ("yes",),
        Severity.LOW,
        "Disable unused services → Web interface access",
    ),
    ParamCheck(
        "tls.allow_tls1_0",
        "TLS 1.0 disabled",
        "HTTPS.AllowTLS1",
        ("no",),
        Severity.HIGH,
        "Legacy hardening → Outdated TLS versions",
    ),
    ParamCheck(
        "tls.allow_tls1_1",
        "TLS 1.1 disabled",
        "HTTPS.AllowTLS11",
        ("no",),
        Severity.HIGH,
        "Legacy hardening → Outdated TLS versions",
    ),
    ParamCheck(
        "logging.access_log",
        "Improved user access logging enabled",
        "System.AccessLog",
        ("on",),
        Severity.LOW,
        "Legacy hardening → Access log",
    ),
    ParamCheck(
        "onvif.replay_protection",
        "ONVIF replay attack protection enabled",
        "WebService.UsernameToken.ReplayAttackProtection",
        ("yes",),
        Severity.MEDIUM,
        "Default protection → ONVIF replay attack protection",
    ),
    ParamCheck(
        "info.server_tokens",
        "HTTP/OpenSSL server header disabled",
        "System.HTTPServerTokens",
        ("no",),
        Severity.LOW,
        "Disable unused services → Information disclosure",
    ),
    ParamCheck(
        "auth.brute_force_delay",
        "Brute-force delay protection enabled",
        "System.PreventDoSAttack.ActivatePasswordThrottling",
        ("on",),
        Severity.MEDIUM,
        "Default protection → Prevent brute-force attacks",
    ),
    ParamCheck(
        "https.enabled",
        "HTTPS enabled",
        "HTTPS.Enabled",
        ("yes",),
        Severity.HIGH,
        "Basic hardening → HTTPS",
        absent_is_na=False,
    ),
    ParamCheck(
        "auth.viewer_requires_password",
        "No anonymous viewer access (HTTP)",
        "System.BoaProtViewer",
        ("password",),
        Severity.HIGH,
        "Common configuration mistakes → Anonymous access",
    ),
    ParamCheck(
        "auth.rtsp_requires_password",
        "No anonymous viewer access (RTSP)",
        "Network.RTSP.ProtViewer",
        ("password",),
        Severity.HIGH,
        "Common configuration mistakes → Anonymous access",
    ),
)

#: ``System.BoaGroupPolicy.<role>``: the guide's "HTTPS only" is ``https`` for all three.
HTTPS_ONLY_ROLES = ("admin", "operator", "viewer")

#: The guide's recommended TLS 1.2 cipher list, verbatim.
RECOMMENDED_CIPHERS = (
    "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305"
)


def check_param(params: dict[str, str], check: ParamCheck) -> Finding:
    """Evaluate one ``ParamCheck`` against an exported parameter tree."""
    value = params.get(f"root.{check.param}")
    update = f"param.cgi?action=update&{check.param}={check.hardened[0]}"
    if value is None:
        if check.absent_is_na:
            return Finding(
                check.check_id,
                check.title,
                Status.NOT_APPLICABLE,
                check.severity,
                evidence=f"{check.param} not present on this product",
                reference=check.reference,
            )
        return Finding(
            check.check_id,
            check.title,
            Status.UNKNOWN,
            check.severity,
            evidence=f"{check.param} not present",
            reference=check.reference,
        )
    ok = value.strip().lower() in {v.lower() for v in check.hardened}
    return Finding(
        check.check_id,
        check.title,
        Status.PASS if ok else Status.FAIL,
        check.severity,
        evidence=f"{check.param}={value}",
        recommendation="" if ok else update,
        reference=check.reference,
    )


def check_https_only(params: dict[str, str]) -> Finding:
    """``System.BoaGroupPolicy.*`` must all be ``https`` (guide: "HTTPS only")."""
    values = {role: params.get(f"root.System.BoaGroupPolicy.{role}") for role in HTTPS_ONLY_ROLES}
    if all(v is None for v in values.values()):
        return Finding(
            "https.only",
            "HTTPS only (no HTTP access) for every role",
            Status.UNKNOWN,
            Severity.HIGH,
            evidence="System.BoaGroupPolicy.* not present",
            reference="Legacy hardening → HTTPS only",
        )
    evidence = ", ".join(f"{r}={v or '?'}" for r, v in values.items())
    failing = [r for r, v in values.items() if (v or "").lower() != "https"]
    return Finding(
        "https.only",
        "HTTPS only (no HTTP access) for every role",
        Status.FAIL if failing else Status.PASS,
        Severity.HIGH,
        evidence=f"System.BoaGroupPolicy: {evidence}",
        recommendation=(
            "; ".join(f"param.cgi?action=update&System.BoaGroupPolicy.{r}=https" for r in failing)
            if failing
            else ""
        ),
        reference="Legacy hardening → HTTPS only",
    )


def check_http_auth_policy(params: dict[str, str]) -> Finding:
    """Basic authentication over plain HTTP sends the password in clear (guide: Digest)."""
    value = params.get("root.Network.HTTP.AuthenticationPolicy")
    if value is None:
        return Finding(
            "auth.http_policy",
            "No Basic authentication over plain HTTP",
            Status.UNKNOWN,
            Severity.HIGH,
            evidence="Network.HTTP.AuthenticationPolicy not present",
            reference="Default protection → Digest authentication",
        )
    # ``recommended`` = Basic on HTTPS / Digest on HTTP (what Axis documents);
    # ``digest`` is stricter.
    ok = value.lower() in {"recommended", "digest"}
    return Finding(
        "auth.http_policy",
        "No Basic authentication over plain HTTP",
        Status.PASS if ok else Status.FAIL,
        Severity.HIGH,
        evidence=f"Network.HTTP.AuthenticationPolicy={value}",
        recommendation=""
        if ok
        else "param.cgi?action=update&Network.HTTP.AuthenticationPolicy=recommended",
        reference="Default protection → Digest authentication",
    )


def check_ciphers(params: dict[str, str]) -> Finding:
    """Every configured TLS 1.2 cipher must be in the guide's recommended set."""
    value = params.get("root.HTTPS.Ciphers")
    if value is None:
        return Finding(
            "tls.ciphers",
            "TLS 1.2 ciphers limited to the recommended set",
            Status.UNKNOWN,
            Severity.MEDIUM,
            evidence="HTTPS.Ciphers not present",
            reference="Basic hardening → HTTPS ciphers",
        )
    configured = [c for c in value.split(":") if c]
    extra = [c for c in configured if c not in RECOMMENDED_CIPHERS.split(":")]
    return Finding(
        "tls.ciphers",
        "TLS 1.2 ciphers limited to the recommended set",
        Status.FAIL if extra else Status.PASS,
        Severity.MEDIUM,
        evidence=f"{len(configured)} cipher(s)"
        + (f"; not recommended: {', '.join(extra)}" if extra else ""),
        recommendation=f"param.cgi?action=update&HTTPS.Ciphers={RECOMMENDED_CIPHERS}"
        if extra
        else "",
        reference="Basic hardening → HTTPS ciphers",
    )


def check_remote_syslog(params: dict[str, str]) -> Finding:
    """A remote syslog server keeps the logs off the device (guide: Remote syslog)."""
    enabled = params.get("root.API.RemoteSyslog1.Enabled")
    if enabled is None:
        return Finding(
            "logging.remote_syslog",
            "Remote syslog configured",
            Status.UNKNOWN,
            Severity.MEDIUM,
            evidence="API.RemoteSyslog1.Enabled not present",
            reference="Extended hardening → Remote syslog",
        )
    servers = [params.get(f"root.API.RemoteSyslog1.Server{i}.Address", "") for i in (1, 2)]
    servers = [s for s in servers if s]
    protocols = {params.get(f"root.API.RemoteSyslog1.Server{i}.Protocol", "") for i in (1, 2)} - {
        ""
    }
    on = enabled.lower() == "true" and bool(servers)
    evidence = f"enabled={enabled}, servers={servers or 'none'}"
    if protocols:
        evidence += f", protocol={'/'.join(sorted(protocols))}"
    return Finding(
        "logging.remote_syslog",
        "Remote syslog configured",
        Status.PASS if on else Status.FAIL,
        Severity.MEDIUM,
        evidence=evidence,
        recommendation=""
        if on
        else "Configure a remote syslog server (System → Logs) — TLS preferred",
        reference="Extended hardening → Remote syslog",
    )


# --- reader-based checks ------------------------------------------------------


def check_accounts(accounts: Any, authenticated_as: str) -> list[Finding]:
    """Account hygiene from ``UserAccounts``: dedicated admin, unknown admins, lone root."""
    admins = [a.username for a in accounts.admins]
    non_admin = [a.username for a in accounts.accounts if a.role is not UserRole.ADMIN]
    findings = [
        Finding(
            "accounts.dedicated_client_account",
            "A non-administrator account exists for daily operation",
            Status.PASS if non_admin else Status.FAIL,
            Severity.MEDIUM,
            evidence=f"{len(admins)} administrator(s), {len(non_admin)} other account(s)",
            recommendation="" if non_admin else "accounts add <name> --role viewer|operator",
            reference="Basic hardening → Create dedicated accounts",
        )
    ]
    unknown_admins = sorted(
        a
        for a in admins
        if a not in KNOWN_SERVICE_ACCOUNTS and a != "root" and a != authenticated_as
    )
    findings.append(
        Finding(
            "accounts.administrators",
            "Administrator accounts are known",
            Status.INFO,
            Severity.INFO,
            evidence=(
                f"administrators: {', '.join(admins) or 'none'}"
                + (
                    f"; not Axis service accounts and not this session: {', '.join(unknown_admins)}"
                    if unknown_admins
                    else ""
                )
            ),
            recommendation=(
                "Confirm each administrator is yours (AXIS OS Forensics Guide: unknown "
                "administrators are an indicator of compromise)"
                if unknown_admins
                else ""
            ),
            reference="Basic hardening → Create dedicated accounts",
        )
    )
    return findings


def check_onvif_users(users: Any) -> Finding:
    """ONVIF users exist only when something uses ONVIF; administrators there need a reason."""
    admins = [u.username for u in users.accounts if u.level is OnvifUserLevel.ADMINISTRATOR]
    others = [u.username for u in users.accounts if u.level is not OnvifUserLevel.ADMINISTRATOR]
    return Finding(
        "onvif.users",
        "ONVIF user database",
        Status.INFO,
        Severity.INFO,
        evidence=(
            f"{len(users.accounts)} ONVIF user(s): administrators {admins or 'none'}, "
            f"others {others or 'none'}"
        ),
        recommendation=(
            "A VMS usually needs Operator, not Administrator; remove ONVIF users nothing uses"
            if admins
            else ""
        ),
        reference="Disable unused services → Network discovery protocols (ONVIF)",
    )


def check_snmp(snmp: Any) -> list[Finding]:
    """SNMP v1/v2c leak everything; a default community is a known password."""
    findings = []
    legacy = snmp.enabled and (snmp.v1_enabled or snmp.v2c_enabled)
    findings.append(
        Finding(
            "snmp.legacy_versions",
            "SNMP v1/v2c disabled (SNMPv3 only)",
            Status.FAIL if legacy else Status.PASS,
            Severity.HIGH if legacy else Severity.MEDIUM,
            evidence=(
                f"enabled={snmp.enabled}, v1={snmp.v1_enabled}, v2c={snmp.v2c_enabled}, "
                f"v3={snmp.v3_enabled}"
            ),
            recommendation="Disable SNMP v1/v2c; use SNMPv3 with AES encryption" if legacy else "",
            reference="Extended hardening → SNMP",
        )
    )
    if snmp.enabled and (snmp.v1_enabled or snmp.v2c_enabled):
        findings.append(
            Finding(
                "snmp.default_community",
                "SNMP read community is not the default",
                Status.FAIL if snmp.read_community_is_default else Status.PASS,
                Severity.HIGH,
                evidence=(
                    "read community is 'public'"
                    if snmp.read_community_is_default
                    else "read community is not the default"
                ),
                recommendation="Change the read community"
                if snmp.read_community_is_default
                else "",
                reference="Extended hardening → SNMP",
            )
        )
    return findings


def check_firewall(firewall: Any) -> Finding:
    """The guide's "Limit network access": firewall on, default DROP, allow-list rules."""
    on = firewall.activated and firewall.default_policy.value == "DROP"
    return Finding(
        "network.firewall",
        "Firewall activated with a DROP default policy",
        Status.PASS if on else Status.FAIL,
        Severity.MEDIUM,
        evidence=(
            f"activated={firewall.activated}, default={firewall.default_policy.value}, "
            f"{len(firewall.rules)} active rule(s)"
        ),
        recommendation=(
            ""
            if on
            else "Allow-list the VMS and management hosts, then set the default policy to DROP"
        ),
        reference="Basic hardening → Interfaces → Limit network access",
    )


def check_crypto_policy(policy: Any) -> Finding:
    """System crypto policy (AXIS OS 12): MODERN or FIPS over DEFAULT."""
    strong = policy.active_policy.upper() in {"MODERN", "FIPS"}
    return Finding(
        "tls.crypto_policy",
        "System cryptographic policy is MODERN or FIPS",
        Status.PASS if strong else Status.FAIL,
        Severity.LOW,
        evidence=f"active_policy={policy.active_policy or '?'}",
        recommendation=""
        if strong
        else (
            "Set the crypto policy to MODERN (System → Security) unless a legacy client "
            "needs DEFAULT"
        ),
        reference="Basic hardening → HTTPS ciphers → TLS 1.3",
    )


def check_ntp(ntp: Any) -> Finding:
    """Logs and certificates need the clock right (guide: network, date and time settings)."""
    ok = ntp.enabled and ntp.synced
    return Finding(
        "time.ntp_synced",
        "NTP enabled and synchronised",
        Status.PASS if ok else Status.FAIL,
        Severity.MEDIUM,
        evidence=(
            f"enabled={ntp.enabled}, synced={ntp.synced}, offset={ntp.time_offset_s:+.3f}s, "
            f"servers={ntp.static_servers or ntp.advertised_servers or 'none'}"
        ),
        recommendation="" if ok else "Configure reachable NTP servers (NTS where available)",
        reference="Basic hardening → Commissioning → Configure network, date, and time settings",
    )


def check_certificates(store: Any, *, now: datetime | None = None) -> list[Finding]:
    """Device certificates: expiring soon, and self-signed where a PKI could be used."""
    now = now or datetime.now(UTC)
    device_certs = list(store.certificates)
    expiring = [c for c in device_certs if c.expires_within(CERT_EXPIRY_WARNING_DAYS, now=now)]
    self_signed = [c for c in device_certs if c.self_signed]
    findings = [
        Finding(
            "cert.expiry",
            f"No device certificate expires within {CERT_EXPIRY_WARNING_DAYS} days",
            Status.FAIL if expiring else Status.PASS,
            Severity.MEDIUM,
            evidence=(
                f"{len(device_certs)} device certificate(s)"
                + (
                    "; expiring: "
                    + ", ".join(
                        f"{c.alias} ({c.not_after:%Y-%m-%d})" for c in expiring if c.not_after
                    )
                    if expiring
                    else ""
                )
            ),
            recommendation="Renew or replace the expiring certificate(s)" if expiring else "",
            reference="Extended hardening → Trusted public key infrastructure (PKI)",
        ),
        Finding(
            "cert.self_signed",
            "Device certificates issued by a PKI (not self-signed)",
            Status.INFO,
            Severity.LOW,
            evidence=(f"self-signed: {', '.join(c.alias for c in self_signed) or 'none'}"),
            recommendation=(
                "Replace self-signed certificates with PKI-issued ones where a PKI exists"
                if self_signed
                else ""
            ),
            reference="Extended hardening → Trusted public key infrastructure (PKI)",
        ),
    ]
    return findings


def check_firmware(info: Any) -> Finding:
    """Firmware version is recorded; whether it is current needs Axis's release feed."""
    return Finding(
        "firmware.version",
        "AXIS OS version",
        Status.INFO,
        Severity.INFO,
        evidence=f"{info.product_full_name} running {info.firmware_version}",
        recommendation=(
            "Compare with the current active/LTS release on axis.com (not checked online)"
        ),
        reference="Basic hardening → Commissioning → Upgrade to latest AXIS OS",
    )


# --- orchestration ----------------------------------------------------------------


def _unreadable(
    check_id: str,
    title: str,
    severity: Severity,
    reference: str,
    exc: Exception,
    *,
    password: object = None,
) -> Finding:
    reason = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, AxisPermissionError):
        reason = f"this account may not read it ({exc})"
    elif isinstance(exc, AxisApiNotSupportedError | AxisDeviceError):
        status = re.search(r"Device error (\d{3})", str(exc))
        # Cut for the table, but withhold first: a cut through the configured
        # password leaves a fragment no downstream scrubber recognises (F7).
        reason = (
            f"the device answered HTTP {status.group(1)} for this API"
            if status
            else f"the device did not answer this API "
            f"({error_excerpt(str(exc), password=password, limit=120)})"
        )
    return Finding(
        check_id,
        title,
        Status.UNKNOWN,
        severity,
        evidence=f"could not read: {reason}",
        reference=reference,
    )


async def _read(reader: Callable[[], Awaitable[Any]]) -> tuple[Any, Exception | None]:
    try:
        return await reader(), None
    except AxisPermissionError as exc:
        return None, exc  # 403 on one API: this account may not use it; the rest still counts
    except (AxisAuthenticationError, AxisConnectionError):
        raise  # the whole audit is meaningless without access; propagate
    except (AxisDeviceError, AxisApiNotSupportedError) as exc:
        return None, exc


async def run_audit(device: AxisDevice, *, device_name: str = "") -> AuditReport:
    """Run every check against ``device`` and return the report. Writes nothing.

    Raises:
        AxisAuthenticationError / AxisConnectionError: Propagate — an audit that
            cannot authenticate has nothing to say.
    """
    report = AuditReport(
        host=device.client.host,
        device_name=device_name or device.client.host,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    unreadable = functools.partial(_unreadable, password=device.client.password)

    # Parameter tree: one read, many checks.
    params, exc = await _read(device.params.export)
    if exc is None:
        for check in PARAM_CHECKS:
            report.findings.append(check_param(params, check))
        report.findings.append(check_https_only(params))
        report.findings.append(check_http_auth_policy(params))
        report.findings.append(check_ciphers(params))
        report.findings.append(check_remote_syslog(params))
    else:
        for check in PARAM_CHECKS:
            report.findings.append(
                unreadable(check.check_id, check.title, check.severity, check.reference, exc)
            )
        for cid, title, sev, ref in (
            (
                "https.only",
                "HTTPS only (no HTTP access) for every role",
                Severity.HIGH,
                "Legacy hardening → HTTPS only",
            ),
            (
                "auth.http_policy",
                "No Basic authentication over plain HTTP",
                Severity.HIGH,
                "Default protection → Digest authentication",
            ),
            (
                "tls.ciphers",
                "TLS 1.2 ciphers limited to the recommended set",
                Severity.MEDIUM,
                "Basic hardening → HTTPS ciphers",
            ),
            (
                "logging.remote_syslog",
                "Remote syslog configured",
                Severity.MEDIUM,
                "Extended hardening → Remote syslog",
            ),
        ):
            report.findings.append(unreadable(cid, title, sev, ref, exc))

    # Readers, in parallel: each failure is its own UNKNOWN.
    readers: dict[str, Callable[[], Awaitable[Any]]] = {
        "device_info": device.device_info.read,
        "users": device.users.read,
        "onvif_users": device.onvif_users.read,
        "snmp": device.snmp.read,
        "firewall": device.firewall.read,
        "crypto_policy": device.crypto_policy.read,
        "ntp": device.ntp.read,
        "cert": device.cert.read,
    }
    results = dict(
        zip(readers, await asyncio.gather(*(_read(r) for r in readers.values())), strict=True)
    )

    info, exc = results["device_info"]
    if exc is None:
        report.product, report.firmware = info.product_full_name, info.firmware_version
        report.findings.append(check_firmware(info))
    else:
        report.findings.append(
            unreadable(
                "firmware.version",
                "AXIS OS version",
                Severity.INFO,
                "Basic hardening → Commissioning → Upgrade to latest AXIS OS",
                exc,
            )
        )

    accounts, exc = results["users"]
    if exc is None:
        report.findings.extend(check_accounts(accounts, device.client.username))
    else:
        report.findings.append(
            unreadable(
                "accounts.dedicated_client_account",
                "A non-administrator account exists for daily operation",
                Severity.MEDIUM,
                "Basic hardening → Create dedicated accounts",
                exc,
            )
        )

    users, exc = results["onvif_users"]
    report.findings.append(
        check_onvif_users(users)
        if exc is None
        else unreadable("onvif.users", "ONVIF user database", Severity.INFO, "ONVIF", exc)
    )

    snmp, exc = results["snmp"]
    if exc is None:
        report.findings.extend(check_snmp(snmp))
    else:
        report.findings.append(
            unreadable(
                "snmp.legacy_versions",
                "SNMP v1/v2c disabled (SNMPv3 only)",
                Severity.MEDIUM,
                "Extended hardening → SNMP",
                exc,
            )
        )

    firewall, exc = results["firewall"]
    report.findings.append(
        check_firewall(firewall)
        if exc is None
        else unreadable(
            "network.firewall",
            "Firewall activated with a DROP default policy",
            Severity.MEDIUM,
            "Basic hardening → Interfaces → Limit network access",
            exc,
        )
    )

    policy, exc = results["crypto_policy"]
    report.findings.append(
        check_crypto_policy(policy)
        if exc is None
        else unreadable(
            "tls.crypto_policy",
            "System cryptographic policy is MODERN or FIPS",
            Severity.LOW,
            "Basic hardening → HTTPS ciphers → TLS 1.3",
            exc,
        )
    )

    ntp, exc = results["ntp"]
    report.findings.append(
        check_ntp(ntp)
        if exc is None
        else unreadable(
            "time.ntp_synced",
            "NTP enabled and synchronised",
            Severity.MEDIUM,
            "Basic hardening → Commissioning → Configure network, date, and time settings",
            exc,
        )
    )

    store, exc = results["cert"]
    if exc is None:
        report.findings.extend(check_certificates(store))
    else:
        report.findings.append(
            unreadable(
                "cert.expiry",
                f"No device certificate expires within {CERT_EXPIRY_WARNING_DAYS} days",
                Severity.MEDIUM,
                "Extended hardening → Trusted public key infrastructure (PKI)",
                exc,
            )
        )

    return report


# --- catalogue: what the audit checks, without a device ----------------------------

#: Checks that appear only when their data is readable (one per item, or a second
#: finding about the same setting). The catalogue names them so nobody reads it
#: as the exhaustive per-device list.
DATA_DEPENDENT_CHECKS: tuple[str, ...] = (
    "accounts.administrators",
    "snmp.default_community",
    "cert.self_signed",
)


class _Unread:
    """A stand-in module whose every read answers 'not read'."""

    async def read(self) -> Any:
        raise AxisApiNotSupportedError("catalogue: not read")

    async def export(self) -> Any:
        raise AxisApiNotSupportedError("catalogue: not read")


class _CatalogueDevice:
    """Enough of AxisDevice for :func:`run_audit` with nothing readable."""

    class client:
        host = "catalogue"
        username = ""
        password = ""

    def __getattr__(self, name: str) -> _Unread:
        return _Unread()


async def check_catalogue() -> list[dict[str, Any]]:
    """Every check the audit runs, with id, title, severity and guide reference.

    Derived by running :func:`run_audit` against a device on which nothing can
    be read, so the list cannot drift from the checks themselves. Parameter
    checks also carry the parameter and the guide's hardened values. Checks in
    :data:`DATA_DEPENDENT_CHECKS` are added only when data is readable.
    """
    report = await run_audit(cast("AxisDevice", _CatalogueDevice()))
    params = {c.check_id: c for c in PARAM_CHECKS}
    catalogue: list[dict[str, Any]] = []
    for finding in report.findings:
        entry: dict[str, Any] = {
            "id": finding.check_id,
            "title": finding.title,
            "severity": finding.severity.value,
            "reference": finding.reference,
        }
        check = params.get(finding.check_id)
        if check is not None:
            entry["parameter"] = check.param
            entry["hardened_values"] = list(check.hardened)
        catalogue.append(entry)
    return catalogue
