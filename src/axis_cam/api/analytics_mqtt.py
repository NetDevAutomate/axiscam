"""Analytics MQTT API module.

This module provides access to analytics MQTT publishing on AXIS devices
via the VAPIX analytics-mqtt API.

API Endpoints:
    - /config/rest/analytics-mqtt/v1beta (REST API)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import (
    AnalyticsMqttConfig,
    AnalyticsMqttSubscription,
    AnalyticsMqttBroker,
)


class AnalyticsMqttAPI(BaseAPI):
    """API module for analytics MQTT publishing configuration.

    This module provides methods to configure analytics data publishing via MQTT:
    - MQTT broker configuration
    - Analytics metadata subscriptions
    - Topic and QoS settings
    - Object tracking data publishing

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.analytics_mqtt.get_config()
        ...     for sub in config.subscriptions:
        ...         print(f"Subscription: {sub.name} -> {sub.topic}")
    """

    REST_PATH = "/config/rest/analytics-mqtt/v1beta"

    async def get_config(self) -> AnalyticsMqttConfig:
        """Get complete analytics MQTT configuration.

        Returns:
            AnalyticsMqttConfig model with all settings.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return AnalyticsMqttConfig()

    async def get_subscriptions(self) -> list[AnalyticsMqttSubscription]:
        """Get list of analytics MQTT subscriptions.

        Returns:
            List of AnalyticsMqttSubscription models.
        """
        config = await self.get_config()
        return config.subscriptions

    async def get_broker(self) -> AnalyticsMqttBroker | None:
        """Get MQTT broker configuration.

        Returns:
            AnalyticsMqttBroker model or None if not configured.
        """
        config = await self.get_config()
        return config.broker

    async def get_subscription(
        self, subscription_id: str
    ) -> AnalyticsMqttSubscription | None:
        """Get a specific subscription by ID.

        Args:
            subscription_id: Subscription identifier.

        Returns:
            AnalyticsMqttSubscription model or None if not found.
        """
        subscriptions = await self.get_subscriptions()
        for sub in subscriptions:
            if sub.id == subscription_id:
                return sub
        return None

    def _parse_config(self, data: dict[str, Any]) -> AnalyticsMqttConfig:
        """Parse analytics MQTT configuration response.

        Args:
            data: Raw API response data.

        Returns:
            AnalyticsMqttConfig model instance.
        """
        # Parse subscriptions
        subscriptions = []
        subs_data = data.get("subscriptions", {})
        for sub_id, sub_info in subs_data.items():
            if isinstance(sub_info, dict):
                subscriptions.append(self._parse_subscription(sub_id, sub_info))

        # Parse broker
        broker = None
        broker_data = data.get("broker", {})
        if broker_data:
            broker = self._parse_broker(broker_data)

        return AnalyticsMqttConfig(
            enabled=data.get("enabled", False),
            connected=data.get("connected", False),
            broker=broker,
            subscriptions=subscriptions,
            include_timestamps=data.get("includeTimestamps", True),
            include_coordinates=data.get("includeCoordinates", True),
        )

    def _parse_subscription(
        self, sub_id: str, data: dict[str, Any]
    ) -> AnalyticsMqttSubscription:
        """Parse analytics MQTT subscription data.

        Args:
            sub_id: Subscription identifier.
            data: Subscription configuration data.

        Returns:
            AnalyticsMqttSubscription model.
        """
        return AnalyticsMqttSubscription(
            id=sub_id,
            name=data.get("name", ""),
            enabled=data.get("enabled", True),
            topic=data.get("topic", ""),
            qos=data.get("qos", 0),
            retain=data.get("retain", False),
            analytics_types=data.get("analyticsTypes", []),
            object_classes=data.get("objectClasses", []),
            include_image=data.get("includeImage", False),
            image_resolution=data.get("imageResolution", ""),
        )

    def _parse_broker(self, data: dict[str, Any]) -> AnalyticsMqttBroker:
        """Parse MQTT broker configuration.

        Args:
            data: Broker configuration data.

        Returns:
            AnalyticsMqttBroker model.
        """
        return AnalyticsMqttBroker(
            host=data.get("host", ""),
            port=data.get("port", 1883),
            protocol=data.get("protocol", "tcp"),
            username=data.get("username", ""),
            client_id=data.get("clientId", ""),
            use_tls=data.get("useTls", False),
            ca_certificate=data.get("caCertificate", ""),
            validate_server_cert=data.get("validateServerCert", True),
        )
