"""Network time synchronisation (``/config/rest/network-time-sync/v1``).

Contract (AXIS OS 12.11, ``network-time-sync/v1/openapi.json``)::

    {"ntp": {"client": {"enabled", "synced", "serversSource": "STATIC"|"DHCP",
                        "staticServers": [..], "advertisedServers": [..],
                        "timeOffset", "nts": {"enabled", ...}, ...}},
     "ptp": {"portState", ...}, "ptp_supported": bool}

The device advertises this API as ``v1beta`` on some firmware; the path is
resolved from discovery, so either answers.
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.api.registry import register
from axis_cam.models import NtpConfig


@register
class NtpAPI(BaseAPI):
    """Read NTP/PTP state.

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     ntp = await camera.ntp.read()
        ...     ntp.enabled, ntp.synced, ntp.static_servers
    """

    name = "ntp"
    api_id = "network-time-sync"

    REST_PATH = "/config/rest/network-time-sync/v1beta"

    async def read(self) -> NtpConfig:
        """Read the configuration; errors propagate (404 on products without the API)."""
        response = await self._get(await self._rest_path())
        return self.parse(response.get("data", {}))

    async def get_config(self) -> NtpConfig:
        """Alias of :meth:`read`."""
        return await self.read()

    @staticmethod
    def parse(data: dict[str, Any]) -> NtpConfig:
        """Build the model from the ``data`` object."""
        client = (data.get("ntp") or {}).get("client") or {}
        nts = client.get("nts") or {}
        ptp = data.get("ptp") or {}
        return NtpConfig(
            enabled=bool(client.get("enabled", False)),
            synced=bool(client.get("synced", False)),
            servers_source=str(client.get("serversSource", "")),
            static_servers=[s for s in client.get("staticServers", []) if s],
            advertised_servers=[s for s in client.get("advertisedServers", []) if s],
            time_offset_s=float(client.get("timeOffset", 0.0) or 0.0),
            nts_enabled=bool(nts.get("enabled", False)),
            ptp_supported=bool(data.get("ptp_supported", False)),
            ptp_port_state=str(ptp.get("portState", "")),
        )
