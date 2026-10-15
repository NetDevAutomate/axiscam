"""Tests for the ONVIF users module (Device Management SOAP on /vapix/services).

Reply bodies are the ones AXIS OS 12.11.118 returned on 2026-10-13, with the
namespace preamble trimmed to the prefixes the parser needs.
"""

import base64
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from axis_cam.api.onvif_users import (
    SOAP_CONTENT_TYPE,
    OnvifUsersAPI,
    parse_fault,
    parse_get_users,
    soap_envelope,
    user_element,
    validate_onvif_password,
    validate_onvif_username,
)
from axis_cam.client import VapixClient
from axis_cam.exceptions import (
    AxisAuthenticationError,
    AxisEchoError,
    AxisLockoutError,
    AxisPermissionError,
    AxisSoapFault,
    AxisUserError,
)
from axis_cam.models import OnvifAccount, OnvifUserLevel

PREAMBLE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:tds="http://www.onvif.org/ver10/device/wsdl" '
    'xmlns:tt="http://www.onvif.org/ver10/schema" xmlns:ter="http://www.onvif.org/ver10/error">'
)


def _reply(body: str) -> str:
    return f"{PREAMBLE}<SOAP-ENV:Body>{body}</SOAP-ENV:Body></SOAP-ENV:Envelope>"


def _users(*pairs: tuple[str, str]) -> str:
    users = "".join(
        f"<tds:User><tt:Username>{n}</tt:Username><tt:UserLevel>{lvl}</tt:UserLevel></tds:User>"
        for n, lvl in pairs
    )
    return _reply(f"<tds:GetUsersResponse>{users}</tds:GetUsersResponse>")


EMPTY_OK = _reply("<tds:CreateUsersResponse/>")

# Verbatim from the device: DeleteUsers with an unknown name (HTTP 400).
FAULT_USERNAME_MISSING = _reply(
    "<SOAP-ENV:Fault><SOAP-ENV:Code><SOAP-ENV:Value>SOAP-ENV:Sender</SOAP-ENV:Value>"
    "<SOAP-ENV:Subcode><SOAP-ENV:Value>ter:InvalidArgVal</SOAP-ENV:Value>"
    "<SOAP-ENV:Subcode><SOAP-ENV:Value>ter:UsernameMissing</SOAP-ENV:Value></SOAP-ENV:Subcode>"
    "</SOAP-ENV:Subcode></SOAP-ENV:Code>"
    '<SOAP-ENV:Reason><SOAP-ENV:Text xml:lang="en">Username not recognized</SOAP-ENV:Text>'
    "</SOAP-ENV:Reason><SOAP-ENV:Detail><SOAP-ENV:Text>Username not recognized</SOAP-ENV:Text>"
    "</SOAP-ENV:Detail></SOAP-ENV:Fault>"
)
# Verbatim: SetUser without a Password element (HTTP 400) — the live cycle found this.
FAULT_INVALID_ARGS = _reply(
    "<SOAP-ENV:Fault><SOAP-ENV:Code><SOAP-ENV:Value>SOAP-ENV:Sender</SOAP-ENV:Value>"
    "<SOAP-ENV:Subcode><SOAP-ENV:Value>ter:InvalidArgs</SOAP-ENV:Value></SOAP-ENV:Subcode>"
    '</SOAP-ENV:Code><SOAP-ENV:Reason><SOAP-ENV:Text xml:lang="en">Invalid argument'
    "</SOAP-ENV:Text></SOAP-ENV:Reason></SOAP-ENV:Fault>"
)
# Verbatim: an operation the device does not implement (HTTP 500).
FAULT_NOT_SUPPORTED = _reply(
    "<SOAP-ENV:Fault><SOAP-ENV:Code><SOAP-ENV:Value>SOAP-ENV:Receiver</SOAP-ENV:Value>"
    "<SOAP-ENV:Subcode><SOAP-ENV:Value>ter:ActionNotSupported</SOAP-ENV:Value></SOAP-ENV:Subcode>"
    '</SOAP-ENV:Code><SOAP-ENV:Reason><SOAP-ENV:Text xml:lang="en">Optional action not '
    "implemented</SOAP-ENV:Text></SOAP-ENV:Reason></SOAP-ENV:Fault>"
)
# SetUser with a weak password (HTTP 400): the leaf subcode is ter:PasswordTooWeak.
FAULT_PASSWORD_WEAK = _reply(
    "<SOAP-ENV:Fault><SOAP-ENV:Code><SOAP-ENV:Value>SOAP-ENV:Sender</SOAP-ENV:Value>"
    "<SOAP-ENV:Subcode><SOAP-ENV:Value>ter:InvalidArgVal</SOAP-ENV:Value>"
    "<SOAP-ENV:Subcode><SOAP-ENV:Value>ter:PasswordTooWeak</SOAP-ENV:Value></SOAP-ENV:Subcode>"
    "</SOAP-ENV:Subcode></SOAP-ENV:Code>"
    '<SOAP-ENV:Reason><SOAP-ENV:Text xml:lang="en">Too weak</SOAP-ENV:Text>'
    "</SOAP-ENV:Reason></SOAP-ENV:Fault>"
)


