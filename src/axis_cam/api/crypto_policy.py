"""System-wide cryptographic policy (``/config/rest/crypto-policy/v1``).

Contract (AXIS OS 12.11, ``crypto-policy/v1/openapi.json``)::

    {"active_policy": "DEFAULT", "policies": [{"name", "nice_name", "description"}]}

The device offers ``DEFAULT`` (OpenSSL default), ``MODERN`` and ``FIPS``. There
is no per-cipher or per-TLS-version detail in this API; the HTTPS cipher list
and legacy TLS switches are parameters (``HTTPS.Ciphers``, ``HTTPS.AllowTLS1``,
``HTTPS.AllowTLS11`` — the last two absent on AXIS OS 12, which removed them).
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.api.registry import register
from axis_cam.models import CryptoPolicy, CryptoPolicyConfig


@register
class CryptoPolicyAPI(BaseAPI):
    """Read the active cryptographic policy.

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     policy = await camera.crypto_policy.read()
        ...     policy.active_policy
    """

    name = "crypto_policy"
    api_id = "crypto-policy"

    REST_PATH = "/config/rest/crypto-policy/v1"

    async def read(self) -> CryptoPolicyConfig:
        """Read the policy; errors propagate (404 on products without the API)."""
        response = await self._get(await self._rest_path())
        return self.parse(response.get("data", {}))

    async def get_config(self) -> CryptoPolicyConfig:
        """Alias of :meth:`read`."""
        return await self.read()

    @staticmethod
    def parse(data: dict[str, Any]) -> CryptoPolicyConfig:
        """Build the model from the ``data`` object."""
        return CryptoPolicyConfig(
            active_policy=str(data.get("active_policy", "")),
            policies=[
                CryptoPolicy(
                    name=str(p.get("name", "")),
                    nice_name=str(p.get("nice_name", "")),
                    description=str(p.get("description", "")),
                )
                for p in data.get("policies", [])
                if isinstance(p, dict)
            ],
        )
