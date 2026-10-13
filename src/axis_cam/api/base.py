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

from axis_cam.exceptions import AxisApiNotSupportedError

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
    #: Hard-coded REST path, used when the device does not advertise ``api_id``.
    REST_PATH: ClassVar[str | None] = None

    @staticmethod
    def _items(collection: Any, *, id_key: str = "id") -> list[tuple[str, dict[str, Any]]]:
        """Normalise a REST collection to ``[(id, entry), ...]``.

        Device-configuration APIs return collections in two shapes: a mapping
        keyed by id (``{"abc": {...}}``, the shape the early fixtures assumed)
        or a list of entries each carrying its own id (``[{"id": "abc", ...}]``,
        what AXIS OS 12.11 devices actually return for recording groups, storage
        destinations and action rules; verified 2026-10-13). ``None`` and
        unknown shapes yield no items rather than raising.
        """
        if isinstance(collection, dict):
            return [(str(k), v) for k, v in collection.items() if isinstance(v, dict)]
        if isinstance(collection, list):
            return [
                (str(entry.get(id_key, index)), entry)
                for index, entry in enumerate(collection)
                if isinstance(entry, dict)
            ]
        return []

    async def _rest_path(self) -> str:
        """The REST base path to use for this module on this device.

        Devices move an API between versions (``/config/rest/ntp/v1beta`` →
        ``…/v1``) and often drop the old path, so the path advertised in
        ``/config/discover/apis`` wins; the class's ``REST_PATH`` is only the
        fallback for devices without discovery (verified against four devices,
        2026-10-13: five of the hard-coded paths were 404 on current firmware).

        Raises:
            AxisApiNotSupportedError: Neither discovery nor ``REST_PATH`` gives a path.
        """
        if self.api_id:
            advertised = await self._client.rest_path_for(self.api_id)
            if advertised:
                return advertised
        if self.REST_PATH is None:
            raise AxisApiNotSupportedError(f"{self.name}: no REST path for this device")
        return self.REST_PATH

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

    async def _get_text(self, path: str, params: dict[str, Any] | None = None) -> str:
        """Perform a GET request and return the body as text.

        For legacy CGIs that answer ``text/plain``. HTTP-level errors are
        raised by the client; a CGI that reports failure with a 200 body is
        the caller's job to inspect.
        """
        response = await self._client.get(path, params)
        return response.text

    async def _post_form(self, path: str, data: dict[str, Any]) -> str:
        """POST form-encoded data and return the body as text.

        Use this for CGIs that take credentials or other secrets: form data
        travels in the request body, never in the URL (device access logs,
        proxies, shell history).
        """
        response = await self._client.post(path, data=data)
        return response.text
