"""AXIS Recorder device class.

This module provides the AxisRecorder class for interacting with
AXIS network video recorders (NVR devices like S-series).
"""

from typing import Any

from axis_cam.devices.base import AxisDevice
from axis_cam.models import DeviceType


class AxisRecorder(AxisDevice):
    """AXIS Recorder (NVR) device.

    This class represents AXIS network video recorders and provides
    access to recorder-specific functionality including recording
    management and storage.

    Supported recorder types:
    - S3008 Recorder
    - S30XX series NVRs

    Example:
        >>> async with AxisRecorder("192.168.1.100", "admin", "pass") as nvr:
        ...     info = await nvr.get_info()
        ...     print(f"NVR: {info.product_number}")
        ...     storage = await nvr.get_storage_info()

    Attributes:
        device_type: Always DeviceType.RECORDER.
    """

    device_type = DeviceType.RECORDER

    # Recording group API endpoint
    RECORDING_GROUP_PATH = "/config/rest/recording-group/v2"

    # Remote object storage API endpoint
    REMOTE_STORAGE_PATH = "/config/rest/remote-object-storage/v1"

    async def get_device_specific_info(self) -> dict[str, Any]:
        """Get recorder-specific information.

        Returns:
            Dictionary with recorder capabilities and storage info.
        """
        capabilities = await self.get_capabilities()
        info = await self.get_info()

        result: dict[str, Any] = {
            "device_type": self.device_type.value,
            "model": info.product_number,
            "serial_number": info.serial_number,
            "firmware": info.firmware_version,
            "available_apis": capabilities.supported_apis,
        }

        # Try to get storage info
        try:
            storage = await self.get_storage_info()
            result["storage"] = storage
        except Exception:
            result["storage"] = None

        return result

    async def get_recording_groups(self) -> list[dict[str, Any]]:
        """Get configured recording groups.

        Returns:
            List of recording group configurations.
        """
        try:
            response = await self._client.get_json(self.RECORDING_GROUP_PATH)
            return response.get("data", {}).get("recordingGroups", [])
        except Exception:
            return []

    async def get_recording_group(self, group_id: str) -> dict[str, Any] | None:
        """Get a specific recording group by ID.

        Args:
            group_id: Recording group identifier.

        Returns:
            Recording group configuration or None.
        """
        try:
            response = await self._client.get_json(
                f"{self.RECORDING_GROUP_PATH}/{group_id}"
            )
            return response.get("data")
        except Exception:
            return None

    async def get_storage_info(self) -> dict[str, Any]:
        """Get storage information.

        Returns:
            Dictionary with storage status and capacity.
        """
        try:
            response = await self._client.get_json(
                "/axis-cgi/storage.cgi",
                {"action": "list"},
            )
            return response
        except Exception:
            return {}

    async def get_disk_status(self) -> list[dict[str, Any]]:
        """Get status of connected disks.

        Returns:
            List of disk status information.
        """
        try:
            response = await self._client.get_json(
                "/axis-cgi/disks/list.cgi"
            )
            return response.get("disks", [])
        except Exception:
            return []

    async def get_remote_storage_config(self) -> dict[str, Any] | None:
        """Get remote object storage configuration.

        Returns:
            Remote storage configuration or None.
        """
        try:
            response = await self._client.get_json(self.REMOTE_STORAGE_PATH)
            return response.get("data")
        except Exception:
            return None

    async def get_connected_cameras(self) -> list[dict[str, Any]]:
        """Get list of cameras connected to this recorder.

        Returns:
            List of connected camera information.
        """
        try:
            # Use param.cgi to get connected devices
            response = await self._client.get_json(
                "/axis-cgi/param.cgi",
                {"action": "list", "group": "root.Network.AxisDevices"},
            )
            return response.get("root", {}).get("Network", {}).get("AxisDevices", [])
        except Exception:
            return []

    async def has_remote_storage(self) -> bool:
        """Check if remote object storage is configured.

        Returns:
            True if remote storage is configured.
        """
        capabilities = await self.get_capabilities()
        return "remote-object-storage" in capabilities.supported_apis
