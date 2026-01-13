"""Remote Object Storage API module.

This module provides access to remote/cloud storage configuration on AXIS devices
via the VAPIX remote-object-storage API.

API Endpoints:
    - /config/rest/remote-object-storage/v1 (REST API)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import RemoteStorageConfig, StorageDestination, StorageType


class RemoteStorageAPI(BaseAPI):
    """API module for remote object storage configuration.

    This module provides methods to retrieve and manage cloud storage:
    - Storage destinations (S3, Azure, etc.)
    - Connection credentials
    - Upload settings

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.remote_storage.get_config()
        ...     for dest in config.destinations:
        ...         print(f"Storage: {dest.name} ({dest.storage_type.value})")
    """

    REST_PATH = "/config/rest/remote-object-storage/v1"

    async def get_config(self) -> RemoteStorageConfig:
        """Get complete remote storage configuration.

        Returns:
            RemoteStorageConfig model with storage settings.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return RemoteStorageConfig()

    async def get_destinations(self) -> list[StorageDestination]:
        """Get list of storage destinations.

        Returns:
            List of StorageDestination models.
        """
        config = await self.get_config()
        return config.destinations

    async def get_destination(self, dest_id: str) -> StorageDestination | None:
        """Get a specific storage destination by ID.

        Args:
            dest_id: Destination identifier.

        Returns:
            StorageDestination model or None if not found.
        """
        destinations = await self.get_destinations()
        for dest in destinations:
            if dest.id == dest_id:
                return dest
        return None

    def _parse_config(self, data: dict[str, Any]) -> RemoteStorageConfig:
        """Parse remote storage configuration response.

        Args:
            data: Raw API response data.

        Returns:
            RemoteStorageConfig model instance.
        """
        # Parse destinations
        destinations = []
        dest_data = data.get("destinations", {})
        for dest_id, dest_info in dest_data.items():
            if isinstance(dest_info, dict):
                destinations.append(self._parse_destination(dest_id, dest_info))

        return RemoteStorageConfig(
            destinations=destinations,
        )

    def _parse_destination(
        self, dest_id: str, data: dict[str, Any]
    ) -> StorageDestination:
        """Parse storage destination data.

        Args:
            dest_id: Destination identifier.
            data: Destination configuration data.

        Returns:
            StorageDestination model.
        """
        storage_type_str = data.get("type", "s3").lower()
        try:
            storage_type = StorageType(storage_type_str)
        except ValueError:
            storage_type = StorageType.S3

        return StorageDestination(
            id=dest_id,
            name=data.get("name", ""),
            storage_type=storage_type,
            endpoint=data.get("endpoint", ""),
            bucket=data.get("bucket", ""),
            region=data.get("region", ""),
            access_key_id=data.get("accessKeyId", ""),
            prefix=data.get("prefix", ""),
            enabled=data.get("enabled", False),
        )
