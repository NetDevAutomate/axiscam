"""AXIS Intercom device class.

This module provides the AxisIntercom class for interacting with
AXIS network intercoms (I-series devices).
"""

from typing import Any

from axis_cam.devices.base import AxisDevice
from axis_cam.models import AudioMulticastConfig, DeviceType


class AxisIntercom(AxisDevice):
    """AXIS Intercom device.

    This class represents AXIS network intercoms and provides
    access to intercom-specific functionality including audio
    and video communication features.

    Supported intercom types:
    - I8016-LVE Network Video Intercom
    - I-series intercoms

    Example:
        >>> async with AxisIntercom("192.168.1.11", "admin", "pass") as intercom:
        ...     info = await intercom.get_info()
        ...     print(f"Intercom: {info.product_number}")
        ...     audio_status = await intercom.get_audio_status()

    Attributes:
        device_type: Always DeviceType.INTERCOM.
    """

    device_type = DeviceType.INTERCOM

    # Audio multicast control API endpoint
    AUDIO_MULTICAST_PATH = "/config/rest/audio-multicast-ctrl/v1beta"

    async def get_device_specific_info(self) -> dict[str, Any]:
        """Get intercom-specific information.

        Returns:
            Dictionary with intercom capabilities.
        """
        capabilities = await self.get_capabilities()
        info = await self.get_info()

        return {
            "device_type": self.device_type.value,
            "model": info.product_number,
            "serial_number": info.serial_number,
            "firmware": info.firmware_version,
            "audio_supported": capabilities.has_audio,
            "video_supported": "video-analytics" in capabilities.supported_apis,
            "available_apis": capabilities.supported_apis,
        }

    async def get_audio_status(self) -> dict[str, Any]:
        """Get audio subsystem status.

        Returns:
            Dictionary with audio device status.
        """
        try:
            response = await self._client.get_json("/axis-cgi/audio/audiostatus.cgi")
            return response
        except Exception:
            return {}

    async def get_audio_device_info(self) -> dict[str, Any]:
        """Get audio device information.

        Returns:
            Dictionary with audio device details.
        """
        try:
            response = await self._client.get_json("/axis-cgi/audio/getaudiodevices.cgi")
            return response
        except Exception:
            return {}

    async def get_audio_multicast_config(self) -> AudioMulticastConfig:
        """Get audio multicast configuration.

        Returns:
            AudioMulticastConfig model with multicast groups and streams.
        """
        # Use the base class implementation via the audio_multicast API
        return await self.audio_multicast.get_config()

    async def get_sip_config(self) -> dict[str, Any]:
        """Get SIP (VoIP) configuration.

        Returns:
            Dictionary with SIP settings.
        """
        try:
            response = await self._client.get_json(
                "/axis-cgi/param.cgi",
                {"action": "list", "group": "root.SIP"},
            )
            return response.get("root", {}).get("SIP", {})
        except Exception:
            return {}

    async def has_video(self) -> bool:
        """Check if the intercom has video capability.

        Returns:
            True if video is supported.
        """
        capabilities = await self.get_capabilities()
        return "video-analytics" in capabilities.supported_apis

    async def has_sip(self) -> bool:
        """Check if SIP is supported.

        Returns:
            True if SIP (VoIP) is supported.
        """
        sip_config = await self.get_sip_config()
        return bool(sip_config)

    async def get_snapshot_url(self, resolution: str | None = None) -> str:
        """Get the URL for retrieving a snapshot.

        Intercoms with video support can capture snapshots.

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
        """Get a snapshot image from the intercom.

        Only available on intercoms with video support.

        Args:
            resolution: Optional resolution (e.g., "1920x1080").

        Returns:
            JPEG image bytes.
        """
        params: dict[str, str] = {}
        if resolution:
            params["resolution"] = resolution

        return await self._client.get_raw("/axis-cgi/jpg/image.cgi", params)
