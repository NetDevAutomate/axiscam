"""Stream Diagnostics API module.

This module provides access to stream configuration via the VAPIX parameter API.
It is a facade over the ParamAPI, providing convenient access to RTSP, RTP,
and stream profile settings.

Stream diagnostics are useful for troubleshooting connectivity issues,
especially when pairing with third-party devices (e.g., UniFi AI Port).

API Endpoints (via ParamAPI):
    - /config/rest/param/v2beta (REST API)
    - /axis-cgi/param.cgi (Legacy CGI)

Note: Stream parameters vary significantly by device model and firmware.
This module handles missing parameters gracefully by returning None values.
"""

from typing import Any

from pydantic import BaseModel, Field

from axis_cam.api.base import BaseAPI


# =============================================================================
# Stream Diagnostics Models
# =============================================================================


class RTSPConfig(BaseModel):
    """RTSP server configuration.

    Attributes:
        enabled: Whether RTSP server is enabled.
        port: RTSP port number (default 554).
        authentication: Authentication type (none, basic, digest).
        timeout: Session timeout in seconds.
        allow_path_arguments: Whether path arguments are allowed.
    """

    enabled: bool = True
    port: int = 554
    authentication: str = "digest"
    timeout: int = 60
    allow_path_arguments: bool = True


class RTPConfig(BaseModel):
    """RTP configuration.

    Attributes:
        start_port: Start of RTP port range.
        end_port: End of RTP port range.
        multicast_enabled: Whether multicast is enabled.
        multicast_address: Multicast address if enabled.
    """

    start_port: int = 50000
    end_port: int = 50999
    multicast_enabled: bool = False
    multicast_address: str = ""


class StreamProfile(BaseModel):
    """Stream profile configuration.

    Attributes:
        name: Profile name (e.g., "Quality", "Balanced", "Bandwidth").
        description: Profile description.
        video_codec: Video codec (H.264, H.265, MJPEG).
        resolution: Resolution string (e.g., "1920x1080").
        fps: Frame rate.
        bitrate: Bitrate in kbps (0 = variable).
        gop_length: GOP length (keyframe interval).
        compression: Compression level (1-100).
        parameters: Additional codec parameters.
    """

    name: str = ""
    description: str = ""
    video_codec: str = "H.264"
    resolution: str = ""
    fps: int = 30
    bitrate: int = 0
    gop_length: int = 32
    compression: int = 30
    parameters: dict[str, Any] = Field(default_factory=dict)


class NetworkDiagnostics(BaseModel):
    """Network configuration diagnostics.

    Attributes:
        hostname: Device hostname.
        dhcp_enabled: Whether DHCP is enabled.
        ip_address: Current IP address.
        subnet_mask: Subnet mask.
        gateway: Default gateway.
        dns_servers: List of DNS servers.
        mtu: MTU size.
        ipv6_enabled: Whether IPv6 is enabled.
    """

    hostname: str = ""
    dhcp_enabled: bool = True
    ip_address: str = ""
    subnet_mask: str = ""
    gateway: str = ""
    dns_servers: list[str] = Field(default_factory=list)
    mtu: int = 1500
    ipv6_enabled: bool = False


class StreamDiagnostics(BaseModel):
    """Complete stream diagnostics report.

    Attributes:
        device_name: Device name or IP address.
        rtsp: RTSP configuration.
        rtp: RTP configuration.
        profiles: List of stream profiles.
        network: Network configuration.
        errors: List of errors encountered during diagnostics retrieval.
    """

    device_name: str = ""
    rtsp: RTSPConfig = Field(default_factory=RTSPConfig)
    rtp: RTPConfig = Field(default_factory=RTPConfig)
    profiles: list[StreamProfile] = Field(default_factory=list)
    network: NetworkDiagnostics = Field(default_factory=NetworkDiagnostics)
    errors: list[str] = Field(default_factory=list)


# =============================================================================
# Stream API Implementation
# =============================================================================


