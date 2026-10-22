"""Tests for the users module (pwdgrp.cgi), the first write surface."""

import urllib.parse
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from axis_cam.api.users import (
    UsersAPI,
    parse_account_list,
    validate_password,
    validate_username,
)
from axis_cam.client import VapixClient
from axis_cam.exceptions import AxisDeviceError, AxisLockoutError, AxisUserError
from axis_cam.models import UserAccount, UserAccounts, UserRole, role_to_sgrp

# The response body documented in VAPIX System settings, example 5.
DOC_EXAMPLE = """admin="root,joe"
operator="root,joe,ellen"
viewer="root,joe,ellen,frank"
ptz="root,joe,ellen"
digusers="root,joe,ellen,frank"
"""


def _listing(*accounts: tuple[str, str | None, bool]) -> str:
    """Build an action=get body from (username, role, ptz) tuples."""
    groups: dict[str, list[str]] = {"admin": [], "operator": [], "viewer": [], "ptz": []}
    names = []
    for name, role, ptz in accounts:
        names.append(name)
        if role == "admin":
            groups["admin"].append(name)
        if role in ("admin", "operator"):
            groups["operator"].append(name)
        if role in ("admin", "operator", "viewer"):
            groups["viewer"].append(name)
        if ptz:
            groups["ptz"].append(name)
    lines = [f'{g}="{",".join(m)}"' for g, m in groups.items()]
    lines.append(f'digusers="{",".join(names)}"')
    return "\n".join(lines) + "\n"


def _api(listings: list[str], *, username: str = "root", replies: list[str] | None = None):
    """UsersAPI over a stub client: successive GET bodies, successive POST bodies."""
    client = MagicMock()
    client.host = "192.168.1.10"
    client.username = username
    client.get = AsyncMock(side_effect=[MagicMock(text=body) for body in listings])
    client.post = AsyncMock(side_effect=[MagicMock(text=body) for body in (replies or [])])
    return UsersAPI(client), client


def _posted(client) -> list[dict]:
    return [call.kwargs["data"] for call in client.post.await_args_list]


class TestRoleMapping:
    @pytest.mark.parametrize(
        ("role", "ptz", "sgrp"),
        [
            (UserRole.VIEWER, False, "viewer"),
            (UserRole.VIEWER, True, "viewer:ptz"),
            (UserRole.OPERATOR, False, "operator:viewer"),
            (UserRole.OPERATOR, True, "operator:viewer:ptz"),
            (UserRole.ADMIN, False, "admin:operator:viewer"),
            (UserRole.ADMIN, True, "admin:operator:viewer:ptz"),
        ],
    )
    def test_the_six_documented_sgrp_values(self, role, ptz, sgrp):
        assert role_to_sgrp(role, ptz) == sgrp
        assert UserAccount(username="x", role=role, ptz=ptz).sgrp == sgrp


class TestParseAccountList:
    def test_documented_example(self):
        accounts = parse_account_list(DOC_EXAMPLE)

        assert [a.username for a in accounts.accounts] == ["root", "joe", "ellen", "frank"]
        assert accounts.get("joe") == UserAccount(username="joe", role=UserRole.ADMIN, ptz=True)
        assert accounts.get("ellen") == UserAccount(
            username="ellen", role=UserRole.OPERATOR, ptz=True
        )
        assert accounts.get("frank") == UserAccount(username="frank", role=UserRole.VIEWER)
        assert [a.username for a in accounts.admins] == ["root", "joe"]

    def test_without_digusers_falls_back_to_union_of_groups(self):
        accounts = parse_account_list('admin="root"\nviewer="root,guest"\n')

        assert [a.username for a in accounts.accounts] == ["root", "guest"]
        assert accounts.get("guest") == UserAccount(username="guest", role=UserRole.VIEWER)

    def test_account_in_no_access_group_has_no_role(self):
        accounts = parse_account_list('viewer=""\ndigusers="ghost"\n')

        assert accounts.get("ghost") == UserAccount(username="ghost", role=None, ptz=False)

    def test_empty_body_is_no_accounts(self):
        assert parse_account_list("") == UserAccounts()

    def test_error_body_raises(self):
        with pytest.raises(AxisUserError, match="refused to list accounts"):
            parse_account_list("Error: consult the system log file.\n")


