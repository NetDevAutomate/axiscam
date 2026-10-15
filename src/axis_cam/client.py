"""VAPIX HTTP client for AXIS device communication.

This module provides the core HTTP client for communicating with AXIS devices
via the VAPIX REST API. It handles authentication, request formatting, and
response parsing for all AXIS device types.

The client supports both the legacy CGI endpoints and the newer REST API
endpoints introduced in AXIS OS 11.x.
"""

import re
from typing import Any

import httpx

from axis_cam.auth import AuthMode, VapixAuth
from axis_cam.exceptions import (
    AxisAuthenticationError,
    AxisConnectionError,
    AxisDeviceError,
    AxisEchoError,
    AxisPermissionError,
)
from axis_cam.secrets import error_excerpt, quotes_sent_auth


def _version_sort_key(version: str) -> tuple[int, int]:
    """Order discovery version keys: ``v1beta`` < ``v1`` < ``v2beta`` < ``v2``."""
    match = re.match(r"v(\d+)(beta|alpha)?$", version)
    if not match:
        return (-1, 0)
    return (int(match.group(1)), 0 if match.group(2) else 1)


def _path_of(response: httpx.Response) -> str:
    """The request path, for messages; ``httpx`` raises without an attached request."""
    try:
        return response.url.path
    except (AttributeError, RuntimeError):
        return "a request"


#: Content types an echo page can come back as; binary downloads are scanned only then.
#: ``message/http`` is what TRACE, the standard request echo, answers with.
_TEXT_TYPES = re.compile(r"^\s*(?:text/|message/|application/(?:[\w.+-]*\+)?(?:json|xml)\b)", re.I)


def _is_text(response: httpx.Response) -> bool:
    """Whether the reply says it is text (``text/*``, ``message/*``, JSON or XML)."""
    try:
        content_type = response.headers.get("content-type", "")
    except AttributeError:
        return False
    return isinstance(content_type, str) and bool(_TEXT_TYPES.match(content_type))


