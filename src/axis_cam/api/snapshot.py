"""Best Snapshot API module.

This module provides access to best snapshot/image capture on AXIS devices
via the VAPIX best-snapshot API.

API Endpoints:
    - /config/rest/best-snapshot/v1beta (REST API)
    - /axis-cgi/jpg/image.cgi (Legacy CGI for image capture)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import (
    BestSnapshotConfig,
    SnapshotProfile,
    SnapshotTrigger,
)


class BestSnapshotAPI(BaseAPI):
    """API module for best snapshot configuration.

    This module provides methods to retrieve snapshots and manage profiles:
    - Snapshot profile configuration
    - Trigger-based snapshot capture
    - Image quality settings
    - Snapshot storage configuration

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.snapshot.get_config()
        ...     for profile in config.profiles:
        ...         print(f"Profile: {profile.name}")
        ...     # Capture a snapshot
        ...     image = await camera.snapshot.capture()
    """

    REST_PATH = "/config/rest/best-snapshot/v1beta"
    IMAGE_CGI = "/axis-cgi/jpg/image.cgi"

    async def get_config(self) -> BestSnapshotConfig:
        """Get complete best snapshot configuration.

        Returns:
            BestSnapshotConfig model with all snapshot settings.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return BestSnapshotConfig()

    async def get_profiles(self) -> list[SnapshotProfile]:
        """Get list of snapshot profiles.

        Returns:
            List of SnapshotProfile models.
        """
        config = await self.get_config()
        return config.profiles

    async def get_triggers(self) -> list[SnapshotTrigger]:
        """Get list of snapshot triggers.

        Returns:
            List of SnapshotTrigger models.
        """
        config = await self.get_config()
        return config.triggers

    async def get_profile(self, profile_id: str) -> SnapshotProfile | None:
        """Get a specific snapshot profile by ID.

        Args:
            profile_id: Profile identifier.

        Returns:
            SnapshotProfile model or None if not found.
        """
        profiles = await self.get_profiles()
        for profile in profiles:
            if profile.id == profile_id:
                return profile
        return None

    async def capture(
        self,
        resolution: str | None = None,
        compression: int | None = None,
        camera: int = 1,
    ) -> bytes:
        """Capture a snapshot image.

        Args:
            resolution: Image resolution (e.g., "1920x1080").
            compression: JPEG compression level (0-100).
            camera: Camera/channel number.

        Returns:
            JPEG image data as bytes.
        """
        params: dict[str, Any] = {"camera": camera}
        if resolution:
            params["resolution"] = resolution
        if compression is not None:
            params["compression"] = compression

        return await self._get_raw(self.IMAGE_CGI, params)

    def _parse_config(self, data: dict[str, Any]) -> BestSnapshotConfig:
        """Parse snapshot configuration response.

        Args:
            data: Raw API response data.

        Returns:
            BestSnapshotConfig model instance.
        """
        # Parse profiles
        profiles = []
        profiles_data = data.get("profiles", {})
        for profile_id, profile_info in profiles_data.items():
            if isinstance(profile_info, dict):
                profiles.append(self._parse_profile(profile_id, profile_info))

        # Parse triggers
        triggers = []
        triggers_data = data.get("triggers", {})
        for trigger_id, trigger_info in triggers_data.items():
            if isinstance(trigger_info, dict):
                triggers.append(self._parse_trigger(trigger_id, trigger_info))

        return BestSnapshotConfig(
            enabled=data.get("enabled", True),
            profiles=profiles,
            triggers=triggers,
            default_resolution=data.get("defaultResolution", ""),
            default_compression=data.get("defaultCompression", 25),
            max_snapshots_per_event=data.get("maxSnapshotsPerEvent", 1),
        )

    def _parse_profile(
        self, profile_id: str, data: dict[str, Any]
    ) -> SnapshotProfile:
        """Parse snapshot profile data.

        Args:
            profile_id: Profile identifier.
            data: Profile configuration data.

        Returns:
            SnapshotProfile model.
        """
        return SnapshotProfile(
            id=profile_id,
            name=data.get("name", ""),
            enabled=data.get("enabled", True),
            resolution=data.get("resolution", ""),
            compression=data.get("compression", 25),
            rotation=data.get("rotation", 0),
            mirror=data.get("mirror", False),
            overlay_enabled=data.get("overlayEnabled", False),
            timestamp_enabled=data.get("timestampEnabled", True),
        )

    def _parse_trigger(
        self, trigger_id: str, data: dict[str, Any]
    ) -> SnapshotTrigger:
        """Parse snapshot trigger data.

        Args:
            trigger_id: Trigger identifier.
            data: Trigger configuration data.

        Returns:
            SnapshotTrigger model.
        """
        return SnapshotTrigger(
            id=trigger_id,
            name=data.get("name", ""),
            enabled=data.get("enabled", True),
            trigger_type=data.get("type", data.get("triggerType", "")),
            profile_id=data.get("profileId", ""),
            pre_trigger_time=data.get("preTriggerTime", 0),
            post_trigger_time=data.get("postTriggerTime", 0),
            event_filter=data.get("eventFilter", ""),
        )