class TestValidation:
    @pytest.mark.parametrize("name", ["", "a" * 15, "with-dash", "sp ace", "ünïcode", "a.b"])
    def test_bad_usernames(self, name):
        with pytest.raises(ValueError, match="invalid user name"):
            validate_username(name)

    @pytest.mark.parametrize("name", ["a", "root", "A1b2C3", "x" * 14])
    def test_good_usernames(self, name):
        validate_username(name)

    def test_password_length(self):
        with pytest.raises(ValueError, match="1-64"):
            validate_password("")
        with pytest.raises(ValueError, match="1-64"):
            validate_password("p" * 65)
        validate_password("p" * 64)

    def test_strict_rejects_non_printable_ascii_only_in_strict_mode(self):
        with pytest.raises(ValueError, match="printable ASCII"):
            validate_password("pässword")
        validate_password("pässword", strict=False)
        validate_password(" ~!@#$%^&*()_+ ")  # 0x20 and 0x7E are allowed

    async def test_add_validates_before_any_request(self):
        api, client = _api([])
        with pytest.raises(ValueError):
            await api.add("bad name", "pw", UserRole.VIEWER)
        with pytest.raises(ValueError):
            await api.add("good", "", UserRole.VIEWER)
        client.get.assert_not_awaited()
        client.post.assert_not_awaited()


class TestListAndRead:
    async def test_list_requests_action_get(self):
        api, client = _api([DOC_EXAMPLE])

        accounts = await api.list()

        client.get.assert_awaited_once_with("/axis-cgi/pwdgrp.cgi", {"action": "get"})
        assert len(accounts.accounts) == 4

    async def test_read_is_the_resource_protocol(self):
        api, _ = _api([DOC_EXAMPLE])
        assert (await api.read()) == parse_account_list(DOC_EXAMPLE)


class TestAdd:
    async def test_posts_form_data_then_verifies(self):
        api, client = _api(
            [
                _listing(("root", "admin", True)),
                _listing(("root", "admin", True), ("ops", "operator", False)),
            ],
            replies=["Created account ops."],
        )

        account = await api.add("ops", "S3cret-pass", UserRole.OPERATOR, comment="Ops team")

        assert _posted(client) == [
            {
                "action": "add",
                "user": "ops",
                "pwd": "S3cret-pass",
                "grp": "users",
                "sgrp": "operator:viewer",
                "comment": "Ops team",
                "strict_pwd": "1",
            }
        ]
        assert account == UserAccount(username="ops", role=UserRole.OPERATOR, ptz=False)

    async def test_strict_password_can_be_disabled(self):
        api, client = _api(
            [
                _listing(("root", "admin", True)),
                _listing(("root", "admin", True), ("v", "viewer", True)),
            ],
            replies=["Created account v."],
        )

        await api.add("v", "pässword", UserRole.VIEWER, ptz=True, strict_password=False)

        posted = _posted(client)[0]
        assert "strict_pwd" not in posted and posted["sgrp"] == "viewer:ptz"

    async def test_existing_account_is_refused_before_writing(self):
        api, client = _api([DOC_EXAMPLE])

        with pytest.raises(AxisUserError, match="already exists"):
            await api.add("joe", "pw", UserRole.VIEWER)
        client.post.assert_not_awaited()

    @pytest.mark.parametrize(
        ("body", "expect"),
        [
            ("Error: invalid password.", "passphrase policy"),
            ("Error: account user name.", "1-14 characters"),
            ("Error: consult the system log file.", "axiscam logs system"),
            ("Error: malformed action operation, add.", "malformed action operation"),
        ],
    )
    async def test_200_error_bodies_raise(self, body, expect):
        api, _ = _api([_listing(("root", "admin", True))], replies=[body])

        with pytest.raises(AxisUserError, match=expect):
            await api.add("ops", "pw", UserRole.VIEWER)

    async def test_acknowledged_but_missing_afterwards_raises(self):
        api, _ = _api(
            [_listing(("root", "admin", True)), _listing(("root", "admin", True))],
            replies=["Created account ops."],
        )

        with pytest.raises(AxisUserError, match="not listed"):
            await api.add("ops", "pw", UserRole.VIEWER)

    async def test_wrong_role_afterwards_raises(self):
        api, _ = _api(
            [
                _listing(("root", "admin", True)),
                _listing(("root", "admin", True), ("ops", "viewer", False)),
            ],
            replies=["Created account ops."],
        )

        with pytest.raises(AxisUserError, match=r"has role viewer .* expected operator"):
            await api.add("ops", "pw", UserRole.OPERATOR)


