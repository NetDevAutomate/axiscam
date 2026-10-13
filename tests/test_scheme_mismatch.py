"""Scheme/port mismatches must produce an error that names the fix.

Since Phase 0 the scheme is explicit (``https`` defaults to True) rather than
inferred from the port, so a pre-existing config with ``port: 80`` and no
``https: false`` sends TLS to a plain-HTTP port. OpenSSL reports that as
``WRONG_VERSION_NUMBER``, which tells the user nothing about what to change.
"""

import http.server
import threading
from collections.abc import Iterator
from unittest.mock import patch

import httpx
import pytest
import respx
from typer.testing import CliRunner

from axis_cam.cli import app
from axis_cam.client import VapixClient
from axis_cam.config import AppConfig, DeviceConfig
from axis_cam.exceptions import AxisConnectionError

runner = CliRunner()


class _PlainHttp(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"plain")

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def plain_http_port() -> Iterator[int]:
    """A real plain-HTTP listener on 127.0.0.1 and an ephemeral port."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _PlainHttp)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()


class TestTlsToPlainHttpPort:
    async def test_names_the_remedy(self, plain_http_port):
        async with VapixClient(
            "127.0.0.1", "u", "p", port=plain_http_port, use_https=True, auth_mode="digest"
        ) as client:
            with pytest.raises(AxisConnectionError) as excinfo:
                await client.get("/axis-cgi/basicdeviceinfo.cgi")

        message = str(excinfo.value)
        assert f"127.0.0.1:{plain_http_port} answered plain HTTP to an HTTPS request" in message
        assert "https: false" in message and "port: 443" in message
        assert "WRONG_VERSION_NUMBER" not in message  # the raw OpenSSL text is not the message

    async def test_plain_http_to_the_same_port_works(self, plain_http_port):
        async with VapixClient(
            "127.0.0.1", "u", "p", port=plain_http_port, use_https=False, auth_mode="digest"
        ) as client:
            response = await client.get("/")
        assert response.text == "plain"

    async def test_other_connect_errors_keep_the_generic_message(self):
        # Nothing listens here; a refused connection is not a scheme problem.
        async with VapixClient("127.0.0.1", "u", "p", port=9, use_https=True) as client:
            with pytest.raises(AxisConnectionError, match=r"Failed to connect to 127\.0\.0\.1"):
                await client.get("/")


class TestPlainHttpToTlsPort:
    @respx.mock
    @pytest.mark.parametrize(
        "body",
        [
            "<html>400 Bad Request: You're speaking plain HTTP to an SSL-enabled server port."
            "</html>",
            "<html>400 The plain HTTP request was sent to HTTPS port</html>",
        ],
    )
    async def test_apache_and_nginx_wording(self, body):
        respx.get("http://192.168.1.10:443/axis-cgi/basicdeviceinfo.cgi").mock(
            return_value=httpx.Response(400, text=body)
        )
        async with VapixClient(
            "192.168.1.10", "u", "p", port=443, use_https=False, auth_mode="digest"
        ) as client:
            with pytest.raises(AxisConnectionError, match="expects HTTPS but was sent plain HTTP"):
                await client.get("/axis-cgi/basicdeviceinfo.cgi")

    @respx.mock
    async def test_an_ordinary_400_is_still_a_device_error(self):
        from axis_cam.exceptions import AxisDeviceError

        respx.get("https://192.168.1.10:443/axis-cgi/x.cgi").mock(
            return_value=httpx.Response(400, text="Bad parameter")
        )
        async with VapixClient("192.168.1.10", "u", "p", port=443, use_https=True) as client:
            with pytest.raises(AxisDeviceError, match="Device error 400"):
                await client.get("/axis-cgi/x.cgi")


class TestCliSurface:
    def test_misconfigured_device_gets_one_actionable_line(self, plain_http_port):
        # A config written before Phase 0: port set, https left at its new default.
        cfg = AppConfig(
            devices={
                "cam": DeviceConfig(
                    host="127.0.0.1", username="u", password="p", port=plain_http_port
                )
            }
        )
        with patch("axis_cam.cli.context.load_config", return_value=cfg):
            result = runner.invoke(app, ["info", "--device", "cam"])

        assert result.exit_code == 1
        text = " ".join(result.output.split())
        assert "answered plain HTTP to an HTTPS request" in text
        assert "https: false" in text
        assert "Traceback" not in text
