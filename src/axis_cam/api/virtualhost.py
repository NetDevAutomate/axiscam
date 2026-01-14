"""Virtual Host API module.

This module provides access to virtual host configuration on AXIS devices
via the VAPIX virtualhost API.

API Endpoints:
    - /config/rest/virtualhost/v1 (REST API)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import VirtualHost, VirtualHostConfig


class VirtualHostAPI(BaseAPI):
    """API module for virtual host configuration.

    This module provides methods to retrieve and manage virtual host settings:
    - Virtual host definitions
    - SSL certificate assignments
    - HTTP to HTTPS redirection
    - Host header validation

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.virtualhost.get_config()
        ...     print(f"Virtual hosting enabled: {config.enabled}")
        ...     for host in config.hosts:
        ...         print(f"Host: {host.hostname}")
    """

    REST_PATH = "/config/rest/virtualhost/v1"

    async def get_config(self) -> VirtualHostConfig:
        """Get virtual host configuration.

        Returns:
            VirtualHostConfig model with virtual host settings.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return VirtualHostConfig()

    async def is_enabled(self) -> bool:
        """Check if virtual hosting is enabled.

        Returns:
            True if virtual hosting is active.
        """
        config = await self.get_config()
        return config.enabled

    async def get_hosts(self) -> list[VirtualHost]:
        """Get list of configured virtual hosts.

        Returns:
            List of VirtualHost models.
        """
        config = await self.get_config()
        return config.hosts

    async def get_default_host(self) -> VirtualHost | None:
        """Get the default virtual host.

        Returns:
            VirtualHost model or None if no default is set.
        """
        config = await self.get_config()
        for host in config.hosts:
            if host.default_host:
                return host
        return None

    async def get_host_by_name(self, hostname: str) -> VirtualHost | None:
        """Get a virtual host by hostname.

        Args:
            hostname: The hostname to search for.

        Returns:
            VirtualHost model or None if not found.
        """
        config = await self.get_config()
        for host in config.hosts:
            if host.hostname == hostname:
                return host
        return None

    def _parse_config(self, data: dict[str, Any]) -> VirtualHostConfig:
        """Parse virtual host configuration response.

        Args:
            data: Raw API response data.

        Returns:
            VirtualHostConfig model instance.
        """
        # Parse hosts
        hosts = []
        for host_data in data.get("hosts", []):
            if isinstance(host_data, dict):
                host = VirtualHost(
                    host_id=host_data.get("hostId", ""),
                    hostname=host_data.get("hostname", ""),
                    enabled=host_data.get("enabled", True),
                    certificate_id=host_data.get("certificateId", ""),
                    redirect_http_to_https=host_data.get(
                        "redirectHttpToHttps", True
                    ),
                    default_host=host_data.get("defaultHost", False),
                    allowed_methods=host_data.get(
                        "allowedMethods", ["GET", "POST", "PUT", "DELETE"]
                    ),
                )
                hosts.append(host)

        return VirtualHostConfig(
            enabled=data.get("enabled", False),
            hosts=hosts,
            default_certificate=data.get("defaultCertificate", ""),
            strict_host_checking=data.get("strictHostChecking", True),
        )
