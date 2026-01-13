"""SNMP API module.

This module provides access to SNMP configuration on AXIS devices
via the VAPIX SNMP API.

API Endpoints:
    - /config/rest/snmp/v1 (REST API)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import SnmpConfig, SnmpTrapReceiver, SnmpVersion


class SnmpAPI(BaseAPI):
    """API module for SNMP configuration.

    This module provides methods to retrieve and manage SNMP settings:
    - SNMP enabled/disabled state
    - SNMP version configuration
    - Community strings
    - Trap receivers
    - System contact/location

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.snmp.get_config()
        ...     print(f"SNMP enabled: {config.enabled}")
        ...     print(f"SNMP version: {config.version}")
    """

    REST_PATH = "/config/rest/snmp/v1"

    async def get_config(self) -> SnmpConfig:
        """Get SNMP configuration.

        Returns:
            SnmpConfig model with SNMP settings.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return SnmpConfig()

    async def is_enabled(self) -> bool:
        """Check if SNMP is enabled.

        Returns:
            True if SNMP is active.
        """
        config = await self.get_config()
        return config.enabled

    async def get_version(self) -> SnmpVersion:
        """Get SNMP version.

        Returns:
            SNMP version in use.
        """
        config = await self.get_config()
        return config.version

    async def get_trap_receivers(self) -> list[SnmpTrapReceiver]:
        """Get list of SNMP trap receivers.

        Returns:
            List of SnmpTrapReceiver models.
        """
        config = await self.get_config()
        return config.trap_receivers

    def _parse_config(self, data: dict[str, Any]) -> SnmpConfig:
        """Parse SNMP configuration response.

        Args:
            data: Raw API response data.

        Returns:
            SnmpConfig model instance.
        """
        # Parse version
        version_str = data.get("version", "v2c")
        try:
            version = SnmpVersion(version_str.lower())
        except ValueError:
            version = SnmpVersion.V2C

        # Parse trap receivers
        trap_receivers = []
        for trap_data in data.get("trapReceivers", []):
            if isinstance(trap_data, dict):
                receiver = SnmpTrapReceiver(
                    address=trap_data.get("address", ""),
                    port=trap_data.get("port", 162),
                    community=trap_data.get("community", ""),
                    enabled=trap_data.get("enabled", True),
                )
                trap_receivers.append(receiver)

        return SnmpConfig(
            enabled=data.get("enabled", False),
            version=version,
            read_community=data.get("readCommunity", "public"),
            write_community=data.get("writeCommunity", ""),
            system_contact=data.get("systemContact", ""),
            system_location=data.get("systemLocation", ""),
            trap_receivers=trap_receivers,
            v3_enabled=data.get("v3", {}).get("enabled", False),
            v3_username=data.get("v3", {}).get("username", ""),
            v3_auth_protocol=data.get("v3", {}).get("authProtocol", ""),
            v3_priv_protocol=data.get("v3", {}).get("privProtocol", ""),
        )
