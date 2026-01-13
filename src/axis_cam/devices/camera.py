"""AXIS Camera device class.

This module provides the AxisCamera class for interacting with
AXIS network cameras (dome, bullet, PTZ, etc.).
"""

from typing import Any

from axis_cam.devices.base import AxisDevice
from axis_cam.models import DeviceType


class AxisCamera(AxisDevice):
    """AXIS Camera device.

    This class represents AXIS network cameras and provides access to
    camera-specific functionality including video, snapshots, and
    video analytics.

    Supported camera types:
    - Dome cameras (M series)
    - Bullet cameras (P series)
    - PTZ cameras (Q series)
    - Modular cameras (F series)

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     info = await camera.get_info()
        ...     print(f"Camera: {info.product_number}")
        ...     snapshot = await camera.get_snapshot()

    Attributes:
        device_type: Always DeviceType.CAMERA.
    """

    device_type = DeviceType.CAMERA

    async def get_device_specific_info(self) -> dict[str, Any]:
        """Get camera-specific information.

        Returns:
            Dictionary with camera capabilities and settings.
        """
        capabilities = await self.get_capabilities()
        info = await self.get_info()

        return {
            "device_type": self.device_type.value,
            "model": info.product_number,
            "serial_number": info.serial_number,
            "firmware": info.firmware_version,
            "ptz_supported": capabilities.has_ptz,
            "audio_supported": capabilities.has_audio,
            "analytics_supported": capabilities.has_analytics,
            "available_apis": capabilities.supported_apis,
        }

    async def get_snapshot_url(self, resolution: str | None = None) -> str:
        """Get the URL for retrieving a snapshot.

        Args:
            resolution: Optional resolution (e.g., "1920x1080").

        Returns:
            URL string for snapshot retrieval.
        """
        url = f"https://{self._host}/axis-cgi/jpg/image.cgi"
        if resolution:
            url += f"?resolution={resolution}"
        return url

    async def get_snapshot(self, resolution: str | None = None) -> bytes:
        """Get a snapshot image from the camera.

        Args:
            resolution: Optional resolution (e.g., "1920x1080").

        Returns:
            JPEG image bytes.
        """
        params: dict[str, str] = {}
        if resolution:
            params["resolution"] = resolution

        return await self._client.get_raw("/axis-cgi/jpg/image.cgi", params)

    async def get_video_stream_url(
        self,
        profile: str | None = None,
        codec: str = "h264",
    ) -> str:
        """Get the RTSP URL for video streaming.

        Args:
            profile: Video profile name (optional).
            codec: Video codec (h264, h265, mjpeg).

        Returns:
            RTSP URL for video streaming.
        """
        url = f"rtsp://{self._host}/axis-media/media.amp"
        params: list[str] = []

        if profile:
            params.append(f"streamprofile={profile}")
        if codec:
            params.append(f"videocodec={codec}")

        if params:
            url += "?" + "&".join(params)

        return url

    async def has_ptz(self) -> bool:
        """Check if the camera supports PTZ.

        Returns:
            True if PTZ is supported.
        """
        capabilities = await self.get_capabilities()
        return capabilities.has_ptz

    async def has_audio(self) -> bool:
        """Check if the camera has audio support.

        Returns:
            True if audio is supported.
        """
        capabilities = await self.get_capabilities()
        return capabilities.has_audio

    async def has_analytics(self) -> bool:
        """Check if the camera supports video analytics.

        Returns:
            True if analytics is supported.
        """
        capabilities = await self.get_capabilities()
        return capabilities.has_analytics

    async def get_video_sources(self) -> list[dict[str, Any]]:
        """Get available video sources.

        Returns:
            List of video source configurations.
        """
        try:
            response = await self._client.get_json(
                "/axis-cgi/videosourceconfig.cgi",
                {"action": "list"},
            )
            return response.get("videoSources", [])
        except Exception:
            return []

    async def get_stream_profiles(self) -> list[dict[str, Any]]:
        """Get configured stream profiles.

        Returns:
            List of stream profile configurations.
        """
        try:
            response = await self._client.get_json(
                "/axis-cgi/streamprofile.cgi",
                {"action": "list"},
            )
            return response.get("streamProfile", [])
        except Exception:
            return []
