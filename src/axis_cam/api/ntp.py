"""Network Time Sync (NTP) API module.

This module provides access to NTP configuration on AXIS devices
via the VAPIX network-time-sync API.

API Endpoints:
    - /config/rest/network-time-sync/v1beta (REST API)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import NtpConfig, NtpServer, NtpSyncStatus


class NtpAPI(BaseAPI):
    """API module for NTP configuration.

    This module provides methods to retrieve and manage NTP settings:
    - NTP enabled/disabled state
    - NTP server configuration
    - Synchronization status
    - DHCP-provided NTP servers

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.ntp.get_config()
        ...     print(f"NTP enabled: {config.enabled}")
        ...     for server in config.servers:
        ...         print(f"  Server: {server.address}")
    """

    REST_PATH = "/config/rest/network-time-sync/v1beta"

    async def get_config(self) -> NtpConfig:
        """Get NTP configuration.

        Returns:
            NtpConfig model with NTP settings.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return NtpConfig()

    async def is_enabled(self) -> bool:
        """Check if NTP is enabled.

        Returns:
            True if NTP is active.
        """
        config = await self.get_config()
        return config.enabled

    async def get_servers(self) -> list[NtpServer]:
        """Get list of configured NTP servers.

        Returns:
            List of NtpServer models.
        """
        config = await self.get_config()
        return config.servers

    async def get_sync_status(self) -> NtpSyncStatus:
        """Get NTP synchronization status.

        Returns:
            NtpSyncStatus model.
        """
        config = await self.get_config()
        return config.sync_status

    async def is_synchronized(self) -> bool:
        """Check if time is synchronized via NTP.

        Returns:
            True if synchronized.
        """
        config = await self.get_config()
        return config.sync_status.synchronized

    def _parse_config(self, data: dict[str, Any]) -> NtpConfig:
        """Parse NTP configuration response.

        Args:
            data: Raw API response data.

        Returns:
            NtpConfig model instance.
        """
        # Parse NTP servers
        servers = []
        for server_data in data.get("servers", []):
            if isinstance(server_data, dict):
                server = NtpServer(
                    address=server_data.get("address", ""),
                    enabled=server_data.get("enabled", True),
                    prefer=server_data.get("prefer", False),
                    source=server_data.get("source", "static"),
                )
                servers.append(server)
            elif isinstance(server_data, str):
                servers.append(NtpServer(address=server_data))

        # Parse sync status
        status_data = data.get("status", {})
        sync_status = NtpSyncStatus(
            synchronized=status_data.get("synchronized", False),
            current_server=status_data.get("currentServer", ""),
            stratum=status_data.get("stratum", 0),
            offset_ms=status_data.get("offset", 0.0),
            last_sync=status_data.get("lastSync", ""),
        )

        return NtpConfig(
            enabled=data.get("enabled", False),
            servers=servers,
            sync_status=sync_status,
            use_dhcp_servers=data.get("useDHCPServers", False),
            fallback_enabled=data.get("fallbackEnabled", False),
        )
