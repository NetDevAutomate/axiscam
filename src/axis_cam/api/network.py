"""Network Settings API module.

This module provides access to network configuration on AXIS devices
via the VAPIX network-settings API.

API Endpoints:
    - /config/rest/network-settings/v2beta (REST API)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import (
    DnsSettings,
    NetworkConfig,
    NetworkInterface,
    ProxySettings,
)


class NetworkSettingsAPI(BaseAPI):
    """API module for network configuration.

    This module provides methods to retrieve and manage network settings:
    - Interface configuration (IP, DHCP, etc.)
    - DNS settings
    - Proxy configuration
    - Hostname and domain settings

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.network.get_config()
        ...     print(f"Hostname: {config.hostname}")
        ...     for iface in config.interfaces:
        ...         print(f"  {iface.name}: {iface.ip_address}")
    """

    REST_PATH = "/config/rest/network-settings/v2beta"

    async def get_config(self) -> NetworkConfig:
        """Get complete network configuration.

        Returns:
            NetworkConfig model with all network settings.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return NetworkConfig()

    async def get_interfaces(self) -> list[NetworkInterface]:
        """Get list of network interfaces.

        Returns:
            List of NetworkInterface models.
        """
        config = await self.get_config()
        return config.interfaces

    async def get_dns(self) -> DnsSettings:
        """Get DNS configuration.

        Returns:
            DnsSettings model.
        """
        config = await self.get_config()
        return config.dns

    async def get_hostname(self) -> str:
        """Get device hostname.

        Returns:
            Hostname string.
        """
        config = await self.get_config()
        return config.hostname

    async def get_global_proxy(self) -> ProxySettings | None:
        """Get global proxy configuration.

        Returns:
            ProxySettings model or None if not configured.
        """
        config = await self.get_config()
        return config.global_proxy

    def _parse_config(self, data: dict[str, Any]) -> NetworkConfig:
        """Parse network configuration response.

        Args:
            data: Raw API response data.

        Returns:
            NetworkConfig model instance.
        """
        # Parse interfaces
        interfaces = []
        iface_data = data.get("interfaces", {})
        for name, iface_info in iface_data.items():
            if isinstance(iface_info, dict):
                interfaces.append(self._parse_interface(name, iface_info))

        # Parse DNS
        dns_data = data.get("resolver", {})
        name_servers = dns_data.get("staticNameServers", [])
        search_domains = dns_data.get("staticSearchDomains", [])
        dns = DnsSettings(
            primary=name_servers[0] if name_servers else "",
            secondary=name_servers[1] if len(name_servers) > 1 else "",
            domain=search_domains[0] if search_domains else "",
        )

        # Parse global proxy
        proxy_data = data.get("globalProxy", {})
        global_proxy = None
        if proxy_data:
            global_proxy = ProxySettings(
                enabled=proxy_data.get("enabled", False),
                host=proxy_data.get("host", ""),
                port=proxy_data.get("port", 0),
                username=proxy_data.get("username", ""),
            )

        return NetworkConfig(
            hostname=data.get("hostname", ""),
            interfaces=interfaces,
            dns=dns,
            global_proxy=global_proxy,
            bonjour_enabled=data.get("bonjour", {}).get("enabled", False),
            upnp_enabled=data.get("upnp", {}).get("enabled", False),
        )

    def _parse_interface(self, name: str, data: dict[str, Any]) -> NetworkInterface:
        """Parse interface data.

        Args:
            name: Interface name.
            data: Interface configuration data.

        Returns:
            NetworkInterface model.
        """
        ipv4 = data.get("ipv4", {})
        ipv6 = data.get("ipv6", {})
        link = data.get("link", {})

        return NetworkInterface(
            name=name,
            mac_address=link.get("MACAddress", ""),
            ip_address=ipv4.get("address", ""),
            subnet_mask=ipv4.get("netmask", ""),
            gateway=ipv4.get("gateway", ""),
            dhcp_enabled=ipv4.get("configurationMode", "") == "dhcp",
            ipv6_address=ipv6.get("address", ""),
            mtu=link.get("MTU", 1500),
            link_speed=link.get("speed", ""),
            link_status=link.get("status", "unknown"),
        )
