"""Base device class for AXIS devices.

This module provides the abstract base class for all AXIS device types.
Device classes compose API modules to provide a unified interface for
interacting with specific device types.
"""

from abc import ABC, abstractmethod
from typing import Any

from axis_cam.api.device_info import BasicDeviceInfoAPI
from axis_cam.api.lldp import LldpAPI
from axis_cam.api.logs import LogsAPI
from axis_cam.api.param import ParamAPI
from axis_cam.api.time import TimeAPI
from axis_cam.client import VapixClient
from axis_cam.models import (
    BasicDeviceInfo,
    DeviceCapabilities,
    DeviceStatus,
    DeviceType,
    LldpInfo,
    LogReport,
    LogType,
    TimeInfo,
)


class AxisDevice(ABC):
    """Abstract base class for AXIS devices.

    This class provides common functionality shared by all AXIS device types.
    Specific device types (Camera, Recorder, Intercom) inherit from this
    class and may add device-specific API modules.

    The class uses composition to include API modules for various VAPIX
    endpoints, making it easy to extend functionality.

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     info = await camera.get_info()
        ...     print(f"Model: {info.product_number}")
        ...     logs = await camera.logs.get_system_logs(max_entries=10)

    Attributes:
        host: Device IP address or hostname.
        device_info: API module for basic device information.
        params: API module for device parameters.
        time: API module for time settings.
        logs: API module for log retrieval.
        lldp: API module for LLDP neighbor discovery.
    """

    # Device type identifier - must be set by subclasses
    device_type: DeviceType = DeviceType.UNKNOWN

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 443,
        ssl_verify: bool = False,
        timeout: float = 30.0,
        use_digest_auth: bool = False,
    ) -> None:
        """Initialize the AXIS device.

        Args:
            host: Device IP address or hostname.
            username: Authentication username.
            password: Authentication password.
            port: HTTPS port number.
            ssl_verify: Whether to verify SSL certificates.
            timeout: Request timeout in seconds.
            use_digest_auth: Use Digest auth instead of Basic.
        """
        self._host = host
        self._client = VapixClient(
            host=host,
            username=username,
            password=password,
            port=port,
            use_https=True,  # AXIS devices typically use HTTPS
            verify_ssl=ssl_verify,
            timeout=timeout,
            use_digest_auth=use_digest_auth,
        )

        # Initialize common API modules
        self.device_info = BasicDeviceInfoAPI(self._client)
        self.params = ParamAPI(self._client)
        self.time = TimeAPI(self._client)
        self.logs = LogsAPI(self._client, device_name=host)
        self.lldp = LldpAPI(self._client)

        # Track discovered capabilities
        self._capabilities: DeviceCapabilities | None = None
        self._device_info_cache: BasicDeviceInfo | None = None

    @property
    def host(self) -> str:
        """Get the device host address."""
        return self._host

    @property
    def client(self) -> VapixClient:
        """Get the underlying VAPIX client."""
        return self._client

    async def __aenter__(self) -> "AxisDevice":
        """Async context manager entry."""
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Async context manager exit."""
        await self._client.__aexit__(exc_type, exc_val, exc_tb)

    async def connect(self) -> None:
        """Establish connection to the device.

        This method initializes the HTTP client and verifies connectivity.
        """
        await self._client.connect()

    async def disconnect(self) -> None:
        """Close the connection to the device."""
        await self._client.disconnect()

    async def get_info(self) -> BasicDeviceInfo:
        """Get basic device information.

        Returns:
            BasicDeviceInfo model with device details.
        """
        if self._device_info_cache is None:
            self._device_info_cache = await self.device_info.get_info()
        return self._device_info_cache

    async def get_status(self) -> DeviceStatus:
        """Get current device status.

        Returns:
            DeviceStatus model with connectivity and health info.
        """
        info = await self.get_info()
        time_info = await self.time.get_info()

        return DeviceStatus(
            host=self._host,
            reachable=True,
            device_type=self.device_type,
            model=info.product_number,
            serial_number=info.serial_number,
            firmware_version=info.firmware_version,
            uptime_seconds=None,  # Not available in basic info
            current_time=time_info.utc_time,
        )

    async def get_capabilities(self) -> DeviceCapabilities:
        """Discover device capabilities via API discovery.

        Returns:
            DeviceCapabilities model with available APIs.
        """
        if self._capabilities is None:
            apis = await self._client.discover_apis()
            self._capabilities = DeviceCapabilities(
                supported_apis=list(apis.keys()),
                has_ptz="ptz" in apis or "ptz-control" in apis,
                has_audio="audio-device-ctrl" in apis,
                has_io_ports="io-port-management" in apis,
                has_analytics="analytics-metadata" in apis,
            )
        return self._capabilities

    async def check_connectivity(self) -> bool:
        """Check if the device is reachable.

        Returns:
            True if device responds, False otherwise.
        """
        return await self._client.check_connectivity()

    async def get_time_info(self) -> TimeInfo:
        """Get device time information.

        Returns:
            TimeInfo model with time settings.
        """
        return await self.time.get_info()

    async def get_logs(
        self,
        log_type: LogType = LogType.SYSTEM,
        max_entries: int | None = None,
    ) -> LogReport:
        """Get device logs.

        Args:
            log_type: Type of logs to retrieve.
            max_entries: Maximum number of entries.

        Returns:
            LogReport with parsed log entries.
        """
        return await self.logs.get_logs(log_type, max_entries)

    async def get_friendly_name(self) -> str:
        """Get the device's user-assigned name.

        Returns:
            Friendly name or empty string.
        """
        return await self.params.get_friendly_name()

    async def get_location(self) -> str:
        """Get the device's location description.

        Returns:
            Location string or empty string.
        """
        return await self.params.get_location()

    async def get_lldp_info(self) -> LldpInfo:
        """Get LLDP neighbor information.

        Returns:
            LldpInfo with LLDP status and discovered neighbors.
        """
        return await self.lldp.get_info()

    @abstractmethod
    async def get_device_specific_info(self) -> dict[str, Any]:
        """Get device-type specific information.

        This method should be implemented by subclasses to return
        information specific to that device type.

        Returns:
            Dictionary with device-specific data.
        """
        pass

    def __repr__(self) -> str:
        """Return string representation."""
        return f"{self.__class__.__name__}(host={self._host!r})"