def _response(body: str, status: int = 200) -> MagicMock:
    return MagicMock(status_code=status, text=body)


def _api(replies: list[MagicMock]) -> tuple[OnvifUsersAPI, MagicMock]:
    client = MagicMock()
    client.host = "192.168.1.10"
    client.post_raw = AsyncMock(side_effect=replies)
    return OnvifUsersAPI(client), client


def _sent(client: MagicMock, index: int) -> str:
    return client.post_raw.await_args_list[index].args[1]


class TestEnvelope:
    def test_envelope_and_user_element(self):
        user = user_element("vms", OnvifUserLevel.OPERATOR, "p&w<d")
        xml = soap_envelope(f"<tds:CreateUsers>{user}</tds:CreateUsers>")
        assert xml.startswith('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"')
        assert "<tt:Username>vms</tt:Username>" in xml
        assert "<tt:Password>p&amp;w&lt;d</tt:Password>" in xml  # escaped, never raw
        assert "<tt:UserLevel>Operator</tt:UserLevel>" in xml

    def test_user_element_always_carries_a_password(self):
        # Axis answers ter:InvalidArgs to a SetUser without one (live, 12.11.118).
        assert "<tt:Password>pw</tt:Password>" in user_element("vms", OnvifUserLevel.USER, "pw")

    def test_username_validation(self):
        validate_onvif_username("vms-01")
        for bad in ("", "a" * 65, "with space", "x<y", "a&b"):
            with pytest.raises(ValueError):
                validate_onvif_username(bad)

    def test_password_validation(self):
        validate_onvif_password("ok-password")
        with pytest.raises(ValueError):
            validate_onvif_password("")
        with pytest.raises(ValueError):
            validate_onvif_password("x" * 65)


class TestParsing:
    def test_get_users_from_the_device_body(self):
        accounts = parse_get_users(_users(("onvif", "Administrator"), ("vms", "User")))

        assert accounts.accounts == [
            OnvifAccount(username="onvif", level=OnvifUserLevel.ADMINISTRATOR),
            OnvifAccount(username="vms", level=OnvifUserLevel.USER),
        ]
        assert accounts.get("vms") is not None and len(accounts.administrators) == 1

    def test_empty_list_is_no_users(self):
        assert parse_get_users(_users()).accounts == []

    def test_unknown_level_is_kept_as_extended(self):
        accounts = parse_get_users(_users(("x", "SomethingNew")))
        assert accounts.accounts[0].level is OnvifUserLevel.EXTENDED

    def test_fault_decoding(self):
        fault = parse_fault(FAULT_USERNAME_MISSING, 400)

        assert isinstance(fault, AxisSoapFault)
        assert fault.code == "SOAP-ENV:Sender"
        assert fault.subcodes == ["ter:InvalidArgVal", "ter:UsernameMissing"]
        assert fault.reason == "Username not recognized"
        assert "no user with that name" in str(fault) and "ter:UsernameMissing" in str(fault)

    def test_fault_without_known_meaning(self):
        fault = parse_fault(FAULT_NOT_SUPPORTED, 500)
        assert fault is not None and "does not implement" in str(fault)

    def test_invalid_args_fault(self):
        fault = parse_fault(FAULT_INVALID_ARGS, 400)
        assert fault is not None and fault.subcodes == ["ter:InvalidArgs"]
        assert "missing or malformed" in str(fault)

    def test_non_fault_bodies_are_not_faults(self):
        assert parse_fault(_users(), 200) is None
        assert parse_fault("<html>login</html>", 401) is None


