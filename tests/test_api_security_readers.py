"""Readers for the security-relevant REST APIs, parsed against the device's own bodies.

Bodies are what AXIS OS 12.11.118 (M3216-LVE) and 11.11.192 (C1410) returned on
2026-10-13, trimmed; shapes match the OpenAPI the devices publish under
``/config/discover/apis/<api>/<version>/openapi.json``.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from axis_cam.api.cert import CertAPI, parse_certificate
from axis_cam.api.crypto_policy import CryptoPolicyAPI
from axis_cam.api.firewall import FirewallAPI, parse_rule
from axis_cam.api.ntp import NtpAPI
from axis_cam.api.snmp import SnmpAPI
from axis_cam.api.ssh import SshAPI
from axis_cam.exceptions import AxisDeviceError
from axis_cam.models import FirewallPolicy

FIREWALL_CAMERA = {
    "activated": True,
    "conf": {
        "rules": {
            "activeDefaultPolicy": "ACCEPT",
            "activeRules": [
                {
                    "filter": None,
                    "ip": None,
                    "ipRange": None,
                    "limit": {
                        "amount": 3,
                        "burst": 3,
                        "period": "SECOND",
                        "unit": "NEWCONNECTIONS",
                    },
                    "mac": None,
                    "pktType": None,
                    "port": {"portNum": 22, "portType": "TCP"},
                    "portRange": None,
                    "ruleType": "LIMIT",
                    "tcpPort": None,
                    "udpPort": None,
                }
            ],
            "pendingDefaultPolicy": None,
            "pendingRules": [],
            "testTimeLeft": 0,
        }
    },
}

SNMP_SPEAKER = {
    "enabled": True,
    "engineBoots": 33,
    "snmpV1": {"enabled": True},
    "snmpV1V2Common": {
        "address": "",
        "readCommunity": "s3cret-community",
        "trap": {
            "authFailEnabled": False,
            "coldStartEnabled": False,
            "community": "public",
            "enabled": False,
        },
        "writeCommunity": "s3cret-community",
    },
    "snmpV2": {"enabled": True},
    "snmpV3": {
        "enabled": False,
        "supportedEncryption": ["AES-128", "AES-256"],
        "userEncryption": "AES-256",
        "userPasswdSet": False,
    },
    "transportProtocol": "udp",
}

NTP_CAMERA = {
    "ntp": {
        "client": {
            "advertisedServers": ["194.35.252.7", "81.168.77.149"],
            "enabled": True,
            "maximumDistance": 3,
            "nts": {"caCertificates": [], "enabled": False, "staticServers": [""]},
            "serversSource": "STATIC",
            "staticServers": ["192.168.125.2", "pool.ntp.org"],
            "synced": True,
            "timeOffset": -4.4,
            "timeToNextSync": 0,
        }
    },
    "ptp": {"hardwareSupport": True, "portState": "STOPPED", "synchronizeSystemClock": False},
    "ptp_supported": True,
}

CRYPTO_CAMERA = {
    "active_policy": "DEFAULT",
    "policies": [
        {"description": "Default policy from OpenSSL", "name": "DEFAULT", "nice_name": "Default"},
        {
            "description": "Policy to comply with FIPS 140-3",
            "name": "FIPS",
            "nice_name": "FIPS 140-3",
        },
        {
            "description": "Policy to use modern ciphers and protocols",
            "name": "MODERN",
            "nice_name": "Modern",
        },
    ],
}


def _pem(subject: str, issuer: str | None = None, *, days: int = 365) -> str:
    """A small self-signed (or issuer-named) EC certificate as PEM."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)])
    issuer_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer or subject)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(issuer_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=days))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def _api(cls, body: dict, *, status_ok: bool = True):
    client = MagicMock()
    client.host = "h"
    api = cls(client)
    api._rest_path = AsyncMock(return_value=cls.REST_PATH)
    api._get = AsyncMock(return_value={"status": "success", "data": body})
    return api


class TestFirewall:
    async def test_camera_body(self):
        fw = await _api(FirewallAPI, FIREWALL_CAMERA).read()

        assert fw.activated is True
        assert fw.default_policy is FirewallPolicy.ACCEPT
        assert len(fw.rules) == 1 and fw.pending_rules == []
        rule = fw.rules[0]
        assert rule.rule_type == "LIMIT" and rule.port == "TCP/22"
        assert rule.limit == "3 NEWCONNECTIONS/SECOND burst 3"

    def test_filter_rule_with_ip_range_and_port_range(self):
        rule = parse_rule(
            {
                "ruleType": "FILTER",
                "ipRange": {"start": "10.0.0.1", "end": "10.0.0.9"},
                "portRange": {"portType": "UDP", "start": 5000, "end": 5010},
            }
        )
        assert rule.ip_range == "10.0.0.1-10.0.0.9" and rule.port_range == "UDP/5000-5010"
        assert rule.limit is None

    async def test_error_propagates(self):
        api = _api(FirewallAPI, {})
        api._get = AsyncMock(side_effect=AxisDeviceError("404"))
        with pytest.raises(AxisDeviceError):
            await api.read()


