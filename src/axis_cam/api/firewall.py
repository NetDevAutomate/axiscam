"""Device firewall (``/config/rest/firewall/v1``).

Contract (AXIS OS 12.11, ``firewall/v1/openapi.json``)::

    {"activated": bool,
     "conf": {"rules": {"activeDefaultPolicy": "ACCEPT"|"DROP",
                        "activeRules": [Rule], "pendingDefaultPolicy": ..|null,
                        "pendingRules": [Rule], "testTimeLeft": int}}}

``Rule`` has ``ruleType`` (``FILTER``/``LIMIT``) and at most one of ``ip``,
``ipRange``, ``mac``, ``port``, ``portRange``, plus ``limit`` for LIMIT rules.
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.api.registry import register
from axis_cam.models import FirewallConfig, FirewallPolicy, FirewallRule


def _policy(value: Any) -> FirewallPolicy | None:
    try:
        return FirewallPolicy(str(value))
    except ValueError:
        return None


def parse_rule(data: dict[str, Any]) -> FirewallRule:
    """Flatten one ``datatype.Rule`` into display-ready strings."""
    port = data.get("port") or {}
    port_range = data.get("portRange") or {}
    ip_range = data.get("ipRange") or {}
    limit = data.get("limit") or {}
    mac = data.get("mac") or {}
    return FirewallRule(
        rule_type=str(data.get("ruleType", "")),
        ip=data.get("ip") or None,
        ip_range=(f"{ip_range.get('start', '')}-{ip_range.get('end', '')}" if ip_range else None),
        port=f"{port.get('portType', '')}/{port.get('portNum', '')}" if port else None,
        port_range=(
            f"{port_range.get('portType', '')}/{port_range.get('start', '')}-"
            f"{port_range.get('end', '')}"
            if port_range
            else None
        ),
        mac=(mac.get("address") or mac.get("mac")) if isinstance(mac, dict) else None,
        limit=(
            f"{limit.get('amount', '')} {limit.get('unit', '')}/{limit.get('period', '')} "
            f"burst {limit.get('burst', '')}"
            if limit
            else None
        ),
    )


@register
class FirewallAPI(BaseAPI):
    """Read the firewall state.

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     fw = await camera.firewall.read()
        ...     fw.activated, fw.default_policy, len(fw.rules)
    """

    name = "firewall"
    api_id = "firewall"

    REST_PATH = "/config/rest/firewall/v1"

    async def read(self) -> FirewallConfig:
        """Read the firewall configuration; errors propagate."""
        response = await self._get(await self._rest_path())
        return self.parse(response.get("data", {}))

    async def get_config(self) -> FirewallConfig:
        """Alias of :meth:`read`."""
        return await self.read()

    @staticmethod
    def parse(data: dict[str, Any]) -> FirewallConfig:
        """Build the model from the ``data`` object."""
        rules = (data.get("conf") or {}).get("rules") or {}
        return FirewallConfig(
            activated=bool(data.get("activated", False)),
            default_policy=_policy(rules.get("activeDefaultPolicy")) or FirewallPolicy.ACCEPT,
            rules=[parse_rule(r) for r in rules.get("activeRules", []) if isinstance(r, dict)],
            pending_rules=[
                parse_rule(r) for r in rules.get("pendingRules", []) if isinstance(r, dict)
            ],
            pending_default_policy=_policy(rules.get("pendingDefaultPolicy")),
            test_time_left=int(rules.get("testTimeLeft", 0) or 0),
        )
