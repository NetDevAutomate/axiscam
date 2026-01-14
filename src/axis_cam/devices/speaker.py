"""AXIS Speaker device class.

This module provides the AxisSpeaker class for interacting with
AXIS network speakers and audio devices (C-series).
"""

from typing import Any

from axis_cam.devices.base import AxisDevice
from axis_cam.models import AudioMulticastConfig, DeviceType


class AxisSpeaker(AxisDevice):
    """AXIS Speaker/Audio device.

    This class represents AXIS network speakers and provides
    access to speaker-specific functionality including audio
    playback and multicast audio.

    Supported speaker types:
    - C1410 Network Mini Speaker
    - C-series speakers

    Example:
        >>> async with AxisSpeaker("192.168.1.45", "admin", "pass") as speaker:
        ...     info = await speaker.get_info()
        ...     print(f"Speaker: {info.product_number}")
        ...     audio_config = await speaker.get_audio_config()

    Attributes:
        device_type: Always DeviceType.SPEAKER.
    """

    device_type = DeviceType.SPEAKER

    # Audio multicast control API endpoint
    AUDIO_MULTICAST_PATH = "/config/rest/audio-multicast-ctrl/v1beta"

    async def get_device_specific_info(self) -> dict[str, Any]:
        """Get speaker-specific information.

        Returns:
            Dictionary with speaker capabilities.
        """
        capabilities = await self.get_capabilities()
        info = await self.get_info()

        return {
            "device_type": self.device_type.value,
            "model": info.product_number,
            "serial_number": info.serial_number,
            "firmware": info.firmware_version,
            "audio_multicast_supported": "audio-multicast-ctrl" in capabilities.supported_apis,
            "available_apis": capabilities.supported_apis,
        }

    async def get_audio_config(self) -> dict[str, Any]:
        """Get audio configuration.

        Returns:
            Dictionary with audio settings.
        """
        try:
            response = await self._client.get_json(
                "/axis-cgi/param.cgi",
                {"action": "list", "group": "root.Audio"},
            )
            return response.get("root", {}).get("Audio", {})
        except Exception:
            return {}

    async def get_audio_multicast_config(self) -> AudioMulticastConfig:
        """Get audio multicast configuration.

        Returns:
            AudioMulticastConfig model with multicast groups and streams.
        """
        # Use the base class implementation via the audio_multicast API
        return await self.audio_multicast.get_config()

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

    async def get_volume(self) -> int | None:
        """Get current speaker volume level.

        Returns:
            Volume level (0-100) or None if unavailable.
        """
        audio_config = await self.get_audio_config()
        volume_str = audio_config.get("OutputGain")
        if volume_str:
            try:
                return int(volume_str)
            except ValueError:
                pass
        return None

    async def has_multicast(self) -> bool:
        """Check if audio multicast is supported.

        Returns:
            True if audio multicast is supported.
        """
        capabilities = await self.get_capabilities()
        return "audio-multicast-ctrl" in capabilities.supported_apis

    async def get_audio_clips(self) -> list[dict[str, Any]]:
        """Get list of audio clips stored on the device.

        Returns:
            List of audio clip information.
        """
        try:
            response = await self._client.get_json(
                "/axis-cgi/mediaclip.cgi",
                {"action": "list"},
            )
            return response.get("clips", [])
        except Exception:
            return []
