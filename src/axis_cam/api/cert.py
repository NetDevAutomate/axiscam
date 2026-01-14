"""Certificate API module.

This module provides access to SSL/TLS certificate management on AXIS devices
via the VAPIX cert API.

API Endpoints:
    - /config/rest/cert/v1 (REST API)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import CertConfig, Certificate, CertificateType


class CertAPI(BaseAPI):
    """API module for certificate management.

    This module provides methods to retrieve certificate information:
    - Installed certificates
    - Certificate details (issuer, validity, etc.)
    - Certificate status
    - CA certificates

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.cert.get_config()
        ...     for cert in config.certificates:
        ...         print(f"  {cert.subject}: expires {cert.not_after}")
    """

    REST_PATH = "/config/rest/cert/v1"

    async def get_config(self) -> CertConfig:
        """Get certificate configuration.

        Returns:
            CertConfig model with certificate settings.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return CertConfig()

    async def get_certificates(self) -> list[Certificate]:
        """Get list of installed certificates.

        Returns:
            List of Certificate models.
        """
        config = await self.get_config()
        return config.certificates

    async def get_ca_certificates(self) -> list[Certificate]:
        """Get list of CA certificates.

        Returns:
            List of CA Certificate models.
        """
        config = await self.get_config()
        return config.ca_certificates

    async def get_active_certificate(self) -> Certificate | None:
        """Get the currently active HTTPS certificate.

        Returns:
            Active Certificate or None.
        """
        config = await self.get_config()
        return config.active_certificate

    def _parse_config(self, data: dict[str, Any]) -> CertConfig:
        """Parse certificate configuration response.

        Args:
            data: Raw API response data.

        Returns:
            CertConfig model instance.
        """
        # Parse certificates
        certificates = []
        for cert_data in data.get("certificates", []):
            cert = self._parse_certificate(cert_data)
            if cert:
                certificates.append(cert)

        # Parse CA certificates
        ca_certificates = []
        for cert_data in data.get("caCertificates", []):
            cert = self._parse_certificate(cert_data, is_ca=True)
            if cert:
                ca_certificates.append(cert)

        # Find active certificate
        active_cert = None
        active_id = data.get("activeCertificate", "")
        if active_id:
            for cert in certificates:
                if cert.cert_id == active_id:
                    active_cert = cert
                    break

        return CertConfig(
            certificates=certificates,
            ca_certificates=ca_certificates,
            active_certificate=active_cert,
            https_enabled=data.get("httpsEnabled", True),
            https_only=data.get("httpsOnly", False),
        )

    def _parse_certificate(self, data: dict[str, Any], is_ca: bool = False) -> Certificate | None:
        """Parse a single certificate.

        Args:
            data: Certificate data from API.
            is_ca: Whether this is a CA certificate.

        Returns:
            Certificate model or None if invalid.
        """
        try:
            cert_type_str = data.get("type", "server")
            try:
                cert_type = CertificateType(cert_type_str.lower())
            except ValueError:
                cert_type = CertificateType.CA if is_ca else CertificateType.SERVER

            return Certificate(
                cert_id=data.get("id", ""),
                cert_type=cert_type,
                subject=data.get("subject", ""),
                issuer=data.get("issuer", ""),
                not_before=data.get("notBefore", ""),
                not_after=data.get("notAfter", ""),
                serial_number=data.get("serialNumber", ""),
                fingerprint_sha256=data.get("fingerprintSHA256", ""),
                fingerprint_sha1=data.get("fingerprintSHA1", ""),
                key_size=data.get("keySize", 0),
                key_type=data.get("keyType", ""),
                self_signed=data.get("selfSigned", False),
            )
        except Exception:
            return None
