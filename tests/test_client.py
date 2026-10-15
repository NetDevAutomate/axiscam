"""Tests for VapixClient."""

import base64
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from axis_cam.client import VapixClient
from axis_cam.exceptions import (
    AxisAuthenticationError,
    AxisConnectionError,
    AxisDeviceError,
    AxisEchoError,
    AxisPermissionError,
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


class TestForbiddenIsPermissionError:
    """403 names the API; it is an AxisAuthenticationError subclass so existing
    handlers still catch it, but report/backup can tell it from a 401."""

    @respx.mock
    async def test_403_raises_permission_error_naming_the_path(self):
        from axis_cam.exceptions import AxisAuthenticationError, AxisPermissionError

        respx.get("https://192.168.1.10:443/config/rest/oauth-ccgrant/v1beta").mock(
            return_value=httpx.Response(403, text="Forbidden")
        )
        async with VapixClient("192.168.1.10", "admin", "pw", port=443, use_https=True) as client:
            with pytest.raises(AxisPermissionError, match="oauth-ccgrant") as excinfo:
                await client.get("/config/rest/oauth-ccgrant/v1beta")
        assert isinstance(excinfo.value, AxisAuthenticationError)


class TestEchoRefusal:
    """A reply that quotes the request's credentials is refused, whatever the path."""

    PASSWORD = "Client-Echo~T3st?"  # pragma: allowlist secret

    def _client(self) -> VapixClient:
        return VapixClient(
            "192.0.2.10", "root", self.PASSWORD, port=443, use_https=True, auth_mode="basic"
        )

    @staticmethod
    def _echo(status: int = 200, content_type: str = "text/plain"):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status,
                text=f"seen {request.headers['Authorization']}",
                headers={"Content-Type": content_type},
            )

        return handler

    @respx.mock
    async def test_discovery_does_not_swallow_the_refusal(self):
        # discover_apis turns a device error into "no discovery"; an echo is not one.
        respx.get("https://192.0.2.10:443/config/discover/apis").mock(side_effect=self._echo())
        async with self._client() as client:
            with pytest.raises(AxisEchoError):
                await client.discover_apis()
            assert client._discovery is None  # nothing cached

    @respx.mock
    async def test_an_error_page_that_echoes_is_refused_not_quoted(self):
        respx.get("https://192.0.2.10:443/x").mock(side_effect=self._echo(404, "text/html"))
        async with self._client() as client:
            with pytest.raises(AxisEchoError, match=r"\(HTTP 404\)") as caught:
                await client.get("/x")
        assert "seen" not in str(caught.value)

    @respx.mock
    async def test_a_binary_download_that_says_it_is_text_is_scanned(self):
        respx.get("https://192.0.2.10:443/img").mock(side_effect=self._echo(200, "text/html"))
        async with self._client() as client:
            with pytest.raises(AxisEchoError):
                await client.get_raw("/img")
            with pytest.raises(AxisEchoError):
                await client.get_binary("/img")

    @respx.mock
    async def test_a_binary_download_is_not_scanned(self):
        respx.get("https://192.0.2.10:443/img").mock(
            side_effect=self._echo(200, "application/octet-stream")
        )
        async with self._client() as client:
            assert (await client.get_raw("/img")).startswith(b"seen Basic ")

    async def test_refuse_echo_checks_decoded_text_against_the_configured_token(self):
        client = self._client()
        token = base64.b64encode(f"root:{self.PASSWORD}".encode()).decode()
        client.refuse_echo("ordinary log line")
        with pytest.raises(AxisEchoError):
            client.refuse_echo(f"debug: authorization={token}")


