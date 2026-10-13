"""Base class for AXIS VAPIX API modules.

Each API module encapsulates one VAPIX API domain (device info, SSH, NTP, …)
and uses composition with the :class:`~axis_cam.client.VapixClient` for HTTP
communication. Modules declare a ``name`` and an ``api_id`` and register
themselves with :func:`axis_cam.api.registry.register`; ``AxisDevice`` builds
its modules from that registry rather than naming each class by hand.

``BaseAPI`` is deliberately a plain base class, not an ABC: it exists to share
the request helpers, and it has no method every module must override. The
contract generic code relies on is the structural
:class:`~axis_cam.api.registry.ResourceModule` protocol.
"""

from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from axis_cam.client import VapixClient


class BaseAPI:
    """Base class for VAPIX API modules.

    Subclasses set two class attributes:

    - ``name``: the attribute the module is exposed under on ``AxisDevice``
      (``device.ssh``) and the key used by reports and backups.
    - ``api_id``: the identifier the device advertises for this API in
      ``/config/discover/apis.json``. ``None`` means the module does not depend
      on a discoverable REST API (legacy CGI) and is always attempted.

    Example:
        >>> @register
        ... class SshAPI(BaseAPI):
        ...     name = "ssh"
        ...     api_id = "ssh"
        ...     async def read(self) -> SshConfig:
        ...         return await self.get_config()

    Attributes:
        _client: The VapixClient instance for HTTP communication.
    """

    name: ClassVar[str]
    api_id: ClassVar[str | None] = None

    def __init__(self, client: "VapixClient") -> None:
        """Initialize the API module.

        Args:
            client: VapixClient instance for HTTP communication.
        """
        self._client = client

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Perform a GET request via the client.

        Args:
            path: URL path for the request.
            params: Optional query parameters.

        Returns:
            Response data (typically dict from JSON).
        """
        return await self._client.get_json(path, params)

    async def _post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> Any:
        """Perform a POST request via the client.

        Args:
            path: URL path for the request.
            data: Form data to send.
            json_data: JSON data to send.

        Returns:
            Response data (typically dict from JSON).
        """
        return await self._client.post_json(path, data=data, json_data=json_data)

    async def _get_raw(self, path: str, params: dict[str, Any] | None = None) -> bytes:
        """Perform a GET request and return raw bytes.

        Args:
            path: URL path for the request.
            params: Optional query parameters.

        Returns:
            Raw response bytes.
        """
        return await self._client.get_raw(path, params)
