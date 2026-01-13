"""LLDP API module.

This module provides access to LLDP (Link Layer Discovery Protocol)
information from AXIS devices via the VAPIX LLDP API.

API Endpoints:
    - /config/rest/lldp/v1 (REST API)

LLDP is used to discover network topology information. The device reports
its LLDP neighbors (typically network switches) which can be useful for
network documentation and troubleshooting.
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import LldpInfo, LldpNeighbor


class LldpAPI(BaseAPI):
    """API module for LLDP neighbor discovery.

    This module provides methods to retrieve LLDP information including:
    - LLDP activation status
    - Neighbor information (switches, routers)
    - Connected port details

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     lldp_info = await camera.lldp.get_info()
        ...     print(f"LLDP Enabled: {lldp_info.activated}")
        ...     for neighbor in lldp_info.neighbors:
        ...         print(f"Connected to: {neighbor.sys_name} ({neighbor.port_id.value})")
    """

    # REST API endpoint
    REST_PATH = "/config/rest/lldp/v1"

    async def get_info(self) -> LldpInfo:
        """Get LLDP configuration and neighbor information.

        Returns:
            LldpInfo model with LLDP state and neighbors.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_response(data)
        except Exception:
            return LldpInfo()

    async def get_neighbors(self) -> list[LldpNeighbor]:
        """Get list of LLDP neighbors.

        Returns:
            List of LldpNeighbor models.
        """
        info = await self.get_info()
        return info.neighbors

    async def is_enabled(self) -> bool:
        """Check if LLDP is enabled on the device.

        Returns:
            True if LLDP is activated.
        """
        info = await self.get_info()
        return info.activated

    def _parse_response(self, data: dict[str, Any]) -> LldpInfo:
        """Parse LLDP API response into LldpInfo model.

        Args:
            data: Raw API response data.

        Returns:
            LldpInfo model instance.
        """
        activated = data.get("activated", False)
        neighbors_data = data.get("neighbors", [])

        neighbors = []
        for neighbor_data in neighbors_data:
            try:
                neighbor = LldpNeighbor.model_validate(neighbor_data)
                neighbors.append(neighbor)
            except Exception:
                # Skip malformed neighbor entries
                continue

        return LldpInfo(activated=activated, neighbors=neighbors)
