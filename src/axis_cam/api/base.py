"""Base class for AXIS VAPIX API modules.

This module provides the abstract base class for all API module implementations.
Each API module encapsulates a specific VAPIX API domain (device info, params, etc.)
and uses composition with the VapixClient for HTTP communication.
"""

from abc import ABC
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from axis_cam.client import VapixClient


class BaseAPI(ABC):  # noqa: B024
    """Abstract base class for VAPIX API modules.

    Each API module represents a specific domain of the VAPIX API
    (e.g., basic-device-info, param, time). This base class provides
    common functionality and defines the interface for all API modules.

    API modules are designed to be composed into device classes:

    Example:
        >>> class AxisCamera(AxisDevice):
        ...     def __init__(self, ...):
        ...         super().__init__(...)
        ...         self.device_info = BasicDeviceInfoAPI(self._client)
        ...         self.params = ParamAPI(self._client)

    Attributes:
        _client: The VapixClient instance for HTTP communication.
    """

    def __init__(self, client: "VapixClient") -> None:
        """Initialize the API module.

        Args:
            client: VapixClient instance for HTTP communication.
        """
        self._client = client

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Perform a GET request via the client.

        Args:
            path: URL path for the request.
            params: Optional query parameters.

        Returns:
            Response data (typically dict from JSON).
        """
        return await self._client.get_json(path, params)

    async def _post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> Any:
        """Perform a POST request via the client.

        Args:
            path: URL path for the request.
            data: Form data to send.
            json_data: JSON data to send.

        Returns:
            Response data (typically dict from JSON).
        """
        return await self._client.post_json(path, data=data, json_data=json_data)

    async def _get_raw(self, path: str, params: dict[str, Any] | None = None) -> bytes:
        """Perform a GET request and return raw bytes.

        Args:
            path: URL path for the request.
            params: Optional query parameters.

        Returns:
            Raw response bytes.
        """
        return await self._client.get_raw(path, params)