class TestSetPassword:
    async def test_posts_update_with_pwd(self):
        api, client = _api([DOC_EXAMPLE], replies=["Modified account joe."])

        await api.set_password("joe", "N3w-pass")

        assert _posted(client) == [
            {"action": "update", "user": "joe", "pwd": "N3w-pass", "strict_pwd": "1"}
        ]

    async def test_unknown_account_is_refused_before_writing(self):
        api, client = _api([DOC_EXAMPLE])

        with pytest.raises(AxisUserError, match="does not exist"):
            await api.set_password("nobody", "pw")
        client.post.assert_not_awaited()

    async def test_device_rejection_raises(self):
        api, _ = _api([DOC_EXAMPLE], replies=["Error: invalid password."])

        with pytest.raises(AxisUserError, match="change the password of account 'joe'"):
            await api.set_password("joe", "short")


class TestSetRole:
    async def test_posts_sgrp_and_verifies(self):
        api, client = _api(
            [DOC_EXAMPLE, _listing(("root", "admin", True), ("frank", "operator", True))],
            replies=["Modified account frank."],
        )

        account = await api.set_role("frank", UserRole.OPERATOR, ptz=True)

        assert _posted(client) == [
            {"action": "update", "user": "frank", "sgrp": "operator:viewer:ptz"}
        ]
        assert account.role is UserRole.OPERATOR and account.ptz is True

    async def test_role_unchanged_afterwards_raises(self):
        api, _ = _api([DOC_EXAMPLE, DOC_EXAMPLE], replies=["Modified account frank."])

        with pytest.raises(AxisUserError, match=r"has role viewer .* expected operator"):
            await api.set_role("frank", UserRole.OPERATOR)


class TestLockoutGuard:
    async def test_cannot_remove_self(self):
        api, client = _api([DOC_EXAMPLE], username="joe")

        with pytest.raises(AxisLockoutError, match="authenticated as"):
            await api.remove("joe")
        client.post.assert_not_awaited()

    async def test_cannot_remove_self_even_as_viewer(self):
        api, client = _api([DOC_EXAMPLE], username="frank")

        with pytest.raises(AxisLockoutError, match="authenticated as"):
            await api.remove("frank")
        client.post.assert_not_awaited()

    async def test_allow_lockout_permits_removing_self_when_another_admin_remains(self):
        api, client = _api(
            [DOC_EXAMPLE, _listing(("root", "admin", True), ("ellen", "operator", True))],
            username="joe",
            replies=["Removed account joe."],
        )

        await api.remove("joe", allow_lockout=True)

        assert _posted(client) == [{"action": "remove", "user": "joe"}]

    async def test_cannot_de_admin_self(self):
        api, client = _api([DOC_EXAMPLE], username="joe")

        with pytest.raises(AxisLockoutError, match="lose administrator access"):
            await api.set_role("joe", UserRole.OPERATOR)
        client.post.assert_not_awaited()

    async def test_last_admin_cannot_be_removed_even_with_allow_lockout(self):
        api, client = _api(
            [_listing(("root", "admin", True), ("v", "viewer", False))], username="v"
        )

        with pytest.raises(AxisLockoutError, match="only administrator"):
            await api.remove("root", allow_lockout=True)
        client.post.assert_not_awaited()

    async def test_last_admin_cannot_be_de_admined(self):
        api, client = _api([_listing(("root", "admin", True))], username="other")

        with pytest.raises(AxisLockoutError, match="only administrator"):
            await api.set_role("root", UserRole.VIEWER, allow_lockout=True)
        client.post.assert_not_awaited()

    async def test_removing_another_admin_is_fine_when_one_remains(self):
        api, client = _api(
            [DOC_EXAMPLE, _listing(("root", "admin", True))],
            username="root",
            replies=["Removed account joe."],
        )

        await api.remove("joe")

        assert _posted(client) == [{"action": "remove", "user": "joe"}]


class TestRemove:
    async def test_unknown_account_is_refused(self):
        api, client = _api([DOC_EXAMPLE])

        with pytest.raises(AxisUserError, match="does not exist"):
            await api.remove("nobody")
        client.post.assert_not_awaited()

    async def test_still_present_afterwards_raises(self):
        api, _ = _api([DOC_EXAMPLE, DOC_EXAMPLE], replies=["Removed account frank."])

        with pytest.raises(AxisUserError, match="still listed"):
            await api.remove("frank")


