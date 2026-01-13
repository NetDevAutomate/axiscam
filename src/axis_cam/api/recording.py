"""Recording Group API module.

This module provides access to recording group configuration on AXIS devices
via the VAPIX recording-group API.

API Endpoints:
    - /config/rest/recording-group/v1 (REST API)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import RecordingConfig, RecordingGroup, RecordingProfile


class RecordingAPI(BaseAPI):
    """API module for recording group configuration.

    This module provides methods to retrieve and manage recordings:
    - Recording groups and profiles
    - Storage destinations
    - Recording schedules

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.recording.get_config()
        ...     for group in config.groups:
        ...         print(f"Group: {group.name} - Storage: {group.storage_id}")
    """

    REST_PATH = "/config/rest/recording-group/v1"

    async def get_config(self) -> RecordingConfig:
        """Get complete recording configuration.

        Returns:
            RecordingConfig model with recording settings.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return RecordingConfig()

    async def get_groups(self) -> list[RecordingGroup]:
        """Get list of recording groups.

        Returns:
            List of RecordingGroup models.
        """
        config = await self.get_config()
        return config.groups

    async def get_profiles(self) -> list[RecordingProfile]:
        """Get list of recording profiles.

        Returns:
            List of RecordingProfile models.
        """
        config = await self.get_config()
        return config.profiles

    async def get_group(self, group_id: str) -> RecordingGroup | None:
        """Get a specific recording group by ID.

        Args:
            group_id: Group identifier.

        Returns:
            RecordingGroup model or None if not found.
        """
        groups = await self.get_groups()
        for group in groups:
            if group.id == group_id:
                return group
        return None

    def _parse_config(self, data: dict[str, Any]) -> RecordingConfig:
        """Parse recording configuration response.

        Args:
            data: Raw API response data.

        Returns:
            RecordingConfig model instance.
        """
        # Parse groups
        groups = []
        groups_data = data.get("groups", {})
        for group_id, group_info in groups_data.items():
            if isinstance(group_info, dict):
                groups.append(self._parse_group(group_id, group_info))

        # Parse profiles
        profiles = []
        profiles_data = data.get("profiles", {})
        for profile_id, profile_info in profiles_data.items():
            if isinstance(profile_info, dict):
                profiles.append(self._parse_profile(profile_id, profile_info))

        return RecordingConfig(
            groups=groups,
            profiles=profiles,
        )

    def _parse_group(self, group_id: str, data: dict[str, Any]) -> RecordingGroup:
        """Parse recording group data.

        Args:
            group_id: Group identifier.
            data: Group configuration data.

        Returns:
            RecordingGroup model.
        """
        return RecordingGroup(
            id=group_id,
            name=data.get("name", ""),
            description=data.get("description", ""),
            storage_id=data.get("storageId", ""),
            retention_days=data.get("retentionDays", 0),
            max_size_mb=data.get("maxSizeMB", 0),
            profile_id=data.get("profileId", ""),
        )

    def _parse_profile(
        self, profile_id: str, data: dict[str, Any]
    ) -> RecordingProfile:
        """Parse recording profile data.

        Args:
            profile_id: Profile identifier.
            data: Profile configuration data.

        Returns:
            RecordingProfile model.
        """
        return RecordingProfile(
            id=profile_id,
            name=data.get("name", ""),
            format=data.get("format", "mkv"),
            video_codec=data.get("videoCodec", "h264"),
            audio_enabled=data.get("audioEnabled", False),
            resolution=data.get("resolution", ""),
            framerate=data.get("framerate", 0),
            bitrate=data.get("bitrate", 0),
        )
