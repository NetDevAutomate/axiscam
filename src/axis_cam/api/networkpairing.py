"""Network Pairing API module.

This module provides access to network pairing configuration on AXIS devices
via the VAPIX networkpairing API.

API Endpoints:
    - /config/rest/networkpairing/v1 (REST API)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import (
    NetworkPairingConfig,
    PairedDevice,
    PairingMode,
    PairingRequest,
)


class NetworkPairingAPI(BaseAPI):
    """API module for network pairing configuration.

    This module provides methods to retrieve and manage device pairing:
    - Pairing mode configuration
    - Paired device management
    - Pairing request handling
    - Device discovery

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.networkpairing.get_config()
        ...     print(f"Pairing mode: {config.mode}")
        ...     for device in config.paired_devices:
        ...         print(f"Paired: {device.name} ({device.address})")
    """

    REST_PATH = "/config/rest/networkpairing/v1"

    async def get_config(self) -> NetworkPairingConfig:
        """Get network pairing configuration.

        Returns:
            NetworkPairingConfig model with pairing settings.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return NetworkPairingConfig()

    async def is_enabled(self) -> bool:
        """Check if network pairing is enabled.

        Returns:
            True if network pairing is active.
        """
        config = await self.get_config()
        return config.enabled

    async def get_mode(self) -> PairingMode:
        """Get the current pairing mode.

        Returns:
            PairingMode enum value.
        """
        config = await self.get_config()
        return config.mode

    async def get_paired_devices(self) -> list[PairedDevice]:
        """Get list of paired devices.

        Returns:
            List of PairedDevice models.
        """
        config = await self.get_config()
        return config.paired_devices

    async def get_online_devices(self) -> list[PairedDevice]:
        """Get only currently online paired devices.

        Returns:
            List of online PairedDevice models.
        """
        config = await self.get_config()
        return [d for d in config.paired_devices if d.online]

    async def get_pending_requests(self) -> list[PairingRequest]:
        """Get pending pairing requests.

        Returns:
            List of PairingRequest models.
        """
        config = await self.get_config()
        return config.pending_requests

    async def discovery_enabled(self) -> bool:
        """Check if device discovery is enabled.

        Returns:
            True if discovery is active.
        """
        config = await self.get_config()
        return config.discovery_enabled

    async def get_pairing_token(self) -> str:
        """Get the current pairing token.

        Returns:
            Pairing token string or empty if not in pairing mode.
        """
        config = await self.get_config()
        return config.pairing_token

    def _parse_config(self, data: dict[str, Any]) -> NetworkPairingConfig:
        """Parse network pairing configuration response.

        Args:
            data: Raw API response data.

        Returns:
            NetworkPairingConfig model instance.
        """
        # Parse pairing mode
        mode_str = data.get("mode", "disabled")
        try:
            mode = PairingMode(mode_str)
        except ValueError:
            mode = PairingMode.DISABLED

        # Parse paired devices
        paired_devices = []
        for device_data in data.get("pairedDevices", []):
            if isinstance(device_data, dict):
                device = PairedDevice(
                    device_id=device_data.get("deviceId", ""),
                    name=device_data.get("name", ""),
                    address=device_data.get("address", ""),
                    device_type=device_data.get("deviceType", ""),
                    paired_at=device_data.get("pairedAt", ""),
                    last_seen=device_data.get("lastSeen", ""),
                    online=device_data.get("online", False),
                    trust_level=device_data.get("trustLevel", "full"),
                )
                paired_devices.append(device)

        # Parse pending requests
        pending_requests = []
        for request_data in data.get("pendingRequests", []):
            if isinstance(request_data, dict):
                request = PairingRequest(
                    request_id=request_data.get("requestId", ""),
                    device_name=request_data.get("deviceName", ""),
                    device_address=request_data.get("deviceAddress", ""),
                    device_type=request_data.get("deviceType", ""),
                    requested_at=request_data.get("requestedAt", ""),
                    expires_at=request_data.get("expiresAt", ""),
                )
                pending_requests.append(request)

        return NetworkPairingConfig(
            enabled=data.get("enabled", False),
            mode=mode,
            discovery_enabled=data.get("discoveryEnabled", False),
            pairing_token=data.get("pairingToken", ""),
            token_expiry=data.get("tokenExpiry", ""),
            paired_devices=paired_devices,
            pending_requests=pending_requests,
            max_paired_devices=data.get("maxPairedDevices", 10),
            auto_approve_same_network=data.get("autoApproveSameNetwork", False),
        )
