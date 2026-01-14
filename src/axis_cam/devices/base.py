"""Base device class for AXIS devices.

This module provides the abstract base class for all AXIS device types.
Device classes compose API modules to provide a unified interface for
interacting with specific device types.
"""

from abc import ABC, abstractmethod
from typing import Any

from axis_cam.api.action import ActionAPI
from axis_cam.api.analytics import VideoAnalyticsAPI
from axis_cam.api.analytics_mqtt import AnalyticsMqttAPI
from axis_cam.api.audio_multicast import AudioMulticastAPI
from axis_cam.api.cert import CertAPI
from axis_cam.api.crypto_policy import CryptoPolicyAPI
from axis_cam.api.device_info import BasicDeviceInfoAPI
from axis_cam.api.firewall import FirewallAPI
from axis_cam.api.geolocation import GeolocationAPI
from axis_cam.api.lldp import LldpAPI
from axis_cam.api.logs import LogsAPI
from axis_cam.api.mqtt import MqttBridgeAPI
from axis_cam.api.network import NetworkSettingsAPI
from axis_cam.api.networkpairing import NetworkPairingAPI
from axis_cam.api.ntp import NtpAPI
from axis_cam.api.oauth import OAuthAPI
from axis_cam.api.oidc import OidcAPI
from axis_cam.api.param import ParamAPI
from axis_cam.api.recording import RecordingAPI
from axis_cam.api.serverreport import ServerReportAPI
from axis_cam.api.snapshot import BestSnapshotAPI
from axis_cam.api.snmp import SnmpAPI
from axis_cam.api.ssh import SshAPI
from axis_cam.api.storage import RemoteStorageAPI
from axis_cam.api.stream import StreamAPI, StreamDiagnostics
from axis_cam.api.time import TimeAPI
from axis_cam.api.virtualhost import VirtualHostAPI
from axis_cam.client import VapixClient
from axis_cam.models import (
    ActionConfig,
    AnalyticsConfig,
    AnalyticsMqttConfig,
    AudioMulticastConfig,
    BasicDeviceInfo,
    BestSnapshotConfig,
    CertConfig,
    CryptoPolicyConfig,
    DeviceCapabilities,
    DeviceStatus,
    DeviceType,
    FirewallConfig,
    GeolocationConfig,
    LldpInfo,
    LogReport,
    LogType,
    MqttBridgeConfig,
    NetworkConfig,
    NetworkPairingConfig,
    NtpConfig,
    OAuthConfig,
    OidcConfig,
    RecordingConfig,
    RemoteStorageConfig,
    ServerReport,
    ServerReportFormat,
    SnmpConfig,
    SshConfig,
    TimeInfo,
    VirtualHostConfig,
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
        network: API module for network settings.
        firewall: API module for firewall configuration.
        ssh: API module for SSH configuration.
        snmp: API module for SNMP configuration.
        cert: API module for certificate management.
        ntp: API module for NTP configuration.
        action: API module for action rules configuration.
        mqtt: API module for MQTT event bridge configuration.
        recording: API module for recording group configuration.
        storage: API module for remote object storage configuration.
        geolocation: API module for device geolocation configuration.
        analytics: API module for video analytics configuration.
        snapshot: API module for best snapshot configuration.
        analytics_mqtt: API module for analytics MQTT publishing.
        audio_multicast: API module for audio multicast control.
        serverreport: API module for server report and debug archive downloads.
        oidc: API module for OpenID Connect configuration.
        oauth: API module for OAuth 2.0 Client Credentials Grant.
        virtualhost: API module for virtual host configuration.
        crypto_policy: API module for cryptographic policy settings.
        networkpairing: API module for network pairing.
        stream: API module for stream diagnostics (RTSP, RTP, profiles).
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
        # Auto-detect HTTPS based on port (443 = HTTPS, otherwise HTTP)
        use_https = port == 443
        self._client = VapixClient(
            host=host,
            username=username,
            password=password,
            port=port,
            use_https=use_https,
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

        # Initialize high-priority API modules
        self.network = NetworkSettingsAPI(self._client)
        self.firewall = FirewallAPI(self._client)
        self.ssh = SshAPI(self._client)
        self.snmp = SnmpAPI(self._client)
        self.cert = CertAPI(self._client)
        self.ntp = NtpAPI(self._client)

        # Initialize medium-priority API modules
        self.action = ActionAPI(self._client)
        self.mqtt = MqttBridgeAPI(self._client)
        self.recording = RecordingAPI(self._client)
        self.storage = RemoteStorageAPI(self._client)
        self.geolocation = GeolocationAPI(self._client)

        # Initialize device-specific API modules
        self.analytics = VideoAnalyticsAPI(self._client)
        self.snapshot = BestSnapshotAPI(self._client)
        self.analytics_mqtt = AnalyticsMqttAPI(self._client)
        self.audio_multicast = AudioMulticastAPI(self._client)
        self.serverreport = ServerReportAPI(self._client)

        # Initialize lower-priority API modules
        self.oidc = OidcAPI(self._client)
        self.oauth = OAuthAPI(self._client)
        self.virtualhost = VirtualHostAPI(self._client)
        self.crypto_policy = CryptoPolicyAPI(self._client)
        self.networkpairing = NetworkPairingAPI(self._client)

        # Initialize stream diagnostics API
        self.stream = StreamAPI(self._client)

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

    async def get_network_config(self) -> NetworkConfig:
        """Get extended network configuration.

        Returns:
            NetworkConfig model with network settings.
        """
        return await self.network.get_config()

    async def get_firewall_config(self) -> FirewallConfig:
        """Get firewall configuration.

        Returns:
            FirewallConfig model with firewall rules and settings.
        """
        return await self.firewall.get_config()

    async def get_ssh_config(self) -> SshConfig:
        """Get SSH configuration.

        Returns:
            SshConfig model with SSH settings.
        """
        return await self.ssh.get_config()

    async def get_snmp_config(self) -> SnmpConfig:
        """Get SNMP configuration.

        Returns:
            SnmpConfig model with SNMP settings.
        """
        return await self.snmp.get_config()

    async def get_cert_config(self) -> CertConfig:
        """Get certificate configuration.

        Returns:
            CertConfig model with certificate information.
        """
        return await self.cert.get_config()

    async def get_ntp_config(self) -> NtpConfig:
        """Get NTP configuration.

        Returns:
            NtpConfig model with NTP settings.
        """
        return await self.ntp.get_config()

    async def get_action_config(self) -> ActionConfig:
        """Get action rules configuration.

        Returns:
            ActionConfig model with action rules and templates.
        """
        return await self.action.get_config()

    async def get_mqtt_config(self) -> MqttBridgeConfig:
        """Get MQTT event bridge configuration.

        Returns:
            MqttBridgeConfig model with MQTT settings.
        """
        return await self.mqtt.get_config()

    async def get_recording_config(self) -> RecordingConfig:
        """Get recording configuration.

        Returns:
            RecordingConfig model with recording groups and profiles.
        """
        return await self.recording.get_config()

    async def get_storage_config(self) -> RemoteStorageConfig:
        """Get remote storage configuration.

        Returns:
            RemoteStorageConfig model with storage destinations.
        """
        return await self.storage.get_config()

    async def get_geolocation_config(self) -> GeolocationConfig:
        """Get device geolocation configuration.

        Returns:
            GeolocationConfig model with GPS coordinates and settings.
        """
        return await self.geolocation.get_config()

    async def get_analytics_config(self) -> AnalyticsConfig:
        """Get video analytics configuration.

        Returns:
            AnalyticsConfig model with analytics profiles and scenarios.
        """
        return await self.analytics.get_config()

    async def get_snapshot_config(self) -> BestSnapshotConfig:
        """Get best snapshot configuration.

        Returns:
            BestSnapshotConfig model with snapshot profiles and triggers.
        """
        return await self.snapshot.get_config()

    async def get_analytics_mqtt_config(self) -> AnalyticsMqttConfig:
        """Get analytics MQTT configuration.

        Returns:
            AnalyticsMqttConfig model with analytics publishing settings.
        """
        return await self.analytics_mqtt.get_config()

    async def get_audio_multicast_config(self) -> AudioMulticastConfig:
        """Get audio multicast configuration.

        Returns:
            AudioMulticastConfig model with multicast groups and streams.
        """
        return await self.audio_multicast.get_config()

    async def capture_snapshot(
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
        return await self.snapshot.capture(
            resolution=resolution,
            compression=compression,
            camera=camera,
        )

    async def download_server_report(
        self,
        format: ServerReportFormat = ServerReportFormat.ZIP_WITH_IMAGE,
        timeout: float | None = None,
    ) -> ServerReport:
        """Download a server report from the device.

        Args:
            format: Report format (zip_with_image, zip, text).
            timeout: Optional custom timeout for download (default: 60s).

        Returns:
            ServerReport model with report content and metadata.
        """
        return await self.serverreport.download_report(format=format, timeout=timeout)

    async def download_debug_archive(
        self,
        timeout: float | None = None,
    ) -> ServerReport:
        """Download the debug archive (debug.tgz) from the device.

        This retrieves a comprehensive debug archive that includes
        system logs, configuration, and diagnostic information.

        Args:
            timeout: Optional custom timeout for download (default: 120s).

        Returns:
            ServerReport model with debug archive content.
        """
        return await self.serverreport.get_debug_archive(timeout=timeout)

    async def get_oidc_config(self) -> OidcConfig:
        """Get OpenID Connect configuration.

        Returns:
            OidcConfig model with OIDC settings.
        """
        return await self.oidc.get_config()

    async def get_oauth_config(self) -> OAuthConfig:
        """Get OAuth 2.0 Client Credentials Grant configuration.

        Returns:
            OAuthConfig model with OAuth settings.
        """
        return await self.oauth.get_config()

    async def get_virtualhost_config(self) -> VirtualHostConfig:
        """Get virtual host configuration.

        Returns:
            VirtualHostConfig model with virtual host settings.
        """
        return await self.virtualhost.get_config()

    async def get_crypto_policy_config(self) -> CryptoPolicyConfig:
        """Get cryptographic policy configuration.

        Returns:
            CryptoPolicyConfig model with crypto settings.
        """
        return await self.crypto_policy.get_config()

    async def get_networkpairing_config(self) -> NetworkPairingConfig:
        """Get network pairing configuration.

        Returns:
            NetworkPairingConfig model with pairing settings.
        """
        return await self.networkpairing.get_config()

    async def get_stream_diagnostics(self, device_name: str | None = None) -> StreamDiagnostics:
        """Get stream diagnostics including RTSP, RTP, and profile settings.

        This method retrieves comprehensive streaming configuration useful
        for troubleshooting connectivity issues with third-party systems.

        Args:
            device_name: Optional device name for the report.

        Returns:
            StreamDiagnostics model with RTSP, RTP, profiles, and network info.
        """
        name = device_name or self._host
        return await self.stream.get_diagnostics(name)

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