class TestEchoBeyondTheReplyBody:
    """Echoes the reply body alone does not reveal (milestone-3 council).

    An earlier request's Digest hash replayed later, a redirect whose target
    carries the token, and a download labelled as an HTTP message.
    """

    PASSWORD = "Client-Replay~T3st?"  # pragma: allowlist secret
    CHALLENGE = 'Digest realm="probe", nonce="abc123", algorithm=MD5, qop="auth"'

    def _basic(self) -> VapixClient:
        return VapixClient(
            "192.0.2.10", "root", self.PASSWORD, port=443, use_https=True, auth_mode="basic"
        )

    @respx.mock
    async def test_a_reply_that_replays_an_earlier_requests_digest_hash_is_refused(self):
        first: list[str] = []

        def peer(request: httpx.Request) -> httpx.Response:
            authorization = request.headers.get("Authorization", "")
            if not authorization.startswith("Digest "):
                return httpx.Response(401, headers={"WWW-Authenticate": self.CHALLENGE})
            if request.url.path == "/first":
                first.append(authorization)
                return httpx.Response(200, json={"ok": True})
            # The previous request's header, not this one's.
            return httpx.Response(
                200, text=f"last request: {first[0]}", headers={"Content-Type": "text/plain"}
            )

        respx.route(host="192.0.2.10").mock(side_effect=peer)
        async with VapixClient("192.0.2.10", "root", self.PASSWORD, auth_mode="digest") as client:
            await client.get("/first")
            with pytest.raises(AxisEchoError):
                await client.get("/second")

    @respx.mock
    async def test_a_redirect_whose_target_quotes_the_token_is_refused_unfollowed(self):
        token = base64.b64encode(f"root:{self.PASSWORD}".encode()).decode()
        respx.get("https://192.0.2.10:443/start").mock(
            return_value=httpx.Response(302, headers={"Location": f"/r/{token}/x"})
        )
        target = respx.route(path__startswith="/r/").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        async with self._basic() as client:
            with pytest.raises(AxisEchoError) as caught:
                await client.get("/start")
        assert not target.called  # never requested, so never logged
        assert "192.0.2.10" in str(caught.value)  # host named
        assert token[:8] not in str(caught.value)

    @respx.mock
    async def test_messages_name_the_path_the_caller_asked_for(self):
        respx.get("https://192.0.2.10:443/start").mock(
            return_value=httpx.Response(302, headers={"Location": "/elsewhere"})
        )
        respx.get("https://192.0.2.10:443/elsewhere").mock(return_value=httpx.Response(403))
        async with self._basic() as client:
            with pytest.raises(AxisPermissionError) as caught:
                await client.get("/start")
        assert "/start" in str(caught.value)
        assert "/elsewhere" not in str(caught.value)

    @respx.mock
    async def test_a_redirect_whose_target_carries_the_plain_password_is_refused(self):
        # A debug proxy that decodes Basic and redirects to /login?p=<pw>. The
        # plain password is excluded from the echo check for stored data, but a
        # Location is not stored data, so it counts here.
        respx.get("https://192.0.2.10:443/start").mock(
            return_value=httpx.Response(
                302, headers={"Location": f"/login?u=root&p={self.PASSWORD}"}
            )
        )
        target = respx.route(path__startswith="/login").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        async with self._basic() as client:
            with pytest.raises(AxisEchoError) as caught:
                await client.get("/start")
        assert not target.called
        assert self.PASSWORD not in str(caught.value)

    @respx.mock
    async def test_a_redirect_refusal_names_no_peer_chosen_path(self):
        # Two hops: the refusal fires on the second response, whose request path
        # is one the first peer chose. The message names no path, so that
        # peer-chosen path cannot reach it.
        token = base64.b64encode(f"root:{self.PASSWORD}".encode()).decode()
        respx.get("https://192.0.2.10:443/start").mock(
            return_value=httpx.Response(302, headers={"Location": "/peer-chosen-hop"})
        )
        respx.get("https://192.0.2.10:443/peer-chosen-hop").mock(
            return_value=httpx.Response(302, headers={"Location": f"/r/{token}/x"})
        )
        async with self._basic() as client:
            with pytest.raises(AxisEchoError) as caught:
                await client.get("/start")
        assert "peer-chosen-hop" not in str(caught.value)
        assert token[:8] not in str(caught.value)

    @respx.mock
    async def test_a_download_labelled_as_an_http_message_is_scanned(self):
        def peer(request: httpx.Request) -> httpx.Response:
            trace = f"GET /img HTTP/1.1\r\nAuthorization: {request.headers['Authorization']}\r\n"
            return httpx.Response(
                200, content=trace.encode(), headers={"Content-Type": "message/http"}
            )

        respx.get("https://192.0.2.10:443/img").mock(side_effect=peer)
        async with self._basic() as client:
            with pytest.raises(AxisEchoError):
                await client.get_raw("/img")

    @respx.mock
    async def test_connectivity_check_reports_an_echoing_peer_as_unreachable(self):
        def peer(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                text=f"seen {request.headers['Authorization']}",
                headers={"Content-Type": "text/plain"},
            )

        respx.get("https://192.0.2.10:443/axis-cgi/basicdeviceinfo.cgi").mock(side_effect=peer)
        async with self._basic() as client:
            assert await client.check_connectivity() is False
