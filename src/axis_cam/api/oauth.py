"""OAuth Client Credentials Grant API module.

This module provides access to OAuth 2.0 Client Credentials Grant configuration
on AXIS devices via the VAPIX oauth-ccgrant API.

API Endpoints:
    - /config/rest/oauth-ccgrant/v1 (REST API)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import OAuthConfig, OAuthCredentialConfig, OAuthTokenStatus


class OAuthAPI(BaseAPI):
    """API module for OAuth 2.0 Client Credentials Grant configuration.

    This module provides methods to retrieve and manage OAuth credentials:
    - Client credentials configuration
    - Token status monitoring
    - Credential management

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.oauth.get_config()
        ...     print(f"OAuth enabled: {config.enabled}")
        ...     for cred in config.credentials:
        ...         print(f"Credential: {cred.name} ({cred.client_id})")
    """

    REST_PATH = "/config/rest/oauth-ccgrant/v1"

    async def get_config(self) -> OAuthConfig:
        """Get OAuth configuration.

        Returns:
            OAuthConfig model with OAuth settings.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return OAuthConfig()

    async def is_enabled(self) -> bool:
        """Check if OAuth client credentials is enabled.

        Returns:
            True if OAuth is active.
        """
        config = await self.get_config()
        return config.enabled

    async def get_credentials(self) -> list[OAuthCredentialConfig]:
        """Get list of configured credentials.

        Returns:
            List of OAuthCredentialConfig models.
        """
        config = await self.get_config()
        return config.credentials

    async def get_token_statuses(self) -> list[OAuthTokenStatus]:
        """Get token status for all credentials.

        Returns:
            List of OAuthTokenStatus models.
        """
        config = await self.get_config()
        return config.token_statuses

    async def get_default_credential(self) -> OAuthCredentialConfig | None:
        """Get the default credential configuration.

        Returns:
            OAuthCredentialConfig or None if no default is set.
        """
        config = await self.get_config()
        if not config.default_credential:
            return None
        for cred in config.credentials:
            if cred.credential_id == config.default_credential:
                return cred
        return None

    def _parse_config(self, data: dict[str, Any]) -> OAuthConfig:
        """Parse OAuth configuration response.

        Args:
            data: Raw API response data.

        Returns:
            OAuthConfig model instance.
        """
        # Parse credentials
        credentials = []
        for cred_data in data.get("credentials", []):
            if isinstance(cred_data, dict):
                cred = OAuthCredentialConfig(
                    credential_id=cred_data.get("credentialId", ""),
                    name=cred_data.get("name", ""),
                    token_endpoint=cred_data.get("tokenEndpoint", ""),
                    client_id=cred_data.get("clientId", ""),
                    scope=cred_data.get("scope", ""),
                    enabled=cred_data.get("enabled", False),
                    grant_type=cred_data.get("grantType", "client_credentials"),
                    token_refresh_margin=cred_data.get("tokenRefreshMargin", 60),
                )
                credentials.append(cred)

        # Parse token statuses
        token_statuses = []
        for status_data in data.get("tokenStatuses", []):
            if isinstance(status_data, dict):
                status = OAuthTokenStatus(
                    credential_id=status_data.get("credentialId", ""),
                    valid=status_data.get("valid", False),
                    expires_at=status_data.get("expiresAt", ""),
                    scope=status_data.get("scope", ""),
                    error=status_data.get("error", ""),
                )
                token_statuses.append(status)

        return OAuthConfig(
            enabled=data.get("enabled", False),
            credentials=credentials,
            token_statuses=token_statuses,
            default_credential=data.get("defaultCredential", ""),
        )
