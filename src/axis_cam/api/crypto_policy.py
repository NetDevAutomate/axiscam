"""Cryptographic Policy API module.

This module provides access to cryptographic policy settings on AXIS devices
via the VAPIX crypto-policy API.

API Endpoints:
    - /config/rest/crypto-policy/v1 (REST API)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import CipherSuite, CryptoPolicyConfig, TlsVersion


class CryptoPolicyAPI(BaseAPI):
    """API module for cryptographic policy configuration.

    This module provides methods to retrieve and manage crypto settings:
    - TLS version requirements
    - Cipher suite configuration
    - HSTS settings
    - OCSP stapling

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.crypto_policy.get_config()
        ...     print(f"Min TLS: {config.tls_min_version}")
        ...     print(f"Weak ciphers: {config.weak_ciphers_enabled}")
    """

    REST_PATH = "/config/rest/crypto-policy/v1"

    async def get_config(self) -> CryptoPolicyConfig:
        """Get cryptographic policy configuration.

        Returns:
            CryptoPolicyConfig model with crypto settings.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return CryptoPolicyConfig()

    async def get_tls_version_range(self) -> tuple[TlsVersion, TlsVersion]:
        """Get the allowed TLS version range.

        Returns:
            Tuple of (min_version, max_version).
        """
        config = await self.get_config()
        return (config.tls_min_version, config.tls_max_version)

    async def get_cipher_suites(self) -> list[CipherSuite]:
        """Get list of cipher suites.

        Returns:
            List of CipherSuite models.
        """
        config = await self.get_config()
        return config.cipher_suites

    async def get_enabled_ciphers(self) -> list[CipherSuite]:
        """Get only enabled cipher suites.

        Returns:
            List of enabled CipherSuite models.
        """
        config = await self.get_config()
        return [c for c in config.cipher_suites if c.enabled]

    async def weak_ciphers_enabled(self) -> bool:
        """Check if weak ciphers are enabled.

        Returns:
            True if weak ciphers are allowed.
        """
        config = await self.get_config()
        return config.weak_ciphers_enabled

    async def hsts_enabled(self) -> bool:
        """Check if HSTS is enabled.

        Returns:
            True if HSTS is active.
        """
        config = await self.get_config()
        return config.hsts_enabled

    def _parse_config(self, data: dict[str, Any]) -> CryptoPolicyConfig:
        """Parse cryptographic policy configuration response.

        Args:
            data: Raw API response data.

        Returns:
            CryptoPolicyConfig model instance.
        """
        # Parse TLS versions
        tls_min_str = data.get("tlsMinVersion", "1.2")
        tls_max_str = data.get("tlsMaxVersion", "1.3")

        try:
            tls_min = TlsVersion(tls_min_str)
        except ValueError:
            tls_min = TlsVersion.TLS_1_2

        try:
            tls_max = TlsVersion(tls_max_str)
        except ValueError:
            tls_max = TlsVersion.TLS_1_3

        # Parse cipher suites
        cipher_suites = []
        for cipher_data in data.get("cipherSuites", []):
            if isinstance(cipher_data, dict):
                cipher = CipherSuite(
                    name=cipher_data.get("name", ""),
                    enabled=cipher_data.get("enabled", True),
                    strength=cipher_data.get("strength", ""),
                    key_exchange=cipher_data.get("keyExchange", ""),
                    authentication=cipher_data.get("authentication", ""),
                    encryption=cipher_data.get("encryption", ""),
                    mac=cipher_data.get("mac", ""),
                )
                cipher_suites.append(cipher)

        return CryptoPolicyConfig(
            tls_min_version=tls_min,
            tls_max_version=tls_max,
            cipher_suites=cipher_suites,
            weak_ciphers_enabled=data.get("weakCiphersEnabled", False),
            prefer_server_ciphers=data.get("preferServerCiphers", True),
            session_tickets_enabled=data.get("sessionTicketsEnabled", True),
            ocsp_stapling_enabled=data.get("ocspStaplingEnabled", False),
            hsts_enabled=data.get("hstsEnabled", False),
            hsts_max_age=data.get("hstsMaxAge", 31536000),
            hsts_include_subdomains=data.get("hstsIncludeSubdomains", False),
        )
