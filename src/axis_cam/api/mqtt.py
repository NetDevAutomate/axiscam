"""Event MQTT Bridge API module.

This module provides access to MQTT event publishing configuration on AXIS devices
via the VAPIX event-mqtt-bridge API.

API Endpoints:
    - /config/rest/event-mqtt-bridge/v1beta (REST API)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import MqttBridgeConfig, MqttClient, MqttEventFilter


class MqttBridgeAPI(BaseAPI):
    """API module for MQTT event bridge configuration.

    This module provides methods to retrieve and manage MQTT publishing:
    - MQTT client configuration
    - Event filters and topics
    - Connection status

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.mqtt.get_config()
        ...     print(f"MQTT Enabled: {config.enabled}")
        ...     for client in config.clients:
        ...         print(f"  Broker: {client.host}:{client.port}")
    """

    REST_PATH = "/config/rest/event-mqtt-bridge/v1beta"

    async def get_config(self) -> MqttBridgeConfig:
        """Get complete MQTT bridge configuration.

        Returns:
            MqttBridgeConfig model with MQTT settings.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return MqttBridgeConfig()

    async def get_clients(self) -> list[MqttClient]:
        """Get list of MQTT clients.

        Returns:
            List of MqttClient models.
        """
        config = await self.get_config()
        return config.clients

    async def get_event_filters(self) -> list[MqttEventFilter]:
        """Get list of event filters.

        Returns:
            List of MqttEventFilter models.
        """
        config = await self.get_config()
        return config.event_filters

    async def is_connected(self) -> bool:
        """Check if MQTT bridge is connected.

        Returns:
            True if connected to broker.
        """
        config = await self.get_config()
        return config.connected

    def _parse_config(self, data: dict[str, Any]) -> MqttBridgeConfig:
        """Parse MQTT bridge configuration response.

        Args:
            data: Raw API response data.

        Returns:
            MqttBridgeConfig model instance.
        """
        # Parse clients
        clients = []
        clients_data = data.get("clients", {})
        for client_id, client_info in clients_data.items():
            if isinstance(client_info, dict):
                clients.append(self._parse_client(client_id, client_info))

        # Parse event filters
        event_filters = []
        filters_data = data.get("eventFilters", {})
        for filter_id, filter_info in filters_data.items():
            if isinstance(filter_info, dict):
                event_filters.append(self._parse_filter(filter_id, filter_info))

        return MqttBridgeConfig(
            enabled=data.get("enabled", False),
            connected=data.get("status", {}).get("connected", False),
            clients=clients,
            event_filters=event_filters,
        )

    def _parse_client(self, client_id: str, data: dict[str, Any]) -> MqttClient:
        """Parse MQTT client data.

        Args:
            client_id: Client identifier.
            data: Client configuration data.

        Returns:
            MqttClient model.
        """
        return MqttClient(
            id=client_id,
            host=data.get("host", ""),
            port=data.get("port", 1883),
            protocol=data.get("protocol", "tcp"),
            username=data.get("username", ""),
            client_id=data.get("clientId", ""),
            keep_alive=data.get("keepAlive", 60),
            clean_session=data.get("cleanSession", True),
            use_tls=data.get("useTls", False),
        )

    def _parse_filter(self, filter_id: str, data: dict[str, Any]) -> MqttEventFilter:
        """Parse MQTT event filter data.

        Args:
            filter_id: Filter identifier.
            data: Filter configuration data.

        Returns:
            MqttEventFilter model.
        """
        return MqttEventFilter(
            id=filter_id,
            name=data.get("name", ""),
            enabled=data.get("enabled", True),
            topic=data.get("topic", ""),
            event_types=data.get("eventTypes", []),
            qos=data.get("qos", 0),
            retain=data.get("retain", False),
        )
