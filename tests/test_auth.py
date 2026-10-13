"""Tests for VapixAuth: the client follows the device's WWW-Authenticate challenge.

Modelled on real devices seen on 2026-10-13: an AXIS OS 12.11 camera with
``Network.HTTP.AuthenticationPolicy=recommended`` offers only ``Basic`` on
HTTPS and rejects Digest; an AXIS OS 11.11 speaker offers only ``Digest``.
A fixed client-side choice fails on one or the other.
"""

import base64

import httpx
import pytest
import respx

from axis_cam.auth import AuthMode, VapixAuth, offered_schemes
from axis_cam.client import VapixClient
from axis_cam.exceptions import AxisAuthenticationError

HOST = "192.168.1.10"
URL = f"https://{HOST}:443/axis-cgi/basicdeviceinfo.cgi"
HTTP_URL = f"http://{HOST}:80/axis-cgi/basicdeviceinfo.cgi"
BASIC_OK = "Basic " + base64.b64encode(b"root:pw").decode()
DIGEST_CHALLENGE = 'Digest realm="AXIS_B8A44F", nonce="abc123", algorithm=MD5, qop="auth"'


def basic_only_device(request: httpx.Request) -> httpx.Response:
    """A camera on policy 'recommended': Basic over HTTPS, nothing else."""
    if request.headers.get("Authorization") == BASIC_OK:
        return httpx.Response(200, json={"ok": True})
    return httpx.Response(401, headers={"WWW-Authenticate": 'Basic realm="AXIS_B8A44F"'})


def digest_only_device(request: httpx.Request) -> httpx.Response:
    """A speaker on 11.x: Digest only."""
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Digest ") and 'username="root"' in authorization:
        return httpx.Response(200, json={"ok": True})
    return httpx.Response(401, headers={"WWW-Authenticate": DIGEST_CHALLENGE})


def both_device(request: httpx.Request) -> httpx.Response:
    authorization = request.headers.get("Authorization", "")
    if authorization == BASIC_OK or authorization.startswith("Digest "):
        return httpx.Response(200, json={"ok": True})
    return httpx.Response(
        401,
        headers=[("WWW-Authenticate", 'Basic realm="x"'), ("WWW-Authenticate", DIGEST_CHALLENGE)],
    )


def wrong_password_device(request: httpx.Request) -> httpx.Response:
    return httpx.Response(401, headers={"WWW-Authenticate": 'Basic realm="AXIS_B8A44F"'})


async def _get(client_kwargs: dict, url_path="/axis-cgi/basicdeviceinfo.cgi"):
    async with VapixClient(HOST, "root", "pw", **client_kwargs) as client:
        response = await client.get(url_path)
        return response, client.auth_scheme


class TestOfferedSchemes:
    def test_parses_multiple_headers_case_insensitively(self):
        response = httpx.Response(
            401,
            headers=[
                ("WWW-Authenticate", 'BASIC realm="x"'),
                ("WWW-Authenticate", DIGEST_CHALLENGE),
            ],
        )
        assert offered_schemes(response) == {"basic", "digest"}

    def test_no_header(self):
        assert offered_schemes(httpx.Response(401)) == set()


class TestAutoOverHttps:
    @respx.mock
    async def test_basic_only_camera_authenticates_first_time(self):
        route = respx.get(URL).mock(side_effect=basic_only_device)

        response, scheme = await _get({"port": 443, "use_https": True})

        assert response.status_code == 200 and scheme == "basic"
        assert route.call_count == 1  # Basic was the first choice over HTTPS

    @respx.mock
    async def test_digest_only_speaker_switches_after_the_challenge(self):
        route = respx.get(URL).mock(side_effect=digest_only_device)

        response, scheme = await _get({"port": 443, "use_https": True})

        assert response.status_code == 200 and scheme == "digest"
        # Basic attempt (401) -> Digest first leg (401 challenge) -> Digest answer (200)
        assert route.call_count == 3

    @respx.mock
    async def test_choice_is_remembered_for_the_session(self):
        route = respx.get(URL).mock(side_effect=digest_only_device)

        async with VapixClient(HOST, "root", "pw", port=443, use_https=True) as client:
            await client.get("/axis-cgi/basicdeviceinfo.cgi")
            calls_after_first = route.call_count
            await client.get("/axis-cgi/basicdeviceinfo.cgi")

        # Second request: no Basic probe again. httpx's DigestAuth reuses the cached
        # challenge, so the very first call already carries a Digest header.
        later_calls = route.calls[calls_after_first:]
        assert len(later_calls) == 1
        assert later_calls[0].request.headers["Authorization"].startswith("Digest ")

    @respx.mock
    async def test_wrong_password_is_a_genuine_401_not_a_loop(self):
        route = respx.get(URL).mock(side_effect=wrong_password_device)

        with pytest.raises(AxisAuthenticationError):
            await _get({"port": 443, "use_https": True})
        assert route.call_count == 1  # same scheme offered back: no retry

    @respx.mock
    async def test_device_offering_both_uses_basic_over_https(self):
        respx.get(URL).mock(side_effect=both_device)

        response, scheme = await _get({"port": 443, "use_https": True})

        assert response.status_code == 200 and scheme == "basic"


