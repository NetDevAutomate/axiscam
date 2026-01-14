"""Video Analytics API module.

This module provides access to video analytics configuration on AXIS devices
via the VAPIX video-analytics API.

API Endpoints:
    - /config/rest/video-analytics/v1beta (REST API)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import (
    AnalyticsConfig,
    AnalyticsProfile,
    AnalyticsScenario,
    ObjectClass,
)


class VideoAnalyticsAPI(BaseAPI):
    """API module for video analytics configuration.

    This module provides methods to retrieve and manage video analytics:
    - Analytics profiles and scenarios
    - Object detection classes
    - Motion detection configuration
    - Analytics metadata settings

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.analytics.get_config()
        ...     for profile in config.profiles:
        ...         print(f"Profile: {profile.name} - Enabled: {profile.enabled}")
    """

    REST_PATH = "/config/rest/video-analytics/v1beta"

    async def get_config(self) -> AnalyticsConfig:
        """Get complete video analytics configuration.

        Returns:
            AnalyticsConfig model with all analytics settings.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return AnalyticsConfig()

    async def get_profiles(self) -> list[AnalyticsProfile]:
        """Get list of analytics profiles.

        Returns:
            List of AnalyticsProfile models.
        """
        config = await self.get_config()
        return config.profiles

    async def get_scenarios(self) -> list[AnalyticsScenario]:
        """Get list of analytics scenarios.

        Returns:
            List of AnalyticsScenario models.
        """
        config = await self.get_config()
        return config.scenarios

    async def get_object_classes(self) -> list[ObjectClass]:
        """Get available object detection classes.

        Returns:
            List of ObjectClass models.
        """
        config = await self.get_config()
        return config.object_classes

    async def get_profile(self, profile_id: str) -> AnalyticsProfile | None:
        """Get a specific analytics profile by ID.

        Args:
            profile_id: Profile identifier.

        Returns:
            AnalyticsProfile model or None if not found.
        """
        profiles = await self.get_profiles()
        for profile in profiles:
            if profile.id == profile_id:
                return profile
        return None

    def _parse_config(self, data: dict[str, Any]) -> AnalyticsConfig:
        """Parse analytics configuration response.

        Args:
            data: Raw API response data.

        Returns:
            AnalyticsConfig model instance.
        """
        # Parse profiles
        profiles = []
        profiles_data = data.get("profiles", {})
        for profile_id, profile_info in profiles_data.items():
            if isinstance(profile_info, dict):
                profiles.append(self._parse_profile(profile_id, profile_info))

        # Parse scenarios
        scenarios = []
        scenarios_data = data.get("scenarios", {})
        for scenario_id, scenario_info in scenarios_data.items():
            if isinstance(scenario_info, dict):
                scenarios.append(self._parse_scenario(scenario_id, scenario_info))

        # Parse object classes
        object_classes = []
        classes_data = data.get("objectClasses", data.get("object_classes", {}))
        for class_id, class_info in classes_data.items():
            if isinstance(class_info, dict):
                object_classes.append(self._parse_object_class(class_id, class_info))

        # Parse global settings
        return AnalyticsConfig(
            enabled=data.get("enabled", False),
            profiles=profiles,
            scenarios=scenarios,
            object_classes=object_classes,
            metadata_enabled=data.get("metadataEnabled", False),
            overlay_enabled=data.get("overlayEnabled", False),
        )

    def _parse_profile(self, profile_id: str, data: dict[str, Any]) -> AnalyticsProfile:
        """Parse analytics profile data.

        Args:
            profile_id: Profile identifier.
            data: Profile configuration data.

        Returns:
            AnalyticsProfile model.
        """
        return AnalyticsProfile(
            id=profile_id,
            name=data.get("name", ""),
            enabled=data.get("enabled", False),
            camera_id=data.get("cameraId", data.get("camera", "")),
            scenarios=data.get("scenarios", []),
            sensitivity=data.get("sensitivity", 50),
            min_object_size=data.get("minObjectSize", 0),
            max_object_size=data.get("maxObjectSize", 100),
        )

    def _parse_scenario(self, scenario_id: str, data: dict[str, Any]) -> AnalyticsScenario:
        """Parse analytics scenario data.

        Args:
            scenario_id: Scenario identifier.
            data: Scenario configuration data.

        Returns:
            AnalyticsScenario model.
        """
        return AnalyticsScenario(
            id=scenario_id,
            name=data.get("name", ""),
            scenario_type=data.get("type", data.get("scenarioType", "")),
            enabled=data.get("enabled", False),
            object_classes=data.get("objectClasses", []),
            trigger_on_enter=data.get("triggerOnEnter", True),
            trigger_on_exit=data.get("triggerOnExit", False),
            trigger_on_presence=data.get("triggerOnPresence", False),
            dwell_time=data.get("dwellTime", 0),
            region=data.get("region", {}),
        )

    def _parse_object_class(self, class_id: str, data: dict[str, Any]) -> ObjectClass:
        """Parse object class data.

        Args:
            class_id: Class identifier.
            data: Class configuration data.

        Returns:
            ObjectClass model.
        """
        return ObjectClass(
            id=class_id,
            name=data.get("name", ""),
            enabled=data.get("enabled", True),
            confidence_threshold=data.get("confidenceThreshold", 50),
            color=data.get("color", ""),
        )
