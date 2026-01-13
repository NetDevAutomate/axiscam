"""Geolocation API module.

This module provides access to device geolocation settings on AXIS devices
via the VAPIX geolocation API.

API Endpoints:
    - /config/rest/geolocation/v1beta (REST API)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import GeolocationConfig


class GeolocationAPI(BaseAPI):
    """API module for device geolocation configuration.

    This module provides methods to retrieve and manage geolocation:
    - GPS coordinates
    - Altitude and direction
    - Location metadata

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.geolocation.get_config()
        ...     if config.latitude and config.longitude:
        ...         print(f"Location: {config.latitude}, {config.longitude}")
    """

    REST_PATH = "/config/rest/geolocation/v1beta"

    async def get_config(self) -> GeolocationConfig:
        """Get geolocation configuration.

        Returns:
            GeolocationConfig model with location settings.
        """
        try:
            response = await self._get(self.REST_PATH)
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return GeolocationConfig()

    async def get_coordinates(self) -> tuple[float | None, float | None]:
        """Get GPS coordinates.

        Returns:
            Tuple of (latitude, longitude) or (None, None) if not set.
        """
        config = await self.get_config()
        return (config.latitude, config.longitude)

    async def get_altitude(self) -> float | None:
        """Get altitude.

        Returns:
            Altitude in meters or None if not set.
        """
        config = await self.get_config()
        return config.altitude

    def _parse_config(self, data: dict[str, Any]) -> GeolocationConfig:
        """Parse geolocation configuration response.

        Args:
            data: Raw API response data.

        Returns:
            GeolocationConfig model instance.
        """
        return GeolocationConfig(
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            altitude=data.get("altitude"),
            direction=data.get("direction"),
            horizontal_accuracy=data.get("horizontalAccuracy"),
            vertical_accuracy=data.get("verticalAccuracy"),
            heading=data.get("heading"),
            speed=data.get("speed"),
            timestamp=data.get("timestamp"),
        )
