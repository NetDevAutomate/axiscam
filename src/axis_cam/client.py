"""VAPIX HTTP client for AXIS device communication.

This module provides the core HTTP client for communicating with AXIS devices
via the VAPIX REST API. It handles authentication, request formatting, and
response parsing for all AXIS device types.

The client supports both the legacy CGI endpoints and the newer REST API
endpoints introduced in AXIS OS 11.x.
"""

from typing import Any

import httpx

from axis_cam.exceptions import (
    AxisAuthenticationError,
    AxisConnectionError,
    AxisDeviceError,
)


class VapixClient:
    """HTTP client for VAPIX API communication.

    This client handles all HTTP communication with AXIS devices, including:
    - Basic or Digest authentication (configurable, defaults to Basic)
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
        use_digest_auth: Use Digest auth instead of Basic (default False).
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
        use_digest_auth: bool = False,
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
            use_digest_auth: Use Digest auth instead of Basic (default False).
        """
        self.host = host.strip()
        self.username = username
        self.password = password
        self.port = port
        self.use_https = use_https
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.use_digest_auth = use_digest_auth
        self._client: httpx.AsyncClient | None = None

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
        if self.use_digest_auth:
            auth = httpx.DigestAuth(self.username, self.password)
        else:
            auth = httpx.BasicAuth(self.username, self.password)

        self._client = httpx.AsyncClient(
            auth=auth,
            timeout=self.timeout,
            verify=self.verify_ssl,
            follow_redirects=True,
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
            self._check_response(response)
            return response
        except httpx.ConnectError as e:
            raise AxisConnectionError(f"Failed to connect to {self.host}: {e}") from e
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
            self._check_response(response)
            return response
        except httpx.ConnectError as e:
            raise AxisConnectionError(f"Failed to connect to {self.host}: {e}") from e
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
        response = await self.get(path, params)
        return response.content

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
            self._check_response(response)
            return response.content
        except httpx.ConnectError as e:
            raise AxisConnectionError(f"Failed to connect to {self.host}: {e}") from e
        except httpx.TimeoutException as e:
            raise AxisConnectionError(f"Connection timeout to {self.host}: {e}") from e

    def _check_response(self, response: httpx.Response) -> None:
        """Check HTTP response for errors.

        Args:
            response: HTTP response to check.

        Raises:
            AxisAuthenticationError: If authentication failed (401).
            AxisDeviceError: If device returned an error status.
        """
        if response.status_code == 401:
            raise AxisAuthenticationError(
                f"Authentication failed for {self.host}. Check username/password."
            )
        if response.status_code == 403:
            raise AxisAuthenticationError(
                f"Access denied to {self.host}. Insufficient permissions."
            )
        if response.status_code >= 400:
            raise AxisDeviceError(
                f"Device error {response.status_code} from {self.host}: {response.text[:200]}"
            )

    async def discover_apis(self) -> dict[str, Any]:
        """Discover available APIs on the device.

        Queries the device's API discovery endpoint to determine
        which APIs are available and their versions.

        Returns:
            Dictionary mapping API names to their configuration.

        Raises:
            AxisConnectionError: If connection fails.
            AxisDeviceError: If discovery fails.
        """
        try:
            return await self.get_json("/config/discover/apis.json")
        except AxisDeviceError:
            # Older devices may not support discovery
            return {}

    async def check_connectivity(self) -> bool:
        """Check if device is reachable and credentials are valid.

        Returns:
            True if device is accessible and authenticated.
        """
        try:
            await self.get("/axis-cgi/basicdeviceinfo.cgi")
            return True
        except (AxisConnectionError, AxisAuthenticationError):
            return False
