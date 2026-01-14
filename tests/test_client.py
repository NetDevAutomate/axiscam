"""Tests for VapixClient."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from axis_cam.client import VapixClient
from axis_cam.exceptions import (
    AxisAuthenticationError,
    AxisConnectionError,
    AxisDeviceError,
)


class TestVapixClientInit:
    """Tests for VapixClient initialization."""

    def test_init_with_defaults(self):
        """Test VapixClient initialization with defaults."""
        client = VapixClient("192.168.1.10", "admin", "password")
        assert client.host == "192.168.1.10"
        assert client.username == "admin"
        assert client.password == "password"
        assert client.port == 80
        assert client.use_https is False
        assert client.timeout == 30.0
        assert client.verify_ssl is False
        assert client._client is None

    def test_init_with_custom_values(self):
        """Test VapixClient initialization with custom values."""
        client = VapixClient(
            host="192.168.1.10",
            username="admin",
            password="secret",
            port=443,
            use_https=True,
            timeout=60.0,
            verify_ssl=True,
        )
        assert client.port == 443
        assert client.use_https is True
        assert client.timeout == 60.0
        assert client.verify_ssl is True

    def test_host_is_stripped(self):
        """Test that host is stripped of whitespace."""
        client = VapixClient("  192.168.1.10  ", "admin", "password")
        assert client.host == "192.168.1.10"


class TestVapixClientBaseUrl:
    """Tests for base_url property."""

    def test_http_base_url(self):
        """Test HTTP base URL."""
        client = VapixClient("192.168.1.10", "admin", "password", port=80)
        assert client.base_url == "http://192.168.1.10:80"

    def test_https_base_url(self):
        """Test HTTPS base URL."""
        client = VapixClient("192.168.1.10", "admin", "password", port=443, use_https=True)
        assert client.base_url == "https://192.168.1.10:443"


class TestVapixClientContextManager:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_aenter_creates_client(self):
        """Test that __aenter__ creates the HTTP client."""
        client = VapixClient("192.168.1.10", "admin", "password")
        assert client._client is None

        async with client as connected_client:
            assert connected_client._client is not None
            assert isinstance(connected_client._client, httpx.AsyncClient)

    @pytest.mark.asyncio
    async def test_aexit_closes_client(self):
        """Test that __aexit__ closes the HTTP client."""
        client = VapixClient("192.168.1.10", "admin", "password")

        async with client:
            http_client = client._client
            assert http_client is not None

        assert client._client is None

    @pytest.mark.asyncio
    async def test_aexit_handles_exception(self):
        """Test that __aexit__ still closes client on exception."""
        client = VapixClient("192.168.1.10", "admin", "password")

        with pytest.raises(ValueError):
            async with client:
                raise ValueError("test error")

        assert client._client is None


class TestVapixClientEnsureConnected:
    """Tests for _ensure_connected method."""

    def test_raises_when_not_connected(self):
        """Test RuntimeError when client not connected."""
        client = VapixClient("192.168.1.10", "admin", "password")
        with pytest.raises(RuntimeError, match="Client not connected"):
            client._ensure_connected()

    @pytest.mark.asyncio
    async def test_returns_client_when_connected(self):
        """Test returns client when connected."""
        client = VapixClient("192.168.1.10", "admin", "password")
        async with client:
            http_client = client._ensure_connected()
            assert http_client is not None


class TestVapixClientCheckResponse:
    """Tests for _check_response method."""

    def test_401_raises_authentication_error(self):
        """Test 401 status raises AxisAuthenticationError."""
        client = VapixClient("192.168.1.10", "admin", "password")
        response = MagicMock(spec=httpx.Response)
        response.status_code = 401

        with pytest.raises(AxisAuthenticationError, match="Authentication failed"):
            client._check_response(response)

    def test_403_raises_authentication_error(self):
        """Test 403 status raises AxisAuthenticationError."""
        client = VapixClient("192.168.1.10", "admin", "password")
        response = MagicMock(spec=httpx.Response)
        response.status_code = 403

        with pytest.raises(AxisAuthenticationError, match="Access denied"):
            client._check_response(response)

    def test_4xx_raises_device_error(self):
        """Test 4xx status raises AxisDeviceError."""
        client = VapixClient("192.168.1.10", "admin", "password")
        response = MagicMock(spec=httpx.Response)
        response.status_code = 404
        response.text = "Not Found"

        with pytest.raises(AxisDeviceError, match="Device error 404"):
            client._check_response(response)

    def test_5xx_raises_device_error(self):
        """Test 5xx status raises AxisDeviceError."""
        client = VapixClient("192.168.1.10", "admin", "password")
        response = MagicMock(spec=httpx.Response)
        response.status_code = 500
        response.text = "Internal Server Error"

        with pytest.raises(AxisDeviceError, match="Device error 500"):
            client._check_response(response)

    def test_200_does_not_raise(self):
        """Test 200 status does not raise."""
        client = VapixClient("192.168.1.10", "admin", "password")
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200

        # Should not raise
        client._check_response(response)


class TestVapixClientGet:
    """Tests for GET request methods."""

    @pytest.mark.asyncio
    async def test_get_returns_response(self):
        """Test get method returns response."""
        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            client = VapixClient("192.168.1.10", "admin", "password")
            async with client:
                response = await client.get("/test/path")
                assert response == mock_response

    @pytest.mark.asyncio
    async def test_get_raises_connection_error_on_connect_error(self):
        """Test get raises AxisConnectionError on connect error."""
        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_get.side_effect = httpx.ConnectError("Connection refused")

            client = VapixClient("192.168.1.10", "admin", "password")
            async with client:
                with pytest.raises(AxisConnectionError, match="Failed to connect"):
                    await client.get("/test/path")

    @pytest.mark.asyncio
    async def test_get_raises_connection_error_on_timeout(self):
        """Test get raises AxisConnectionError on timeout."""
        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_get.side_effect = httpx.TimeoutException("Request timeout")

            client = VapixClient("192.168.1.10", "admin", "password")
            async with client:
                with pytest.raises(AxisConnectionError, match="Connection timeout"):
                    await client.get("/test/path")

    @pytest.mark.asyncio
    async def test_get_json_parses_response(self):
        """Test get_json parses JSON response."""
        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.json.return_value = {"key": "value"}
            mock_get.return_value = mock_response

            client = VapixClient("192.168.1.10", "admin", "password")
            async with client:
                result = await client.get_json("/test/path")
                assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_get_json_raises_on_invalid_json(self):
        """Test get_json raises AxisDeviceError on invalid JSON."""
        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.json.side_effect = ValueError("Invalid JSON")
            mock_get.return_value = mock_response

            client = VapixClient("192.168.1.10", "admin", "password")
            async with client:
                with pytest.raises(AxisDeviceError, match="Invalid JSON"):
                    await client.get_json("/test/path")

    @pytest.mark.asyncio
    async def test_get_raw_returns_bytes(self):
        """Test get_raw returns raw bytes."""
        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.content = b"raw binary data"
            mock_get.return_value = mock_response

            client = VapixClient("192.168.1.10", "admin", "password")
            async with client:
                result = await client.get_raw("/test/path")
                assert result == b"raw binary data"


class TestVapixClientPost:
    """Tests for POST request methods."""

    @pytest.mark.asyncio
    async def test_post_returns_response(self):
        """Test post method returns response."""
        with patch.object(httpx.AsyncClient, "post") as mock_post:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            client = VapixClient("192.168.1.10", "admin", "password")
            async with client:
                response = await client.post("/test/path", data={"key": "value"})
                assert response == mock_response

    @pytest.mark.asyncio
    async def test_post_raises_connection_error_on_connect_error(self):
        """Test post raises AxisConnectionError on connect error."""
        with patch.object(httpx.AsyncClient, "post") as mock_post:
            mock_post.side_effect = httpx.ConnectError("Connection refused")

            client = VapixClient("192.168.1.10", "admin", "password")
            async with client:
                with pytest.raises(AxisConnectionError, match="Failed to connect"):
                    await client.post("/test/path")

    @pytest.mark.asyncio
    async def test_post_json_parses_response(self):
        """Test post_json parses JSON response."""
        with patch.object(httpx.AsyncClient, "post") as mock_post:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "ok"}
            mock_post.return_value = mock_response

            client = VapixClient("192.168.1.10", "admin", "password")
            async with client:
                result = await client.post_json("/test/path", json_data={"input": "test"})
                assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_post_json_raises_on_invalid_json(self):
        """Test post_json raises AxisDeviceError on invalid JSON."""
        with patch.object(httpx.AsyncClient, "post") as mock_post:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.json.side_effect = ValueError("Invalid JSON")
            mock_post.return_value = mock_response

            client = VapixClient("192.168.1.10", "admin", "password")
            async with client:
                with pytest.raises(AxisDeviceError, match="Invalid JSON"):
                    await client.post_json("/test/path")


class TestVapixClientDiscoverApis:
    """Tests for discover_apis method."""

    @pytest.mark.asyncio
    async def test_discover_apis_returns_dict(self):
        """Test discover_apis returns API dictionary."""
        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "basic-device-info": {"v2": {"state": "beta"}},
                "param": {"v2": {"state": "beta"}},
            }
            mock_get.return_value = mock_response

            client = VapixClient("192.168.1.10", "admin", "password")
            async with client:
                result = await client.discover_apis()
                assert "basic-device-info" in result
                assert "param" in result

    @pytest.mark.asyncio
    async def test_discover_apis_returns_empty_on_error(self):
        """Test discover_apis returns empty dict on error."""
        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 404
            mock_response.text = "Not Found"
            mock_get.return_value = mock_response

            client = VapixClient("192.168.1.10", "admin", "password")
            async with client:
                result = await client.discover_apis()
                assert result == {}


class TestVapixClientCheckConnectivity:
    """Tests for check_connectivity method."""

    @pytest.mark.asyncio
    async def test_check_connectivity_returns_true(self):
        """Test check_connectivity returns True when accessible."""
        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            client = VapixClient("192.168.1.10", "admin", "password")
            async with client:
                result = await client.check_connectivity()
                assert result is True

    @pytest.mark.asyncio
    async def test_check_connectivity_returns_false_on_connection_error(self):
        """Test check_connectivity returns False on connection error."""
        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_get.side_effect = httpx.ConnectError("Connection refused")

            client = VapixClient("192.168.1.10", "admin", "password")
            async with client:
                result = await client.check_connectivity()
                assert result is False

    @pytest.mark.asyncio
    async def test_check_connectivity_returns_false_on_auth_error(self):
        """Test check_connectivity returns False on auth error."""
        with patch.object(httpx.AsyncClient, "get") as mock_get:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = 401
            mock_get.return_value = mock_response

            client = VapixClient("192.168.1.10", "admin", "password")
            async with client:
                result = await client.check_connectivity()
                assert result is False
