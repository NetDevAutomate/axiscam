"""Tests for the hardening audit (``axis_cam.audit``)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from axis_cam.audit import (
    PARAM_CHECKS,
    RECOMMENDED_CIPHERS,
    Severity,
    Status,
    check_accounts,
    check_certificates,
    check_ciphers,
    check_firewall,
    check_http_auth_policy,
    check_https_only,
    check_ntp,
    check_param,
    check_remote_syslog,
    check_snmp,
    run_audit,
)
from axis_cam.exceptions import AxisAuthenticationError, AxisDeviceError, AxisPermissionError
from axis_cam.mcp_server.redact import Scrubber
from axis_cam.models import (
    BasicDeviceInfo,
    CertConfig,
    Certificate,
    CryptoPolicyConfig,
    FirewallConfig,
    FirewallPolicy,
    NtpConfig,
    OnvifAccount,
    OnvifAccounts,
    OnvifUserLevel,
    SnmpConfig,
    UserAccount,
    UserAccounts,
    UserRole,
)

BY_ID = {c.check_id: c for c in PARAM_CHECKS}

# The M3216-LVE's values on 2026-10-13 for the parameters the guide names.
CAMERA_PARAMS = {
    "root.Network.Bonjour.Enabled": "yes",
    "root.Network.UPnP.Enabled": "yes",
    "root.Network.ZeroConf.Enabled": "yes",
    "root.WebService.DiscoveryMode.Discoverable": "Yes",
    "root.RemoteService.Enabled": "no",
    "root.Network.SSH.Enabled": "yes",
    "root.HTTPS.Enabled": "yes",
    "root.HTTPS.Ciphers": RECOMMENDED_CIPHERS,
    "root.System.AccessLog": "Off",
    "root.WebService.UsernameToken.ReplayAttackProtection": "yes",
    "root.System.WebInterfaceDisabled": "no",
    "root.System.HTTPServerTokens": "yes",
    "root.System.BoaGroupPolicy.admin": "both",
    "root.System.BoaGroupPolicy.operator": "both",
    "root.System.BoaGroupPolicy.viewer": "both",
    "root.System.BoaProtViewer": "password",
    "root.Network.RTSP.ProtViewer": "password",
    "root.Network.HTTP.AuthenticationPolicy": "recommended",
    "root.System.PreventDoSAttack.ActivatePasswordThrottling": "On",
    "root.API.RemoteSyslog1.Enabled": "false",
    "root.API.RemoteSyslog1.Server1.Address": "",
    "root.API.RemoteSyslog1.Server1.Protocol": "TLS",
}


class TestParamChecks:
    def test_hardened_value_passes_case_insensitively(self):
        f = check_param({"root.RemoteService.Enabled": "No"}, BY_ID["remote.o3c"])
        assert f.status is Status.PASS and f.recommendation == ""

    def test_unhardened_value_fails_with_the_guides_call(self):
        f = check_param(CAMERA_PARAMS, BY_ID["discovery.bonjour"])
        assert f.status is Status.FAIL
        assert f.evidence == "Network.Bonjour.Enabled=yes"
        assert f.recommendation == "param.cgi?action=update&Network.Bonjour.Enabled=no"
        assert f.severity is Severity.MEDIUM

    def test_absent_parameter_is_not_applicable_when_removal_satisfies_it(self):
        # AXIS OS 12 removed FTP and the legacy TLS switches: nothing left to harden.
        for cid in ("access.ftp", "tls.allow_tls1_0", "access.arp_ping", "access.script_editor"):
            assert check_param(CAMERA_PARAMS, BY_ID[cid]).status is Status.NOT_APPLICABLE

    def test_absent_https_enabled_is_unknown_not_na(self):
        f = check_param({}, BY_ID["https.enabled"])
        assert f.status is Status.UNKNOWN

    def test_every_check_has_a_reference(self):
        assert all(c.reference for c in PARAM_CHECKS)
        assert len({c.check_id for c in PARAM_CHECKS}) == len(PARAM_CHECKS)


class TestCompositeParamChecks:
    def test_https_only_fails_on_both(self):
        f = check_https_only(CAMERA_PARAMS)
        assert f.status is Status.FAIL and f.severity is Severity.HIGH
        assert "admin=both" in f.evidence
        assert f.recommendation.count("System.BoaGroupPolicy") == 3

    def test_https_only_passes(self):
        params = {
            f"root.System.BoaGroupPolicy.{r}": "https" for r in ("admin", "operator", "viewer")
        }
        assert check_https_only(params).status is Status.PASS

    def test_https_only_unknown_when_absent(self):
        assert check_https_only({}).status is Status.UNKNOWN

    def test_http_auth_policy(self):
        assert check_http_auth_policy(CAMERA_PARAMS).status is Status.PASS  # recommended
        assert (
            check_http_auth_policy({"root.Network.HTTP.AuthenticationPolicy": "digest"}).status
            is Status.PASS
        )
        f = check_http_auth_policy({"root.Network.HTTP.AuthenticationPolicy": "basic"})
        assert f.status is Status.FAIL and f.severity is Severity.HIGH
        assert check_http_auth_policy({}).status is Status.UNKNOWN

    def test_ciphers(self):
        assert check_ciphers(CAMERA_PARAMS).status is Status.PASS
        speaker = {"root.HTTPS.Ciphers": RECOMMENDED_CIPHERS + ":DHE-RSA-AES128-GCM-SHA256"}
        f = check_ciphers(speaker)
        assert f.status is Status.FAIL and "DHE-RSA-AES128-GCM-SHA256" in f.evidence
        assert f.recommendation.endswith(RECOMMENDED_CIPHERS)

    def test_remote_syslog(self):
        f = check_remote_syslog(CAMERA_PARAMS)
        assert f.status is Status.FAIL and "servers=none" in f.evidence
        on = dict(
            CAMERA_PARAMS,
            **{
                "root.API.RemoteSyslog1.Enabled": "true",
                "root.API.RemoteSyslog1.Server1.Address": "10.0.0.5",
            },
        )
        assert check_remote_syslog(on).status is Status.PASS
        enabled_without_server = dict(CAMERA_PARAMS, **{"root.API.RemoteSyslog1.Enabled": "true"})
        assert check_remote_syslog(enabled_without_server).status is Status.FAIL
        assert check_remote_syslog({}).status is Status.UNKNOWN


class TestReaderChecks:
    def test_accounts(self):
        accounts = UserAccounts(
            accounts=[
                UserAccount(username="root", role=UserRole.ADMIN),
                UserAccount(username="AxisDeviceMgmt", role=UserRole.ADMIN),
                UserAccount(username="homeassistant", role=UserRole.ADMIN),
                UserAccount(username="viewer1", role=UserRole.VIEWER),
            ]
        )
        dedicated, admins = check_accounts(accounts, authenticated_as="root")
        assert dedicated.status is Status.PASS
        assert admins.status is Status.INFO
        assert (
            "homeassistant" in admins.evidence
            and "AxisDeviceMgmt" not in admins.evidence.split(";")[1]
        )
        assert "Forensics" in admins.recommendation

    def test_accounts_without_a_client_account_fails(self):
        accounts = UserAccounts(accounts=[UserAccount(username="root", role=UserRole.ADMIN)])
        dedicated, admins = check_accounts(accounts, authenticated_as="root")
        assert dedicated.status is Status.FAIL
        assert admins.recommendation == ""  # root alone is not an unknown admin

    def test_snmp_legacy_and_default_community(self):
        off = SnmpConfig(enabled=False)
        assert [f.status for f in check_snmp(off)] == [Status.PASS]
        legacy = SnmpConfig(
            enabled=True, v1_enabled=True, v2c_enabled=True, read_community_is_default=True
        )
        findings = {f.check_id: f for f in check_snmp(legacy)}
        assert findings["snmp.legacy_versions"].status is Status.FAIL
        assert findings["snmp.legacy_versions"].severity is Severity.HIGH
        assert findings["snmp.default_community"].status is Status.FAIL
        v3_only = SnmpConfig(enabled=True, v3_enabled=True)
        assert [f.check_id for f in check_snmp(v3_only)] == ["snmp.legacy_versions"]
        assert check_snmp(v3_only)[0].status is Status.PASS

    def test_firewall(self):
        assert (
            check_firewall(
                FirewallConfig(activated=True, default_policy=FirewallPolicy.ACCEPT)
            ).status
            is Status.FAIL
        )
        assert (
            check_firewall(
                FirewallConfig(activated=True, default_policy=FirewallPolicy.DROP)
            ).status
            is Status.PASS
        )
        assert (
            check_firewall(
                FirewallConfig(activated=False, default_policy=FirewallPolicy.DROP)
            ).status
            is Status.FAIL
        )

    def test_ntp(self):
        assert check_ntp(NtpConfig(enabled=True, synced=True)).status is Status.PASS
        f = check_ntp(NtpConfig(enabled=True, synced=False, static_servers=["pool.ntp.org"]))
        assert f.status is Status.FAIL and "pool.ntp.org" in f.evidence

    def test_certificates(self):
        now = datetime(2026, 10, 13, tzinfo=UTC)
        store = CertConfig(
            certificates=[
                Certificate(alias="soon", not_after=now + timedelta(days=30), self_signed=True),
                Certificate(alias="fine", not_after=now + timedelta(days=400)),
                Certificate(alias="unparsed"),
            ]
        )
        expiry, self_signed = check_certificates(store, now=now)
        assert expiry.status is Status.FAIL and "soon (2026-11-12)" in expiry.evidence
        assert "fine" not in expiry.evidence
        assert self_signed.status is Status.INFO and "soon" in self_signed.evidence

    def test_certificates_all_good(self):
        now = datetime(2026, 10, 13, tzinfo=UTC)
        store = CertConfig(
            certificates=[Certificate(alias="fine", not_after=now + timedelta(days=400))]
        )
        expiry, self_signed = check_certificates(store, now=now)
        assert expiry.status is Status.PASS and self_signed.recommendation == ""


def _device(*, params=None, **readers):
    """A fake AxisDevice: params.export and each named module's read()."""
    device = MagicMock()
    device.client.host = "10.0.0.5"
    device.client.username = "root"
    device.params.export = AsyncMock(
        side_effect=params if isinstance(params, Exception) else None,
        return_value=None if isinstance(params, Exception) else (params or CAMERA_PARAMS),
    )
    defaults = {
        "device_info": BasicDeviceInfo(
            product_full_name="AXIS M3216-LVE", firmware_version="12.11.118"
        ),
        "users": UserAccounts(accounts=[UserAccount(username="root", role=UserRole.ADMIN)]),
        "onvif_users": OnvifAccounts(
            accounts=[OnvifAccount(username="onvif", level=OnvifUserLevel.ADMINISTRATOR)]
        ),
        "snmp": SnmpConfig(),
        "firewall": FirewallConfig(activated=True, default_policy=FirewallPolicy.ACCEPT),
        "crypto_policy": CryptoPolicyConfig(active_policy="DEFAULT"),
        "ntp": NtpConfig(enabled=True, synced=True),
        "cert": CertConfig(),
    }
    defaults.update(readers)
    for name, value in defaults.items():
        module = MagicMock()
        module.read = AsyncMock(
            side_effect=value if isinstance(value, Exception) else None,
            return_value=None if isinstance(value, Exception) else value,
        )
        setattr(device, name, module)
    return device


