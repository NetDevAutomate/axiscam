"""Certificate store (``/config/rest/cert/v1``), with the PEMs parsed.

Contract (AXIS OS 12.11, ``cert/v1/openapi.json``)::

    {"certificates": [{"alias", "certificate": PEM, "keystore"}],
     "ca_certificates": [{"alias", "certificate": PEM}],
     "keystores": [{"id", "security_level", "key_types", "certifications"}],
     "settings": {"keystore"}}

The device gives only alias + PEM; subject, issuer, validity, key type and
fingerprint come from parsing the PEM with ``cryptography``. A PEM that does
not parse yields a certificate with just its alias, never an exception — one
odd certificate must not hide the rest of the store.
"""

from datetime import UTC
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

from axis_cam.api.base import BaseAPI
from axis_cam.api.registry import register
from axis_cam.models import CertConfig, Certificate, Keystore

#: cryptography leaves serialNumber as a dotted OID in RFC 4514 strings; name it.
_NAME_OVERRIDES = {NameOID.SERIAL_NUMBER: "serialNumber"}


def _key_type(cert: x509.Certificate) -> str:
    key = cert.public_key()
    if isinstance(key, rsa.RSAPublicKey):
        return f"RSA-{key.key_size}"
    if isinstance(key, ec.EllipticCurvePublicKey):
        return f"EC-{key.curve.name.replace('secp', 'P-').replace('r1', '')}"
    return type(key).__name__


def parse_certificate(entry: dict[str, Any], *, is_ca: bool = False) -> Certificate:
    """One store entry → :class:`Certificate`; unparseable PEM keeps alias only."""
    alias = str(entry.get("alias", ""))
    keystore = str(entry.get("keystore", "") or "")
    pem = entry.get("certificate") or ""
    try:
        cert = x509.load_pem_x509_certificate(pem.encode())
    except (ValueError, TypeError):
        return Certificate(alias=alias, keystore=keystore, is_ca=is_ca)
    digest = cert.fingerprint(hashes.SHA256()).hex().upper()
    return Certificate(
        alias=alias,
        keystore=keystore,
        is_ca=is_ca,
        subject=cert.subject.rfc4514_string(_NAME_OVERRIDES),
        issuer=cert.issuer.rfc4514_string(_NAME_OVERRIDES),
        not_before=cert.not_valid_before_utc.astimezone(UTC),
        not_after=cert.not_valid_after_utc.astimezone(UTC),
        self_signed=cert.subject == cert.issuer,
        key_type=_key_type(cert),
        fingerprint_sha256=":".join(digest[i : i + 2] for i in range(0, len(digest), 2)),
    )


@register
class CertAPI(BaseAPI):
    """Read the certificate store.

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     store = await camera.cert.read()
        ...     [(c.alias, c.not_after) for c in store.certificates]
    """

    name = "cert"
    api_id = "cert"

    REST_PATH = "/config/rest/cert/v1"

    async def read(self) -> CertConfig:
        """Read the store; errors propagate."""
        response = await self._get(await self._rest_path())
        return self.parse(response.get("data", {}))

    async def get_config(self) -> CertConfig:
        """Alias of :meth:`read`."""
        return await self.read()

    async def get_certificates(self) -> list[Certificate]:
        """Device certificates only."""
        return (await self.read()).certificates

    @staticmethod
    def parse(data: dict[str, Any]) -> CertConfig:
        """Build the model from the ``data`` object."""
        return CertConfig(
            certificates=[
                parse_certificate(c) for c in data.get("certificates", []) if isinstance(c, dict)
            ],
            ca_certificates=[
                parse_certificate(c, is_ca=True)
                for c in data.get("ca_certificates", [])
                if isinstance(c, dict)
            ],
            keystores=[
                Keystore(
                    id=str(k.get("id", "")),
                    security_level=str(k.get("security_level", "")),
                    key_types=[str(t) for t in k.get("key_types", [])],
                    certifications=[str(t) for t in k.get("certifications", [])],
                )
                for k in data.get("keystores", [])
                if isinstance(k, dict)
            ],
            default_keystore=str((data.get("settings") or {}).get("keystore", "")),
        )
