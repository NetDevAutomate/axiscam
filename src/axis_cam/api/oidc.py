"""OIDC Setup API module.

This module provides access to OpenID Connect configuration on AXIS devices
via the VAPIX oidcsetup API.

API Endpoints:
    - /config/rest/oidcsetup/v1 (REST API)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import OidcClaimMapping, OidcConfig, OidcProviderConfig


class OidcAPI(BaseAPI):
    """API module for OpenID Connect configuration.

    This module provides methods to retrieve and manage OIDC settings:
    - OIDC provider configuration
    - Claim mappings
    - Session settings
    - Local authentication fallback

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.oidc.get_config()
        ...     print(f"OIDC enabled: {config.enabled}")
        ...     if config.provider:
        ...         print(f"Issuer: {config.provider.issuer_uri}")
    """

    REST_PATH = "/config/rest/oidcsetup/v1"

    async def get_config(self) -> OidcConfig:
        """Get OIDC configuration.

        Returns:
            OidcConfig model with OIDC settings.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return OidcConfig()

    async def is_enabled(self) -> bool:
        """Check if OIDC authentication is enabled.

        Returns:
            True if OIDC is active.
        """
        config = await self.get_config()
        return config.enabled

    async def get_provider(self) -> OidcProviderConfig | None:
        """Get OIDC provider configuration.

        Returns:
            OidcProviderConfig model or None if not configured.
        """
        config = await self.get_config()
        return config.provider

    async def get_claim_mappings(self) -> list[OidcClaimMapping]:
        """Get claim-to-attribute mappings.

        Returns:
            List of OidcClaimMapping models.
        """
        config = await self.get_config()
        return config.claim_mappings

    async def local_auth_allowed(self) -> bool:
        """Check if local authentication fallback is allowed.

        Returns:
            True if local authentication is permitted.
        """
        config = await self.get_config()
        return config.allow_local_auth

    def _parse_config(self, data: dict[str, Any]) -> OidcConfig:
        """Parse OIDC configuration response.

        Args:
            data: Raw API response data.

        Returns:
            OidcConfig model instance.
        """
        # Parse provider configuration
        provider_data = data.get("provider", {})
        provider = None
        if provider_data:
            provider = OidcProviderConfig(
                issuer_uri=provider_data.get("issuerUri", ""),
                client_id=provider_data.get("clientId", ""),
                authorization_endpoint=provider_data.get("authorizationEndpoint", ""),
                token_endpoint=provider_data.get("tokenEndpoint", ""),
                userinfo_endpoint=provider_data.get("userinfoEndpoint", ""),
                jwks_uri=provider_data.get("jwksUri", ""),
                scopes=provider_data.get("scopes", ["openid", "profile"]),
                response_type=provider_data.get("responseType", "code"),
            )

        # Parse claim mappings
        claim_mappings = []
        for mapping_data in data.get("claimMappings", []):
            if isinstance(mapping_data, dict):
                mapping = OidcClaimMapping(
                    claim_name=mapping_data.get("claimName", ""),
                    device_attribute=mapping_data.get("deviceAttribute", ""),
                    required=mapping_data.get("required", False),
                )
                claim_mappings.append(mapping)

        return OidcConfig(
            enabled=data.get("enabled", False),
            provider=provider,
            redirect_uri=data.get("redirectUri", ""),
            logout_uri=data.get("logoutUri", ""),
            claim_mappings=claim_mappings,
            admin_claim=data.get("adminClaim", ""),
            admin_claim_value=data.get("adminClaimValue", ""),
            session_timeout=data.get("sessionTimeout", 3600),
            allow_local_auth=data.get("allowLocalAuth", True),
        )