class StreamAPI(BaseAPI):
    """API module for stream diagnostics.

    This is a facade over the Parameter API, providing convenient access
    to streaming-related settings. Stream parameters are typically found in:
    - root.Network.RTSP.*
    - root.Network.RTP.*
    - root.StreamProfile.*
    - root.Image.*

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     diagnostics = await camera.stream.get_diagnostics()
        ...     print(f"RTSP Port: {diagnostics.rtsp.port}")
        ...     for profile in diagnostics.profiles:
        ...         print(f"Profile {profile.name}: {profile.resolution}")
    """

    # REST API endpoint for param v2beta
    REST_PATH = "/config/rest/param/v2beta"

    async def _get_param_json(self, path: str = "") -> dict[str, Any]:
        """Get JSON data from param API.

        Args:
            path: Parameter path (e.g., "Network/RTSP").

        Returns:
            JSON response data.
        """
        url = f"{self.REST_PATH}/{path}" if path else self.REST_PATH

        try:
            response = await self._get(url, params={})
            # Response format: {"status": "success", "data": {...}}
            if isinstance(response, dict):
                if response.get("status") == "success":
                    return response.get("data", {})
                return response
            return {}
        except Exception:
            return {}

    async def get_rtsp_config(self) -> RTSPConfig:
        """Get RTSP server configuration.

        Returns:
            RTSPConfig with current RTSP settings.
        """
        data = await self._get_param_json("Network/RTSP")

        return RTSPConfig(
            enabled=data.get("Enabled", True),
            port=int(data.get("Port", 554)),
            authentication=data.get("Authentication", "digest"),
            timeout=int(data.get("Timeout", 60)),
            allow_path_arguments=data.get("AllowPathArguments", True),
        )

    async def get_rtp_config(self) -> RTPConfig:
        """Get RTP configuration.

        Returns:
            RTPConfig with current RTP port settings.
        """
        data = await self._get_param_json("Network/RTP")

        multicast = data.get("Multicast", {})
        if isinstance(multicast, dict):
            multicast_enabled = multicast.get("Enabled", False)
            multicast_address = multicast.get("Address", "")
        else:
            multicast_enabled = False
            multicast_address = ""

        return RTPConfig(
            start_port=int(data.get("StartPort", 50000)),
            end_port=int(data.get("EndPort", 50999)),
            multicast_enabled=bool(multicast_enabled),
            multicast_address=str(multicast_address),
        )

    async def get_stream_profiles(self) -> list[StreamProfile]:
        """Get all stream profiles.

        Returns:
            List of StreamProfile objects.
        """
        data = await self._get_param_json("StreamProfile")

        profiles: list[StreamProfile] = []
        for name, profile_data in data.items():
            if isinstance(profile_data, dict):
                profiles.append(
                    StreamProfile(
                        name=name,
                        description=profile_data.get("Description", ""),
                        video_codec=profile_data.get("VideoCodec", "H.264"),
                        resolution=profile_data.get("Resolution", ""),
                        fps=int(profile_data.get("Fps", 30)),
                        bitrate=int(profile_data.get("Bitrate", 0)),
                        gop_length=int(profile_data.get("GOPLength", 32)),
                        compression=int(profile_data.get("Compression", 30)),
                        parameters=profile_data.get("Parameters", {}),
                    )
                )

        return profiles

    async def get_network_config(self) -> NetworkDiagnostics:
        """Get network configuration for diagnostics.

        Returns:
            NetworkDiagnostics with current network settings.
        """
        data = await self._get_param_json("Network")

        # Handle nested structure from param/v2beta
        bonjour = data.get("Bonjour", {})
        interface = data.get("Interface", {}).get("I0", {})
        ipv6 = data.get("IPv6", {})

        return NetworkDiagnostics(
            hostname=bonjour.get("FriendlyName", ""),
            dhcp_enabled=interface.get("DHCPEnabled", True),
            ip_address=interface.get("IPAddress", ""),
            subnet_mask=interface.get("SubnetMask", ""),
            gateway=interface.get("Gateway", ""),
            dns_servers=data.get("DNSServers", []),
            mtu=int(interface.get("MTU", 1500)),
            ipv6_enabled=ipv6.get("Enabled", False),
        )

    async def get_image_config(self) -> dict[str, Any]:
        """Get image/video source configuration.

        Returns:
            Raw image configuration data.
        """
        return await self._get_param_json("Image")

    async def get_stream_cache(self) -> dict[str, Any]:
        """Get stream cache configuration.

        Returns:
            Raw stream cache configuration data.
        """
        return await self._get_param_json("StreamCache")

    async def get_qos_config(self) -> dict[str, Any]:
        """Get QoS (Quality of Service) configuration.

        Returns:
            Raw QoS configuration data.
        """
        try:
            return await self._get_param_json("Network/QoS")
        except Exception:
            return {}

    async def get_diagnostics(self, device_name: str = "") -> StreamDiagnostics:
        """Get complete stream diagnostics.

        Collects RTSP, RTP, stream profiles, and network configuration
        in a single call. Handles errors gracefully for each component.

        Args:
            device_name: Optional device name for the report.

        Returns:
            StreamDiagnostics with all configuration data.

        Example:
            >>> diagnostics = await camera.stream.get_diagnostics("Front Door")
            >>> if diagnostics.errors:
            ...     print(f"Warnings: {diagnostics.errors}")
            >>> print(f"RTSP enabled: {diagnostics.rtsp.enabled}")
        """
        diagnostics = StreamDiagnostics(device_name=device_name)

        # Collect RTSP config
        try:
            diagnostics.rtsp = await self.get_rtsp_config()
        except Exception as e:
            diagnostics.errors.append(f"RTSP config: {e}")

        # Collect RTP config
        try:
            diagnostics.rtp = await self.get_rtp_config()
        except Exception as e:
            diagnostics.errors.append(f"RTP config: {e}")

        # Collect stream profiles
        try:
            diagnostics.profiles = await self.get_stream_profiles()
        except Exception as e:
            diagnostics.errors.append(f"Stream profiles: {e}")

        # Collect network config
        try:
            diagnostics.network = await self.get_network_config()
        except Exception as e:
            diagnostics.errors.append(f"Network config: {e}")

        return diagnostics
