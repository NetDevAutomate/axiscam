"""SSH API module.

This module provides access to SSH configuration on AXIS devices
via the VAPIX SSH API.

API Endpoints:
    - /config/rest/ssh/v2 (REST API)
    - /config/rest/ssh/v1beta (fallback)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import SshConfig, SshKey


class SshAPI(BaseAPI):
    """API module for SSH configuration.

    This module provides methods to retrieve and manage SSH settings:
    - SSH enabled/disabled state
    - SSH port configuration
    - Authorized keys management
    - Root login settings

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.ssh.get_config()
        ...     print(f"SSH enabled: {config.enabled}")
        ...     print(f"SSH port: {config.port}")
    """

    REST_PATH = "/config/rest/ssh/v2"
    REST_PATH_BETA = "/config/rest/ssh/v1beta"

    async def get_config(self) -> SshConfig:
        """Get SSH configuration.

        Returns:
            SshConfig model with SSH settings.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            # Try beta API
            try:
                response = await self._get(self.REST_PATH_BETA, params={"recursive": "true"})
                data = response.get("data", {})
                return self._parse_config(data)
            except Exception:
                return SshConfig()

    async def is_enabled(self) -> bool:
        """Check if SSH is enabled.

        Returns:
            True if SSH is active.
        """
        config = await self.get_config()
        return config.enabled

    async def get_port(self) -> int:
        """Get SSH port number.

        Returns:
            SSH port number.
        """
        config = await self.get_config()
        return config.port

    async def get_authorized_keys(self) -> list[SshKey]:
        """Get list of authorized SSH keys.

        Returns:
            List of SshKey models.
        """
        config = await self.get_config()
        return config.authorized_keys

    async def root_login_allowed(self) -> bool:
        """Check if root login is allowed.

        Returns:
            True if root login is permitted.
        """
        config = await self.get_config()
        return config.root_login_allowed

    def _parse_config(self, data: dict[str, Any]) -> SshConfig:
        """Parse SSH configuration response.

        Args:
            data: Raw API response data.

        Returns:
            SshConfig model instance.
        """
        # Parse authorized keys
        authorized_keys = []
        for key_data in data.get("authorizedKeys", []):
            if isinstance(key_data, dict):
                key = SshKey(
                    key_type=key_data.get("type", ""),
                    key=key_data.get("key", ""),
                    comment=key_data.get("comment", ""),
                    fingerprint=key_data.get("fingerprint", ""),
                )
                authorized_keys.append(key)

        return SshConfig(
            enabled=data.get("enabled", False),
            port=data.get("port", 22),
            root_login_allowed=data.get("rootLoginAllowed", False),
            password_auth_enabled=data.get("passwordAuthEnabled", True),
            authorized_keys=authorized_keys,
        )