class VapixClient:
    """HTTP client for VAPIX API communication.

    This client handles all HTTP communication with AXIS devices, including:
    - Basic or Digest authentication, chosen from the device's challenge by default
    - Request formatting for both legacy CGI and REST APIs
    - Response parsing and error handling
    - Connection management via async context manager

    The client is designed to be used as an async context manager:

    Example:
        >>> async with VapixClient("192.168.1.10", "admin", "password") as client:
        ...     response = await client.get("/axis-cgi/basicdeviceinfo.cgi")
        ...     print(response)

    Attributes:
        host: Device IP address or hostname.
        username: Authentication username.
        password: Authentication password.
        port: HTTP port (default 80).
        use_https: Whether to use HTTPS (default False).
        timeout: Request timeout in seconds.
        verify_ssl: Whether to verify SSL certificates.
        auth_mode: ``AUTO`` (follow the device's challenge: Basic over HTTPS,
            Digest over HTTP, switching if the device offers only the other),
            or ``BASIC`` / ``DIGEST`` to force one.
        allow_insecure_basic: Permit Basic over plain HTTP (cleartext credentials).
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 80,
        use_https: bool = False,
        timeout: float = 30.0,
        verify_ssl: bool = False,
        auth_mode: AuthMode | str = AuthMode.AUTO,
        *,
        allow_insecure_basic: bool = False,
    ) -> None:
        """Initialize the VAPIX client.

        Args:
            host: Device IP address or hostname.
            username: Authentication username.
            password: Authentication password.
            port: HTTP port (default 80).
            use_https: Whether to use HTTPS (default False).
            timeout: Request timeout in seconds.
            verify_ssl: Whether to verify SSL certificates.
            auth_mode: Authentication scheme policy (see class docstring).
            allow_insecure_basic: Permit Basic over plain HTTP.
        """
        self.host = host.strip()
        self.username = username
        self.password = password
        self.port = port
        self.use_https = use_https
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.auth_mode = AuthMode(auth_mode)
        self.allow_insecure_basic = allow_insecure_basic
        self._auth: VapixAuth | None = None
        self._client: httpx.AsyncClient | None = None
        self._discovery: dict[str, Any] | None = None

    @property
    def auth_scheme(self) -> str | None:
        """``"basic"`` or ``"digest"`` once settled by a request, else ``None``."""
        return self._auth.scheme if self._auth else None

    @property
    def base_url(self) -> str:
        """Get the base URL for API requests.

        Returns:
            Base URL string including protocol, host, and port.
        """
        protocol = "https" if self.use_https else "http"
        return f"{protocol}://{self.host}:{self.port}"

    async def __aenter__(self) -> "VapixClient":
        """Async context manager entry - establish connection.

        Returns:
            The connected client instance.
        """
        self._auth = VapixAuth(
            self.username,
            self.password,
            mode=self.auth_mode,
            https=self.use_https,
            allow_insecure_basic=self.allow_insecure_basic,
        )
        self._client = httpx.AsyncClient(
            auth=self._auth,
            timeout=self.timeout,
            verify=self.verify_ssl,
            follow_redirects=True,
            event_hooks={"response": [self._refuse_echoing_redirect]},
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Async context manager exit - close connection.

        Args:
            exc_type: Exception type if an error occurred.
            exc_val: Exception value if an error occurred.
            exc_tb: Exception traceback if an error occurred.
        """
        if self._client:
            await self._client.aclose()
            self._client = None

    def _ensure_connected(self) -> httpx.AsyncClient:
        """Ensure client is connected.

        Returns:
            The HTTP client instance.

        Raises:
            RuntimeError: If client is not connected.
        """
        if not self._client:
            raise RuntimeError("Client not connected. Use 'async with VapixClient(...) as client:'")
        return self._client

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Perform a GET request.

        Args:
            path: URL path (e.g., "/axis-cgi/basicdeviceinfo.cgi").
            params: Optional query parameters.

        Returns:
            HTTP response object.

        Raises:
            AxisConnectionError: If connection fails.
            AxisAuthenticationError: If authentication fails.
            AxisDeviceError: If device returns an error.
        """
        client = self._ensure_connected()
        url = f"{self.base_url}{path}"

        try:
            response = await client.get(url, params=params)
            self._check_response(response, path=path)
            return response
        except httpx.ConnectError as e:
            raise self._connection_error(e) from e
        except httpx.TimeoutException as e:
            raise AxisConnectionError(f"Connection timeout to {self.host}: {e}") from e

    async def post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Perform a POST request.

        Args:
            path: URL path.
            data: Form data to send.
            json: JSON data to send.

        Returns:
            HTTP response object.

        Raises:
            AxisConnectionError: If connection fails.
            AxisAuthenticationError: If authentication fails.
            AxisDeviceError: If device returns an error.
        """
        client = self._ensure_connected()
        url = f"{self.base_url}{path}"

        try:
            response = await client.post(url, data=data, json=json)
            self._check_response(response, path=path)
            return response
        except httpx.ConnectError as e:
            raise self._connection_error(e) from e
        except httpx.TimeoutException as e:
            raise AxisConnectionError(f"Connection timeout to {self.host}: {e}") from e

    async def post_raw(
        self, path: str, content: str | bytes, *, content_type: str
    ) -> httpx.Response:
        """POST a raw body (SOAP, XML) and return the response for the caller to interpret.

        Connection failures, a TLS/plain-HTTP mismatch, 401 and 403 are raised
        as usual. Any other status is returned: SOAP faults travel as HTTP 400
        or 500 with an XML body that says what went wrong, and only the caller
        can read it.

        Raises:
            AxisConnectionError: If connection fails.
            AxisAuthenticationError: If authentication fails (401).
            AxisPermissionError: If the account may not use the path (403).
        """
        client = self._ensure_connected()
        url = f"{self.base_url}{path}"
        try:
            response = await client.post(
                url, content=content, headers={"Content-Type": content_type}
            )
            self._check_response(response, path=path, raise_on_error_status=False)
            return response
        except httpx.ConnectError as e:
            raise self._connection_error(e) from e
        except httpx.TimeoutException as e:
            raise AxisConnectionError(f"Connection timeout to {self.host}: {e}") from e

    async def get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform a GET request and parse JSON response.

        Args:
            path: URL path.
            params: Optional query parameters.

        Returns:
            Parsed JSON response as dictionary.

        Raises:
            AxisConnectionError: If connection fails.
            AxisAuthenticationError: If authentication fails.
            AxisDeviceError: If device returns an error or invalid JSON.
        """
        response = await self.get(path, params)
        try:
            return response.json()
        except ValueError as e:
            raise AxisDeviceError(f"Invalid JSON response from {path}: {e}") from e

    async def post_json(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform a POST request and parse JSON response.

        Args:
            path: URL path.
            data: Form data to send.
            json_data: JSON data to send.

        Returns:
            Parsed JSON response as dictionary.

        Raises:
            AxisConnectionError: If connection fails.
            AxisAuthenticationError: If authentication fails.
            AxisDeviceError: If device returns an error or invalid JSON.
        """
        response = await self.post(path, data=data, json=json_data)
        try:
            return response.json()
        except ValueError as e:
            raise AxisDeviceError(f"Invalid JSON response from {path}: {e}") from e

    async def get_raw(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> bytes:
        """Perform a GET request and return raw bytes.

        Useful for binary content like images or archives.

        Args:
            path: URL path.
            params: Optional query parameters.

        Returns:
            Raw response content as bytes.

        Raises:
            AxisConnectionError: If connection fails.
            AxisAuthenticationError: If authentication fails.
            AxisDeviceError: If device returns an error.
        """
        client = self._ensure_connected()
        url = f"{self.base_url}{path}"
        try:
            response = await client.get(url, params=params)
            # Binary: not scanned for echoed credentials (see _check_response).
            self._check_response(response, path=path, scan_reply=False)
            return response.content
        except httpx.ConnectError as e:
            raise self._connection_error(e) from e
        except httpx.TimeoutException as e:
            raise AxisConnectionError(f"Connection timeout to {self.host}: {e}") from e

    async def get_binary(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> bytes:
        """Perform a GET request for binary content with custom timeout.

        Similar to get_raw but allows overriding the timeout for long-running
        operations like server report downloads.

        Args:
            path: URL path.
            params: Optional query parameters.
            timeout: Optional timeout override in seconds.

        Returns:
            Raw response content as bytes.

        Raises:
            AxisConnectionError: If connection fails.
            AxisAuthenticationError: If authentication fails.
            AxisDeviceError: If device returns an error.
        """
        client = self._ensure_connected()
        url = f"{self.base_url}{path}"

        # Use custom timeout if provided, otherwise use client default
        request_timeout = timeout if timeout is not None else self.timeout

        try:
            response = await client.get(url, params=params, timeout=request_timeout)
            # Binary: not scanned for echoed credentials (see _check_response).
            self._check_response(response, path=path, scan_reply=False)
            return response.content
        except httpx.ConnectError as e:
            raise self._connection_error(e) from e
        except httpx.TimeoutException as e:
            raise AxisConnectionError(f"Connection timeout to {self.host}: {e}") from e

    def _connection_error(self, exc: httpx.ConnectError) -> AxisConnectionError:
        """Translate a transport failure into an error that names the remedy.

        A TLS handshake against a port that speaks plain HTTP fails with
        ``SSL: WRONG_VERSION_NUMBER``. Since the scheme is no longer inferred
        from the port, a device configured ``port: 80`` without ``https: false``
        hits exactly this; the raw OpenSSL text does not tell the user what to
        change.
        """
        if "WRONG_VERSION_NUMBER" in str(exc):
            return AxisConnectionError(
                f"{self.host}:{self.port} answered plain HTTP to an HTTPS request. "
                "If this device is meant to use HTTP, set `https: false` for it in the "
                "config (library: https=False); otherwise set `port: 443`."
            )
        return AxisConnectionError(f"Failed to connect to {self.host}: {exc}")

    def _check_response(
        self,
        response: httpx.Response,
        *,
        path: str | None = None,
        raise_on_error_status: bool = True,
        scan_reply: bool = True,
    ) -> None:
        """Check HTTP response for errors.

        A reply that quotes credentials this client sent, in any common
        spelling (:func:`~axis_cam.secrets.quotes_sent_auth`), is refused first,
        whatever its status: no Axis device echoes request headers, so such a
        body is a proxy or peer echoing the request. It is not device data, and
        nothing downstream ever sees, parses or quotes it.

        Args:
            response: HTTP response to check.
            path: The path the caller asked for, which messages quote. Not
                ``response.url``: after a redirect that is the target, which the
                reply chose.
            raise_on_error_status: Raise ``AxisDeviceError`` for any other
                4xx/5xx. ``False`` leaves those to a caller that can read the
                body (SOAP faults); that caller quotes it only through
                :func:`~axis_cam.secrets.error_excerpt`.
            scan_reply: Scan the reply for the request's credentials. ``False``
                for binary downloads (snapshots, server reports), which are
                still scanned when the reply says it is text: an echo page
                always is.

        Raises:
            AxisEchoError: The reply quotes credentials this client sent.
            AxisConnectionError: Plain HTTP was sent to a port that expects TLS.
            AxisAuthenticationError: If authentication failed (401).
            AxisPermissionError: If the account may not use the path (403).
            AxisDeviceError: If device returned an error status.
        """
        where = path if path is not None else _path_of(response)
        if (scan_reply or _is_text(response)) and quotes_sent_auth(
            response.text,
            response,
            username=self.username,
            password=self.password,
            sent=self._sent(),
        ):
            raise AxisEchoError(
                f"Refused the reply from {self.host} to {where} "
                f"(HTTP {response.status_code}): it quotes this request's credentials, "
                "so a proxy or peer is echoing requests."
            )
        if response.status_code == 400 and "plain http" in response.text.lower():
            # Apache: "You're speaking plain HTTP to an SSL-enabled server port";
            # nginx: "The plain HTTP request was sent to HTTPS port".
            raise AxisConnectionError(
                f"{self.host}:{self.port} expects HTTPS but was sent plain HTTP. "
                "Remove `https: false` for this device (library: https=True), or use "
                "the device's HTTP port."
            )
        if response.status_code == 401:
            raise AxisAuthenticationError(
                f"Authentication failed for {self.host}. Check username/password."
            )
        if response.status_code == 403:
            raise AxisPermissionError(
                f"Access denied to {self.host}: this account may not use {where} (403)."
            )
        if response.status_code >= 400 and raise_on_error_status:
            excerpt = error_excerpt(response.text, password=self.password)
            raise AxisDeviceError(
                f"Device error {response.status_code} from {self.host}: {excerpt}"
            )

    def _sent(self) -> tuple[str, ...]:
        """Every ``Authorization`` value this client has sent (``VapixAuth.sent``)."""
        return tuple(self._auth.sent) if self._auth is not None else ()

    async def _refuse_echoing_redirect(self, response: httpx.Response) -> None:
        """Response hook: refuse a redirect whose target quotes the credentials.

        httpx follows a redirect -- requesting the target and logging its URL --
        before ``_check_response`` sees the final reply. A target that carries
        the token is an echo like any other, so it is refused here and never
        requested.

        Raises:
            AxisEchoError: The redirect's ``Location`` quotes credentials this
                client sent.
        """
        location = response.headers.get("location")
        if (
            response.is_redirect
            and isinstance(location, str)
            and quotes_sent_auth(
                location,
                response,
                username=self.username,
                password=self.password,
                sent=self._sent(),
            )
        ):
            raise AxisEchoError(
                f"Refused a redirect from {self.host} at {_path_of(response)} "
                f"(HTTP {response.status_code}): its target quotes this request's "
                "credentials, so a proxy or peer is echoing requests."
            )

    def refuse_echo(self, text: str) -> None:
        """Refuse device text that quotes credentials this client sent.

        For text the client only sees after decoding a binary download (a log
        file inside the server-report tarball), when the response is gone: the
        text is checked against every ``Authorization`` value the client sent
        (Basic tokens and Digest hashes, ``VapixAuth.sent``) and the configured
        Basic token.

        Raises:
            AxisEchoError: ``text`` quotes credentials this client sent.
        """
        if quotes_sent_auth(
            text, None, username=self.username, password=self.password, sent=self._sent()
        ):
            raise AxisEchoError(
                f"Refused content from {self.host}: it quotes this client's credentials, "
                "so a proxy or peer is echoing requests."
            )

    DISCOVERY_PATH = "/config/discover/apis"

    async def discover_apis(self) -> dict[str, Any]:
        """Discover the device-configuration REST APIs the device advertises.

        ``GET /config/discover/apis`` (no ``.json`` suffix: the suffixed form
        is a 404 on AXIS OS 11.11 and 12.11, verified 2026-10-13) answers a
        mapping of API id to its versions, each with a ``rest_api`` path such
        as ``/config/rest/ssh/v2``. The result is cached for the lifetime of
        the client; the device's API set does not change between requests.

        Returns:
            Dictionary mapping API ids to their version entries; ``{}`` when
            the device has no discovery endpoint.

        Raises:
            AxisConnectionError: If connection fails.
            AxisAuthenticationError: If the credentials are rejected.
        """
        if self._discovery is None:
            try:
                self._discovery = await self.get_json(self.DISCOVERY_PATH)
            except AxisDeviceError:
                # Older devices may not support discovery
                self._discovery = {}
        return self._discovery

    async def rest_path_for(self, api_id: str, *, prefer: str | None = None) -> str | None:
        """The ``rest_api`` path the device advertises for ``api_id``.

        Devices move APIs between versions (``v1beta`` → ``v1`` → ``v2``) and
        remove the old path, so a module must ask rather than hard-code one.

        Args:
            api_id: Discovery id, e.g. ``"ssh"``.
            prefer: A version key (``"v2"``) to pick when several are offered;
                otherwise the highest version wins.

        Returns:
            The path, or ``None`` if the device does not advertise the API (or
            has no discovery at all).
        """
        entry = (await self.discover_apis()).get(api_id)
        if not isinstance(entry, dict) or not entry:
            return None
        versions = {k: v for k, v in entry.items() if isinstance(v, dict) and v.get("rest_api")}
        if not versions:
            return None
        if prefer and prefer in versions:
            return versions[prefer]["rest_api"]
        best = max(versions, key=_version_sort_key)
        return versions[best]["rest_api"]

    async def check_connectivity(self) -> bool:
        """Check if device is reachable and credentials are valid.

        An echoing peer counts as unreachable: its reply is refused
        (``AxisEchoError``, an ``AxisConnectionError``), because whatever
        answered is not the device as sent. Call :meth:`get` to see why.

        Returns:
            True if device is accessible and authenticated.
        """
        try:
            await self.get("/axis-cgi/basicdeviceinfo.cgi")
            return True
        except (AxisConnectionError, AxisAuthenticationError):
            return False