class TestAutoOverPlainHttp:
    @respx.mock
    async def test_digest_is_the_first_choice(self):
        route = respx.get(HTTP_URL).mock(side_effect=digest_only_device)

        response, scheme = await _get({"port": 80, "use_https": False})

        assert response.status_code == 200 and scheme == "digest"
        assert route.call_count == 2  # challenge + answer, no Basic probe

    @respx.mock
    async def test_never_falls_back_to_basic_in_cleartext(self):
        route = respx.get(HTTP_URL).mock(side_effect=basic_only_device)

        with pytest.raises(AxisAuthenticationError):
            await _get({"port": 80, "use_https": False})
        assert all(
            not call.request.headers.get("Authorization", "").startswith("Basic ")
            for call in route.calls
        )

    @respx.mock
    async def test_falls_back_to_basic_only_when_explicitly_allowed(self):
        respx.get(HTTP_URL).mock(side_effect=basic_only_device)

        response, scheme = await _get(
            {"port": 80, "use_https": False, "allow_insecure_basic": True}
        )

        assert response.status_code == 200 and scheme == "basic"


class TestForcedModes:
    @respx.mock
    async def test_forced_digest_against_a_basic_only_device_fails_cleanly(self):
        route = respx.get(URL).mock(side_effect=basic_only_device)

        with pytest.raises(AxisAuthenticationError):
            await _get({"port": 443, "use_https": True, "auth_mode": "digest"})
        assert route.call_count == 1

    @respx.mock
    async def test_forced_basic_against_a_digest_only_device_fails_cleanly(self):
        route = respx.get(URL).mock(side_effect=digest_only_device)

        with pytest.raises(AxisAuthenticationError):
            await _get({"port": 443, "use_https": True, "auth_mode": AuthMode.BASIC})
        assert route.call_count == 1

    def test_mode_accepts_strings(self):
        client = VapixClient(HOST, "root", "pw", auth_mode="DIGEST".lower())
        assert client.auth_mode is AuthMode.DIGEST
        with pytest.raises(ValueError):
            VapixClient(HOST, "root", "pw", auth_mode="ntlm")

    def test_scheme_is_none_before_any_request(self):
        auth = VapixAuth("u", "p")
        assert auth.scheme is None


class TestSettlingNeedsSuccess:
    """A 404 before any 401 must not lock the scheme in (the C1410 speaker case)."""

    @respx.mock
    async def test_404_then_digest_challenge_still_switches(self):
        def speaker(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("auditlog.cgi"):
                return httpx.Response(404, text="Not Found")  # no such CGI on 11.x
            return digest_only_device(request)

        respx.route(host=HOST).mock(side_effect=speaker)

        async with VapixClient(HOST, "root", "pw", port=443, use_https=True) as client:
            with pytest.raises(Exception):  # noqa: B017 - any AxisError for the 404 is fine here
                await client.get("/axis-cgi/auditlog.cgi")
            assert client.auth_scheme is None  # 404 proved nothing
            response = await client.get("/axis-cgi/serverreport.cgi")

        assert response.status_code == 200 and client.auth_scheme == "digest"

    @respx.mock
    async def test_settled_scheme_is_reconsidered_when_a_later_401_offers_only_the_other(self):
        calls = {"n": 0}

        def device(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] <= 1:
                return basic_only_device(request)  # first CGI: Basic works
            return digest_only_device(request)  # a different CGI insists on Digest

        respx.route(host=HOST).mock(side_effect=device)

        async with VapixClient(HOST, "root", "pw", port=443, use_https=True) as client:
            await client.get("/axis-cgi/a.cgi")
            assert client.auth_scheme == "basic"
            response = await client.get("/axis-cgi/b.cgi")

        assert response.status_code == 200 and client.auth_scheme == "digest"