class TestRunAudit:
    async def test_catalogue_covers_every_check_the_audit_can_emit(self):
        from axis_cam.audit import DATA_DEPENDENT_CHECKS, check_catalogue

        catalogue = await check_catalogue()
        ids = [c["id"] for c in catalogue]
        assert len(ids) == len(set(ids))
        emitted = {f.check_id for f in (await run_audit(_device())).findings}
        assert emitted <= set(ids) | set(DATA_DEPENDENT_CHECKS), emitted - set(ids)
        assert set(DATA_DEPENDENT_CHECKS).isdisjoint(ids)
        assert {c["id"] for c in catalogue if "parameter" in c} == {
            c.check_id for c in PARAM_CHECKS
        }

    async def test_report_shape_and_counts(self):
        report = await run_audit(_device(), device_name="cam")

        assert report.device_name == "cam" and report.product == "AXIS M3216-LVE"
        ids = [f.check_id for f in report.findings]
        assert len(ids) == len(set(ids)), "check ids must be unique"
        assert len(ids) == len(PARAM_CHECKS) + 4 + 1 + 2 + 1 + 1 + 1 + 1 + 1 + 2
        counts = report.counts()
        assert counts["fail"] >= 8 and counts["unknown"] == 0
        d = report.to_dict()
        assert d["counts"] == counts and d["findings"][0]["id"] == ids[0]
        assert d["guide"].startswith("https://help.axis.com")

    async def test_unreadable_reader_is_unknown_not_pass_or_fail(self):
        report = await run_audit(
            _device(ntp=AxisDeviceError("Device error 404 from 10.0.0.5: not found"))
        )

        ntp = next(f for f in report.findings if f.check_id == "time.ntp_synced")
        assert ntp.status is Status.UNKNOWN
        assert "HTTP 404" in ntp.evidence

    async def test_permission_denied_reader_says_so(self):
        report = await run_audit(_device(snmp=AxisPermissionError("Access denied to 10.0.0.5")))
        snmp = next(f for f in report.findings if f.check_id == "snmp.legacy_versions")
        assert snmp.status is Status.UNKNOWN and "may not read" in snmp.evidence

    async def test_unreadable_params_make_every_param_check_unknown(self):
        report = await run_audit(
            _device(params=AxisDeviceError("Device error 404 from 10.0.0.5: no param.cgi"))
        )

        param_ids = {c.check_id for c in PARAM_CHECKS} | {
            "https.only",
            "auth.http_policy",
            "tls.ciphers",
            "logging.remote_syslog",
        }
        for f in report.findings:
            if f.check_id in param_ids:
                assert f.status is Status.UNKNOWN, f.check_id
        # reader-based checks still ran
        assert any(
            f.check_id == "network.firewall" and f.status is Status.FAIL for f in report.findings
        )

    async def test_authentication_error_aborts(self):
        with pytest.raises(AxisAuthenticationError):
            await run_audit(_device(params=AxisAuthenticationError("401")))

    # F7: the audit cuts library messages to 120 characters for the table.

    PASSWORD = "Audit-Cut~S3cret?"  # pragma: allowlist secret

    async def _evidence_for(self, message: str) -> list[str]:
        device = _device(params=AxisDeviceError(message))
        device.client.password = self.PASSWORD
        report = await run_audit(device)
        return [f.evidence for f in report.findings if f.evidence.startswith("could not read")]

    async def test_a_message_holding_the_password_is_withheld_before_the_cut(self):
        # A cut through the password leaves a fragment that no downstream scrubber
        # (the MCP Scrubber matches whole strings) recognises. The library's rule
        # holds here too: withhold first, then cut.
        message = "param.cgi: Error: " + "x" * 94 + self.PASSWORD + " in group"
        assert message.index(self.PASSWORD) < 120 < message.index(self.PASSWORD) + 17

        evidence = await self._evidence_for(message)

        fragments = [self.PASSWORD[i : i + 8] for i in range(len(self.PASSWORD) - 7)]
        scrubbed = [Scrubber("root", self.PASSWORD).text(e) for e in evidence]
        assert evidence and all("withheld" in e for e in evidence)
        assert [f for e in scrubbed for f in fragments if f in e] == []

    async def test_a_long_message_without_a_secret_is_still_cut(self):
        message = "param.cgi: Error: " + "y" * 300
        evidence = await self._evidence_for(message)
        assert evidence and all(f"({message[:120]})" in e for e in evidence)


