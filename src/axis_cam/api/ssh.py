"""SSH: who may log in, and whether the service is on.

Contract (AXIS OS 12.11, ``/config/discover/apis/ssh/v2/openapi.json``): the
REST API ``/config/rest/ssh/v2`` exposes ``{"users": [{"username", "comment"}]}``
and nothing else — the on/off switch is the parameter ``Network.SSH.Enabled``
(the AXIS OS Hardening Guide's own instruction is
``param.cgi?action=update&Network.SSH.Enabled=no``). The reader combines both.
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.api.param import ParamAPI
from axis_cam.api.registry import register
from axis_cam.models import SshConfig, SshUser


@register
class SshAPI(BaseAPI):
    """Read SSH state.

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     ssh = await camera.ssh.read()
        ...     ssh.enabled, [u.username for u in ssh.users]
    """

    name = "ssh"
    api_id = "ssh"

    REST_PATH = "/config/rest/ssh/v2"
    ENABLED_PARAM = "Network.SSH.Enabled"

    async def read(self) -> SshConfig:
        """SSH users from the REST API and the enabled flag from ``param.cgi``.

        Raises:
            AxisAuthenticationError / AxisPermissionError / AxisConnectionError /
            AxisDeviceError: Propagate; a reader that cannot read says so.
        """
        response = await self._get(await self._rest_path())
        enabled = await ParamAPI(self._client).get(self.ENABLED_PARAM)
        return self.parse(response.get("data", {}), enabled)

    async def get_config(self) -> SshConfig:
        """Alias of :meth:`read`."""
        return await self.read()

    @staticmethod
    def parse(data: dict[str, Any], enabled_param: str | None) -> SshConfig:
        """Build the model from the ``data`` object and the ``Network.SSH.Enabled`` value."""
        users = [
            SshUser(username=str(u.get("username", "")), comment=str(u.get("comment", "")))
            for u in data.get("users", [])
            if isinstance(u, dict)
        ]
        enabled = None if enabled_param is None else enabled_param.strip().lower() == "yes"
        return SshConfig(enabled=enabled, users=users)