class TestSsh:
    async def test_combines_rest_users_with_the_enabled_parameter(self, monkeypatch):
        api = _api(SshAPI, {"users": [{"comment": "", "username": "ataylor"}]})
        monkeypatch.setattr("axis_cam.api.ssh.ParamAPI.get", AsyncMock(return_value="yes"))

        ssh = await api.read()

        assert ssh.enabled is True
        assert [u.username for u in ssh.users] == ["ataylor"]

    def test_parse_without_the_parameter_is_tri_state(self):
        assert SshAPI.parse({"users": []}, None).enabled is None
        assert SshAPI.parse({"users": []}, "no").enabled is False


class TestSnmp:
    async def test_speaker_body_never_keeps_the_community_strings(self):
        snmp = await _api(SnmpAPI, SNMP_SPEAKER).read()

        assert snmp.enabled and snmp.v1_enabled and snmp.v2c_enabled and not snmp.v3_enabled
        assert snmp.read_community_is_default is False
        assert snmp.write_community_set is True
        assert "s3cret-community" not in snmp.model_dump_json()

    def test_default_read_community(self):
        body = dict(SNMP_SPEAKER, snmpV1V2Common={"readCommunity": "public", "writeCommunity": ""})
        snmp = SnmpAPI.parse(body)
        assert snmp.read_community_is_default is True and snmp.write_community_set is False


class TestCryptoPolicy:
    async def test_camera_body(self):
        policy = await _api(CryptoPolicyAPI, CRYPTO_CAMERA).read()
        assert policy.active_policy == "DEFAULT"
        assert [p.name for p in policy.policies] == ["DEFAULT", "FIPS", "MODERN"]


class TestNtp:
    async def test_camera_body(self):
        ntp = await _api(NtpAPI, NTP_CAMERA).read()

        assert ntp.enabled and ntp.synced
        assert ntp.servers_source == "STATIC"
        assert ntp.static_servers == ["192.168.125.2", "pool.ntp.org"]
        assert ntp.advertised_servers == ["194.35.252.7", "81.168.77.149"]
        assert ntp.time_offset_s == pytest.approx(-4.4)
        assert ntp.nts_enabled is False and ntp.ptp_supported and ntp.ptp_port_state == "STOPPED"


class TestCert:
    def test_pem_is_parsed_into_fields(self):
        cert = parse_certificate(
            {
                "alias": "Companion Secure Link",
                "certificate": _pem("axis-b8a44f"),
                "keystore": "SOFTWARE0",
            }
        )
        assert cert.alias == "Companion Secure Link" and cert.keystore == "SOFTWARE0"
        assert cert.subject == "CN=axis-b8a44f" and cert.self_signed is True
        assert cert.key_type == "EC-P-256"
        assert cert.not_after is not None and cert.not_after.tzinfo is not None
        assert len(cert.fingerprint_sha256.split(":")) == 32

    def test_issued_certificate_is_not_self_signed(self):
        cert = parse_certificate({"alias": "x", "certificate": _pem("device", "My CA")})
        assert cert.self_signed is False and cert.issuer == "CN=My CA"

    def test_unparseable_pem_keeps_the_alias(self):
        cert = parse_certificate({"alias": "odd", "certificate": "not a pem", "keystore": "SE0"})
        assert cert.alias == "odd" and cert.subject == "" and cert.not_after is None

    async def test_store_body(self):
        body = {
            "certificates": [{"alias": "dev", "certificate": _pem("dev"), "keystore": "SE0"}],
            "ca_certificates": [{"alias": "ca", "certificate": _pem("ca")}],
            "keystores": [
                {
                    "id": "SE0",
                    "security_level": "STRONG",
                    "key_types": ["EC-P256"],
                    "certifications": ["CC EAL6+"],
                },
                {
                    "id": "SOFTWARE0",
                    "security_level": "SOFTWARE",
                    "key_types": ["RSA-2048"],
                    "certifications": [],
                },
            ],
            "settings": {"keystore": "SE0"},
        }
        store = await _api(CertAPI, body).read()

        assert [c.alias for c in store.certificates] == ["dev"]
        assert store.ca_certificates[0].is_ca is True
        assert [k.id for k in store.keystores] == ["SE0", "SOFTWARE0"]
        assert store.default_keystore == "SE0"
        assert await _api(CertAPI, body).get_certificates() == store.certificates
