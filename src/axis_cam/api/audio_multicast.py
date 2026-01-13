"""Audio Multicast Control API module.

This module provides access to audio multicast configuration on AXIS devices
via the VAPIX audio-multicast-ctrl API.

API Endpoints:
    - /config/rest/audio-multicast-ctrl/v1beta (REST API)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import (
    AudioMulticastConfig,
    AudioStream,
    MulticastGroup,
)


class AudioMulticastAPI(BaseAPI):
    """API module for audio multicast configuration.

    This module provides methods to configure audio multicast streaming:
    - Multicast group configuration
    - Audio stream settings
    - Codec and bitrate configuration
    - Audio source selection

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.audio_multicast.get_config()
        ...     for group in config.groups:
        ...         print(f"Group: {group.name} -> {group.address}:{group.port}")
    """

    REST_PATH = "/config/rest/audio-multicast-ctrl/v1beta"

    async def get_config(self) -> AudioMulticastConfig:
        """Get complete audio multicast configuration.

        Returns:
            AudioMulticastConfig model with all settings.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return AudioMulticastConfig()

    async def get_groups(self) -> list[MulticastGroup]:
        """Get list of multicast groups.

        Returns:
            List of MulticastGroup models.
        """
        config = await self.get_config()
        return config.groups

    async def get_streams(self) -> list[AudioStream]:
        """Get list of audio streams.

        Returns:
            List of AudioStream models.
        """
        config = await self.get_config()
        return config.streams

    async def get_group(self, group_id: str) -> MulticastGroup | None:
        """Get a specific multicast group by ID.

        Args:
            group_id: Group identifier.

        Returns:
            MulticastGroup model or None if not found.
        """
        groups = await self.get_groups()
        for group in groups:
            if group.id == group_id:
                return group
        return None

    async def get_stream(self, stream_id: str) -> AudioStream | None:
        """Get a specific audio stream by ID.

        Args:
            stream_id: Stream identifier.

        Returns:
            AudioStream model or None if not found.
        """
        streams = await self.get_streams()
        for stream in streams:
            if stream.id == stream_id:
                return stream
        return None

    def _parse_config(self, data: dict[str, Any]) -> AudioMulticastConfig:
        """Parse audio multicast configuration response.

        Args:
            data: Raw API response data.

        Returns:
            AudioMulticastConfig model instance.
        """
        # Parse multicast groups
        groups = []
        groups_data = data.get("groups", {})
        for group_id, group_info in groups_data.items():
            if isinstance(group_info, dict):
                groups.append(self._parse_group(group_id, group_info))

        # Parse audio streams
        streams = []
        streams_data = data.get("streams", {})
        for stream_id, stream_info in streams_data.items():
            if isinstance(stream_info, dict):
                streams.append(self._parse_stream(stream_id, stream_info))

        return AudioMulticastConfig(
            enabled=data.get("enabled", False),
            groups=groups,
            streams=streams,
            default_ttl=data.get("defaultTtl", 64),
            audio_source=data.get("audioSource", ""),
        )

    def _parse_group(self, group_id: str, data: dict[str, Any]) -> MulticastGroup:
        """Parse multicast group data.

        Args:
            group_id: Group identifier.
            data: Group configuration data.

        Returns:
            MulticastGroup model.
        """
        return MulticastGroup(
            id=group_id,
            name=data.get("name", ""),
            enabled=data.get("enabled", False),
            address=data.get("address", ""),
            port=data.get("port", 0),
            ttl=data.get("ttl", 64),
            stream_id=data.get("streamId", ""),
        )

    def _parse_stream(self, stream_id: str, data: dict[str, Any]) -> AudioStream:
        """Parse audio stream data.

        Args:
            stream_id: Stream identifier.
            data: Stream configuration data.

        Returns:
            AudioStream model.
        """
        return AudioStream(
            id=stream_id,
            name=data.get("name", ""),
            enabled=data.get("enabled", False),
            codec=data.get("codec", ""),
            sample_rate=data.get("sampleRate", 16000),
            bitrate=data.get("bitrate", 64000),
            channels=data.get("channels", 1),
            source=data.get("source", ""),
        )