class TestCli:
    """``axiscam security audit``: table/json, exit code, --no-fail, --all."""

    @staticmethod
    def _run(args, device):
        from unittest.mock import patch

        from typer.testing import CliRunner

        from axis_cam.cli import DeviceContext, app
        from axis_cam.config import AppConfig

        class Ctx:
            def __init__(self, dev):
                self.dev = dev

            async def __aenter__(self):
                return self.dev

            async def __aexit__(self, *exc):
                return None

        with (
            patch("axis_cam.cli.context.load_config", return_value=AppConfig()),
            patch.object(DeviceContext, "open", return_value=Ctx(device)),
        ):
            return CliRunner().invoke(
                app, ["security", "audit", *args, "--host", "10.0.0.5", "-u", "root", "-p", "pw"]
            )

    def test_table_hides_passing_and_exits_1_on_failures(self):
        result = self._run([], _device())

        assert result.exit_code == 1, result.output
        text = " ".join(result.output.replace("│", " ").split())
        assert "Security audit" in text and "failing" in text
        assert "Passing and n/a checks hidden" in text
        assert "FAIL" in text and "Bonjour" in text
        assert "No anonymous" not in text  # a passing check, hidden

    def test_no_fail_exits_0(self):
        assert self._run(["--no-fail"], _device()).exit_code == 0

    def test_json(self):
        import json

        result = self._run(["--json", "--no-fail"], _device())

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["counts"]["fail"] >= 8
        assert {f["status"] for f in data["findings"]} >= {"pass", "fail"}

    def test_all_shows_passing(self):
        result = self._run(["--show-all", "--no-fail"], _device())
        text = " ".join(result.output.replace("│", " ").split())
        assert " pass " in text and "No anonymous" in text and "BoaProtView" in text