class TestTransport:
    """Through the real VapixClient and httpx: what actually goes on the wire."""

    @respx.mock
    async def test_password_is_in_the_form_body_and_never_in_the_url(self):
        base = "https://192.168.1.10:443"
        listing_before = _listing(("root", "admin", True))
        listing_after = _listing(("root", "admin", True), ("ops", "operator", False))
        get_route = respx.get(f"{base}/axis-cgi/pwdgrp.cgi").mock(
            side_effect=[
                httpx.Response(200, text=listing_before),
                httpx.Response(200, text=listing_after),
            ]
        )
        post_route = respx.post(f"{base}/axis-cgi/pwdgrp.cgi").mock(
            return_value=httpx.Response(200, text="Created account ops.")
        )

        async with VapixClient(
            "192.168.1.10", "root", "rootpw", port=443, use_https=True, auth_mode="basic"
        ) as client:
            await UsersAPI(client).add("ops", "Sup3r-secret", UserRole.OPERATOR)

        assert post_route.call_count == 1
        request = post_route.calls[0].request
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        assert b"pwd=Sup3r-secret" in request.content
        assert request.url.query == b""  # nothing at all in the query string
        assert "Sup3r-secret" not in str(request.url)
        assert get_route.call_count == 2
        for call in get_route.calls:
            assert "Sup3r-secret" not in str(call.request.url)

    NEW_PASSWORD = "N3w Pass/w+rd!"  # pragma: allowlist secret
    #: Both writes that send a ``pwd``: an existing account's new password, a new account.
    OPS = ("set_password", "add")

    async def _against(self, op: str, reply: Callable[[httpx.Request], httpx.Response]):
        base = "https://192.168.1.10:443"
        accounts = [("root", "admin", True)] + ([("ops", "operator", False)] if op != "add" else [])
        respx.get(f"{base}/axis-cgi/pwdgrp.cgi").mock(
            return_value=httpx.Response(200, text=_listing(*accounts))
        )
        respx.post(f"{base}/axis-cgi/pwdgrp.cgi").mock(side_effect=reply)
        async with VapixClient(
            "192.168.1.10", "root", "rootpw", port=443, use_https=True, auth_mode="basic"
        ) as client:
            users = UsersAPI(client)
            if op == "add":
                await users.add("ops", self.NEW_PASSWORD, UserRole.OPERATOR)
            else:
                await users.set_password("ops", self.NEW_PASSWORD)

    def _spellings(self) -> list[str]:
        new = self.NEW_PASSWORD
        return [new, urllib.parse.quote_plus(new), urllib.parse.quote(new, safe="")]

    @pytest.mark.parametrize("op", OPS)
    @respx.mock
    async def test_an_error_page_quoting_the_new_password_is_withheld(self, op: str):
        # F6, related: a peer that quotes the form body (pwd) on a 4xx.
        with pytest.raises(AxisDeviceError, match="withheld") as caught:
            await self._against(
                op,
                lambda request: httpx.Response(400, text=f"bad form: {request.content.decode()}"),
            )
        assert not [s for s in self._spellings() if s in str(caught.value)]

    @pytest.mark.parametrize("op", OPS)
    @respx.mock
    async def test_an_error_reply_quoting_the_new_password_is_withheld(self, op: str):
        # The same echo in the CGI's own 200 "Error" form.
        with pytest.raises(AxisUserError, match="withheld") as caught:
            await self._against(
                op,
                lambda request: httpx.Response(
                    200, text=f"Error: {request.content.decode()} rejected"
                ),
            )
        assert not [s for s in self._spellings() if s in str(caught.value)]

    @respx.mock
    async def test_http_401_is_an_authentication_error_not_a_user_error(self):
        from axis_cam.exceptions import AxisAuthenticationError

        respx.get("https://192.168.1.10:443/axis-cgi/pwdgrp.cgi").mock(
            return_value=httpx.Response(
                401, text="Error: initial admin user must be created first."
            )
        )

        async with VapixClient(
            "192.168.1.10", "root", "pw", port=443, use_https=True, auth_mode="basic"
        ) as client:
            with pytest.raises(AxisAuthenticationError):
                await UsersAPI(client).list()