class TestList:
    async def test_list_posts_get_users_and_parses(self):
        api, client = _api([_response(_users(("onvif", "Operator")))])

        accounts = await api.list()

        client.post_raw.assert_awaited_once()
        path, body = client.post_raw.await_args.args
        assert path == "/vapix/services" and "<tds:GetUsers/>" in body
        assert client.post_raw.await_args.kwargs == {"content_type": SOAP_CONTENT_TYPE}
        assert [(a.username, a.level) for a in accounts.accounts] == [
            ("onvif", OnvifUserLevel.OPERATOR)
        ]

    async def test_auth_error_propagates(self):
        api, _ = _api([AxisAuthenticationError("401")])
        with pytest.raises(AxisAuthenticationError):
            await api.list()


class TestAdd:
    async def test_add_creates_and_verifies(self):
        api, client = _api(
            [
                _response(_users(("onvif", "Administrator"))),
                _response(EMPTY_OK),
                _response(_users(("onvif", "Administrator"), ("vms", "Operator"))),
            ]
        )

        created = await api.add("vms", "Str0ng-pass", OnvifUserLevel.OPERATOR)

        assert created == OnvifAccount(username="vms", level=OnvifUserLevel.OPERATOR)
        sent = _sent(client, 1)
        assert "<tds:CreateUsers>" in sent and "<tt:Password>Str0ng-pass</tt:Password>" in sent

    async def test_add_refuses_an_existing_name_before_writing(self):
        api, client = _api([_response(_users(("vms", "User")))])
        with pytest.raises(AxisUserError, match="already exists"):
            await api.add("vms", "Str0ng-pass", OnvifUserLevel.USER)
        assert client.post_raw.await_count == 1  # the list only

    async def test_add_refuses_anonymous_level(self):
        api, client = _api([])
        with pytest.raises(ValueError, match="Anonymous"):
            await api.add("vms", "Str0ng-pass", OnvifUserLevel.ANONYMOUS)
        client.post_raw.assert_not_awaited()

    async def test_device_fault_is_raised_with_its_meaning(self):
        api, _ = _api([_response(_users()), _response(FAULT_USERNAME_MISSING, 400)])
        with pytest.raises(AxisSoapFault, match="no user with that name"):
            await api.add("vms", "Str0ng-pass", OnvifUserLevel.USER)

    async def test_error_status_without_a_fault_body(self):
        api, _ = _api([_response(_users()), _response("<html>oops</html>", 500)])
        with pytest.raises(AxisUserError, match="without a SOAP fault"):
            await api.add("vms", "Str0ng-pass", OnvifUserLevel.USER)

    async def test_acknowledged_but_missing_afterwards(self):
        api, _ = _api([_response(_users()), _response(EMPTY_OK), _response(_users())])
        with pytest.raises(AxisUserError, match="not listed"):
            await api.add("vms", "Str0ng-pass", OnvifUserLevel.USER)

    async def test_acknowledged_with_wrong_level(self):
        api, _ = _api(
            [_response(_users()), _response(EMPTY_OK), _response(_users(("vms", "User")))]
        )
        with pytest.raises(AxisUserError, match="has level User; expected Operator"):
            await api.add("vms", "Str0ng-pass", OnvifUserLevel.OPERATOR)


class TestSetPassword:
    async def test_set_password_sends_current_level_and_new_password(self):
        api, client = _api([_response(_users(("vms", "Operator"))), _response(EMPTY_OK)])

        await api.set_password("vms", "N3w-pass")

        sent = _sent(client, 1)
        assert "<tds:SetUser>" in sent
        assert "<tt:Password>N3w-pass</tt:Password>" in sent
        assert "<tt:UserLevel>Operator</tt:UserLevel>" in sent

    async def test_unknown_user(self):
        api, _ = _api([_response(_users())])
        with pytest.raises(AxisUserError, match="does not exist"):
            await api.set_password("vms", "N3w-pass")


