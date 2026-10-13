"""SNMP (``/config/rest/snmp/v1``), without ever keeping the community strings.

Contract (AXIS OS 12.11, ``snmp/v1/openapi.json``)::

    {"enabled": bool, "snmpV1": {"enabled"}, "snmpV2": {"enabled"},
     "snmpV3": {"enabled", "userPasswdSet", "userEncryption", "supportedEncryption"},
     "snmpV1V2Common": {"readCommunity", "writeCommunity", "address",
                        "trap": {"enabled", "community", ...}},
     "transportProtocol": "udp"|"tcp", "dscp", "engineBoots", "ntcip_supported"}

Community strings are credentials; the model records only whether they are set
and whether the read community is the well-known default.
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.api.registry import register
from axis_cam.models import SnmpConfig

DEFAULT_READ_COMMUNITY = "public"


@register
class SnmpAPI(BaseAPI):
    """Read SNMP state.

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     snmp = await camera.snmp.read()
        ...     snmp.enabled, snmp.v1_enabled, snmp.read_community_is_default
    """

    name = "snmp"
    api_id = "snmp"

    REST_PATH = "/config/rest/snmp/v1"

    async def read(self) -> SnmpConfig:
        """Read the SNMP configuration; errors propagate."""
        response = await self._get(await self._rest_path())
        return self.parse(response.get("data", {}))

    async def get_config(self) -> SnmpConfig:
        """Alias of :meth:`read`."""
        return await self.read()

    @staticmethod
    def parse(data: dict[str, Any]) -> SnmpConfig:
        """Build the model from the ``data`` object, dropping the community strings."""
        v1 = data.get("snmpV1") or {}
        v2 = data.get("snmpV2") or {}
        v3 = data.get("snmpV3") or {}
        common = data.get("snmpV1V2Common") or {}
        trap = common.get("trap") or {}
        return SnmpConfig(
            enabled=bool(data.get("enabled", False)),
            v1_enabled=bool(v1.get("enabled", False)),
            v2c_enabled=bool(v2.get("enabled", False)),
            v3_enabled=bool(v3.get("enabled", False)),
            v3_password_set=bool(v3.get("userPasswdSet", False)),
            v3_encryption=str(v3.get("userEncryption", "")),
            read_community_is_default=str(common.get("readCommunity", ""))
            == DEFAULT_READ_COMMUNITY,
            write_community_set=bool(common.get("writeCommunity")),
            trap_enabled=bool(trap.get("enabled", False)),
            trap_address=str(common.get("address", "")),
            transport_protocol=str(data.get("transportProtocol", "udp")),
        )
