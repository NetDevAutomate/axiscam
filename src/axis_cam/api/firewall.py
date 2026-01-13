"""Firewall API module.

This module provides access to firewall configuration on AXIS devices
via the VAPIX firewall API.

API Endpoints:
    - /config/rest/firewall/v1 (REST API)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import (
    FirewallAction,
    FirewallConfig,
    FirewallProtocol,
    FirewallRule,
)


class FirewallAPI(BaseAPI):
    """API module for firewall configuration.

    This module provides methods to retrieve and manage firewall settings:
    - Firewall enabled/disabled state
    - IPv4 and IPv6 rules
    - Default policies
    - Address filtering

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.firewall.get_config()
        ...     print(f"Firewall enabled: {config.enabled}")
        ...     for rule in config.ipv4_rules:
        ...         print(f"  {rule.action}: {rule.source} -> {rule.dest_port}")
    """

    REST_PATH = "/config/rest/firewall/v1"

    async def get_config(self) -> FirewallConfig:
        """Get complete firewall configuration.

        Returns:
            FirewallConfig model with all firewall settings.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return FirewallConfig()

    async def is_enabled(self) -> bool:
        """Check if firewall is enabled.

        Returns:
            True if firewall is active.
        """
        config = await self.get_config()
        return config.enabled

    async def get_ipv4_rules(self) -> list[FirewallRule]:
        """Get IPv4 firewall rules.

        Returns:
            List of FirewallRule models.
        """
        config = await self.get_config()
        return config.ipv4_rules

    async def get_ipv6_rules(self) -> list[FirewallRule]:
        """Get IPv6 firewall rules.

        Returns:
            List of FirewallRule models.
        """
        config = await self.get_config()
        return config.ipv6_rules

    async def get_default_policy(self) -> FirewallAction:
        """Get default firewall policy.

        Returns:
            Default action for unmatched traffic.
        """
        config = await self.get_config()
        return config.default_policy

    def _parse_config(self, data: dict[str, Any]) -> FirewallConfig:
        """Parse firewall configuration response.

        Args:
            data: Raw API response data.

        Returns:
            FirewallConfig model instance.
        """
        # Parse IPv4 rules
        ipv4_rules = []
        for rule_data in data.get("ipv4Rules", []):
            rule = self._parse_rule(rule_data)
            if rule:
                ipv4_rules.append(rule)

        # Parse IPv6 rules
        ipv6_rules = []
        for rule_data in data.get("ipv6Rules", []):
            rule = self._parse_rule(rule_data)
            if rule:
                ipv6_rules.append(rule)

        # Parse default policy
        default_policy_str = data.get("defaultPolicy", "allow")
        try:
            default_policy = FirewallAction(default_policy_str.lower())
        except ValueError:
            default_policy = FirewallAction.ALLOW

        return FirewallConfig(
            enabled=data.get("enabled", False),
            ipv4_rules=ipv4_rules,
            ipv6_rules=ipv6_rules,
            default_policy=default_policy,
            icmp_allowed=data.get("allowICMP", True),
        )

    def _parse_rule(self, data: dict[str, Any]) -> FirewallRule | None:
        """Parse a single firewall rule.

        Args:
            data: Rule data from API.

        Returns:
            FirewallRule model or None if invalid.
        """
        try:
            action_str = data.get("action", "allow")
            try:
                action = FirewallAction(action_str.lower())
            except ValueError:
                action = FirewallAction.ALLOW

            protocol_str = data.get("protocol", "any")
            try:
                protocol = FirewallProtocol(protocol_str.lower())
            except ValueError:
                protocol = FirewallProtocol.ANY

            return FirewallRule(
                action=action,
                protocol=protocol,
                source=data.get("sourceAddress", ""),
                source_port=data.get("sourcePort", ""),
                destination=data.get("destAddress", ""),
                dest_port=data.get("destPort", ""),
                description=data.get("description", ""),
                enabled=data.get("enabled", True),
            )
        except Exception:
            return None