class TestSetLevel:
    async def test_set_level_sends_level_and_password_and_verifies(self):
        api, client = _api(
            [
                _response(_users(("onvif", "Administrator"), ("vms", "User"))),
                _response(EMPTY_OK),
                _response(_users(("onvif", "Administrator"), ("vms", "Operator"))),
            ]
        )

        updated = await api.set_level("vms", OnvifUserLevel.OPERATOR, "Keep-pass")

        assert updated.level is OnvifUserLevel.OPERATOR
        sent = _sent(client, 1)
        assert "<tds:SetUser>" in sent
        assert "<tt:Password>Keep-pass</tt:Password>" in sent
        assert "<tt:UserLevel>Operator</tt:UserLevel>" in sent

    async def test_set_level_without_password_is_what_the_device_refuses(self):
        # Simulate the real reply to a password-less SetUser so the meaning is checked end to end.
        api, _ = _api([_response(_users(("vms", "User"))), _response(FAULT_INVALID_ARGS, 400)])
        with pytest.raises(AxisSoapFault, match="ter:InvalidArgs"):
            await api.set_level("vms", OnvifUserLevel.OPERATOR, "Keep-pass")

    async def test_demoting_the_only_administrator_is_refused(self):
        api, client = _api([_response(_users(("onvif", "Administrator"), ("vms", "User")))])
        with pytest.raises(AxisLockoutError, match="only ONVIF Administrator"):
            await api.set_level("onvif", OnvifUserLevel.USER, "Keep-pass")
        assert client.post_raw.await_count == 1

    async def test_demoting_with_allow_lockout(self):
        api, _ = _api(
            [
                _response(_users(("onvif", "Administrator"))),
                _response(EMPTY_OK),
                _response(_users(("onvif", "User"))),
            ]
        )
        updated = await api.set_level("onvif", OnvifUserLevel.USER, "Keep-pass", allow_lockout=True)
        assert updated.level is OnvifUserLevel.USER

    async def test_demoting_when_another_administrator_exists(self):
        api, _ = _api(
            [
                _response(_users(("a", "Administrator"), ("b", "Administrator"))),
                _response(EMPTY_OK),
                _response(_users(("a", "Operator"), ("b", "Administrator"))),
            ]
        )
        updated = await api.set_level("a", OnvifUserLevel.OPERATOR, "Keep-pass")
        assert updated.level is OnvifUserLevel.OPERATOR

    async def test_empty_password_rejected_before_any_request(self):
        api, client = _api([])
        with pytest.raises(ValueError):
            await api.set_level("vms", OnvifUserLevel.OPERATOR, "")
        client.post_raw.assert_not_awaited()


class TestRemove:
    async def test_remove_deletes_and_verifies(self):
        api, client = _api(
            [
                _response(_users(("onvif", "Administrator"), ("vms", "User"))),
                _response(_reply("<tds:DeleteUsersResponse/>")),
                _response(_users(("onvif", "Administrator"))),
            ]
        )

        await api.remove("vms")

        assert "<tds:DeleteUsers><tds:Username>vms</tds:Username></tds:DeleteUsers>" in _sent(
            client, 1
        )

    async def test_removing_the_only_administrator_is_refused(self):
        api, _ = _api([_response(_users(("onvif", "Administrator")))])
        with pytest.raises(AxisLockoutError, match="only ONVIF Administrator"):
            await api.remove("onvif")

    async def test_still_listed_afterwards(self):
        api, _ = _api(
            [
                _response(_users(("vms", "User"))),
                _response(_reply("<tds:DeleteUsersResponse/>")),
                _response(_users(("vms", "User"))),
            ]
        )
        with pytest.raises(AxisUserError, match="still listed"):
            await api.remove("vms")

    async def test_unknown_user(self):
        api, _ = _api([_response(_users())])
        with pytest.raises(AxisUserError, match="does not exist"):
            await api.remove("vms")


class TestPostRaw:
    """VapixClient.post_raw: raw body, 401/403 raised, other statuses returned."""

    @respx.mock
    async def test_sends_body_and_returns_error_statuses(self):
        route = respx.post("https://192.168.1.10:443/vapix/services").mock(
            return_value=httpx.Response(400, text=FAULT_USERNAME_MISSING)
        )
        client = VapixClient("192.168.1.10", "admin", "pw", use_https=True, port=443)
        async with client:
            response = await client.post_raw(
                "/vapix/services", "<s:Envelope/>", content_type=SOAP_CONTENT_TYPE
            )
        assert response.status_code == 400
        request = route.calls.last.request
        assert request.content == b"<s:Envelope/>"
        assert request.headers["content-type"] == SOAP_CONTENT_TYPE

    @respx.mock
    async def test_401_and_403_still_raise(self):
        respx.post("https://192.168.1.10:443/vapix/services").mock(
            side_effect=[httpx.Response(401), httpx.Response(403)]
        )
        client = VapixClient("192.168.1.10", "admin", "pw", use_https=True, port=443)
        async with client:
            with pytest.raises(AxisAuthenticationError):
                await client.post_raw("/vapix/services", "x", content_type=SOAP_CONTENT_TYPE)
            with pytest.raises(AxisPermissionError):
                await client.post_raw("/vapix/services", "x", content_type=SOAP_CONTENT_TYPE)


ECHO_PASSWORD = "Onvif-Echo-T3st!"  # pragma: allowlist secret
ECHO_TOKEN = base64.b64encode(f"admin:{ECHO_PASSWORD}".encode()).decode()


def _token_fragments_in(text: str) -> list[str]:
    return [
        ECHO_TOKEN[i : i + 8] for i in range(len(ECHO_TOKEN) - 7) if ECHO_TOKEN[i : i + 8] in text
    ]


class TestSentCredentialNeverReachesTheError:
    """A peer that echoes the request headers must not put the credential in an error.

    No Axis device does this; a proxy or a broken or hostile peer can. The client
    sends HTTP Basic, so the echoed header carries the base64 credential. The
    client refuses such a reply before the SOAP layer sees it, whatever its
    status, so neither a fault reason nor an excerpt can quote it.
    """

    @staticmethod
    def _echo(status: int, wrap: Callable[[str], str]) -> Callable[[httpx.Request], httpx.Response]:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, text=wrap(request.headers["Authorization"]))

        return handler

    async def _call(self, handler: Callable[[httpx.Request], httpx.Response]) -> Exception:
        with respx.mock:
            respx.post("https://192.168.1.10:443/vapix/services").mock(side_effect=handler)
            client = VapixClient(
                "192.168.1.10", "admin", ECHO_PASSWORD, use_https=True, port=443, auth_mode="basic"
            )
            async with client:
                with pytest.raises((AxisUserError, AxisSoapFault, AxisEchoError)) as caught:
                    await OnvifUsersAPI(client).list()
        return caught.value

    async def test_a_non_fault_body_cut_across_the_credential(self):
        # Pad so a 200-character snippet would end in the middle of the token.
        pad = "." * (200 - len("Basic ") - len(ECHO_TOKEN) // 2)
        error = await self._call(self._echo(500, lambda auth: pad + auth))
        assert isinstance(error, AxisEchoError)
        assert "quotes this request's credentials" in str(error)
        assert _token_fragments_in(str(error)) == []

    async def test_a_fault_reason_that_echoes_the_credential(self):
        def fault(auth: str) -> str:
            return FAULT_INVALID_ARGS.replace("Invalid argument", f"Invalid argument: {auth}")

        error = await self._call(self._echo(400, fault))
        assert isinstance(error, AxisEchoError)
        assert _token_fragments_in(str(error)) == []

    async def test_a_fault_reason_holding_the_configured_password_is_withheld(self):
        # The plain password is not an echo of the request (data may hold it),
        # but a fault reason that carries it is not quoted. The fault itself --
        # its class and codes -- still reaches the caller.
        def fault(_: str) -> str:
            return FAULT_INVALID_ARGS.replace("Invalid argument", f"bad pwd {ECHO_PASSWORD}")

        error = await self._call(self._echo(400, fault))
        assert isinstance(error, AxisSoapFault)
        assert error.subcodes == ["ter:InvalidArgs"]
        assert ECHO_PASSWORD not in str(error)
        assert ECHO_PASSWORD not in error.reason
        assert "withheld: the reply contains the configured password" in str(error)

    async def test_a_genuine_fault_survives_a_password_that_appears_in_the_envelope(self):
        # Opus F6: "2003" is in the SOAP 1.2 namespace of every reply. The fault
        # quotes only its codes and reason, so nothing needs withholding.
        api, client = _api([_response(FAULT_USERNAME_MISSING, 400)])
        client.password = "2003"  # pragma: allowlist secret
        with pytest.raises(AxisSoapFault) as caught:
            await api.list()
        assert caught.value.subcodes == ["ter:InvalidArgVal", "ter:UsernameMissing"]
        assert "no user with that name" in str(caught.value)

    async def test_a_fault_meaning_survives_a_password_that_is_a_substring_of_a_code(self):
        # Fix-review finding 3: password "Password" is a substring of the subcode
        # ter:PasswordTooWeak. Codes are a controlled vocabulary, so they are
        # quoted verbatim and the fault's meaning is not lost.
        api, client = _api([_response(FAULT_PASSWORD_WEAK, 400)])
        client.password = "Password"  # pragma: allowlist secret
        with pytest.raises(AxisSoapFault) as caught:
            await api.list()
        assert caught.value.subcodes[-1] == "ter:PasswordTooWeak"
        assert "the device rejected the password as too weak" in str(caught.value)
