"""ONVIF user accounts — the device's *second* user database.

Axis keeps ONVIF users apart from VAPIX accounts (``pwdgrp.cgi``): a VMS that
talks ONVIF authenticates against this list, and ``accounts list`` does not
show it. The only management path is the ONVIF Device Management service
(``GetUsers`` / ``CreateUsers`` / ``SetUser`` / ``DeleteUsers``, ONVIF Core
Specification §8.4.3-8.4.6, ``devicemgmt.wsdl``).

Transport, verified on AXIS OS 12.11.118 and 11.11.192 on 2026-10-13:

- ``POST /vapix/services`` accepts the ONVIF operations and authenticates with
  the device's ordinary HTTP authentication — the same ``VapixAuth`` the rest
  of the client uses, so an administrator's VAPIX credentials manage ONVIF
  users. ``/onvif/device_service`` is the ONVIF-proper endpoint: it demands
  HTTP Digest and rejects the VAPIX administrator even with Digest (it wants an
  ONVIF user), so it is of no use for administering the list from the outside.
- A fault is HTTP 400 (``env:Sender``) or 500 (``env:Receiver``) with a SOAP
  1.2 ``Fault`` body whose nested ``Subcode`` values are the ONVIF error codes
  (``ter:InvalidArgVal`` / ``ter:UsernameMissing`` for an unknown name).
- ``GetUsers`` never returns passwords (the specification forbids it), so a
  password change is acknowledged, not read back; create/level/delete are
  verified by re-reading the list.
- ``SetUser`` **must carry a** ``Password``: without one the device answers
  HTTP 400 ``ter:InvalidArgs`` (live, 12.11.118). The specification lets a
  device treat a missing password as "clear it"; Axis refuses instead. So a
  level change needs the user's password — the current one to keep ONVIF
  clients working, or a new one to rotate it in the same step.

Requests are built from a fixed template with escaped values and parsed with
defusedxml; no SOAP library is involved.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING, ClassVar

from defusedxml import ElementTree as DefusedElementTree

from axis_cam.api.base import BaseAPI
from axis_cam.api.registry import register
from axis_cam.exceptions import AxisLockoutError, AxisSoapFault, AxisUserError
from axis_cam.models import OnvifAccount, OnvifAccounts, OnvifUserLevel
from axis_cam.secrets import error_excerpt

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

    import httpx

SOAP_ENV = "http://www.w3.org/2003/05/soap-envelope"
ONVIF_DEVICE = "http://www.onvif.org/ver10/device/wsdl"
ONVIF_SCHEMA = "http://www.onvif.org/ver10/schema"
SOAP_CONTENT_TYPE = "application/soap+xml; charset=utf-8"

_NS = {"s": SOAP_ENV, "tds": ONVIF_DEVICE, "tt": ONVIF_SCHEMA}

#: ONVIF fault subcodes (Core Specification §8.4.4-8.4.6) in plain words.
_FAULT_MEANINGS: dict[str, str] = {
    "ter:UsernameClash": "a user with that name already exists",
    "ter:UsernameMissing": "no user with that name",
    "ter:FixedUser": "the device does not allow changing or deleting that user",
    "ter:Password": "the device rejected the password as too weak",
    "ter:PasswordTooWeak": "the device rejected the password as too weak",
    "ter:PasswordTooLong": "the password is too long",
    "ter:UsernameTooLong": "the user name is too long",
    "ter:UsernameTooShort": "the user name is too short",
    "ter:TooManyUsers": "the device has reached its maximum number of ONVIF users",
    "ter:AnonymousNotAllowed": "the Anonymous level cannot be assigned",
    "ter:InvalidArgs": "a required argument is missing or malformed (a SetUser needs the password)",
    "ter:NotAuthorized": "this account may not manage ONVIF users",
    "ter:ActionNotSupported": "the device does not implement this operation",
}


def validate_onvif_username(username: str) -> None:
    """Reject names the specification or the device cannot take.

    ONVIF leaves the character set to the device; Axis takes the same set as
    VAPIX accounts. Whitespace and the XML-significant characters are refused
    here because they could never be what was meant.
    """
    if not username or len(username) > 64:
        raise ValueError("ONVIF user name must be 1-64 characters")
    if any(c.isspace() for c in username) or any(c in username for c in "<>&\"'"):
        raise ValueError("ONVIF user name may not contain whitespace or < > & \" '")


def validate_onvif_password(password: str) -> None:
    """Length limits only; the device applies its own policy and reports ``ter:Password``."""
    if not password:
        raise ValueError("password must not be empty")
    if len(password.encode()) > 64:
        raise ValueError("password must be at most 64 bytes")


def soap_envelope(body: str) -> str:
    """Wrap an operation element in a SOAP 1.2 envelope with the ONVIF namespaces."""
    return (
        f'<s:Envelope xmlns:s="{SOAP_ENV}" xmlns:tds="{ONVIF_DEVICE}" xmlns:tt="{ONVIF_SCHEMA}">'
        f"<s:Body>{body}</s:Body></s:Envelope>"
    )


def user_element(username: str, level: OnvifUserLevel, password: str) -> str:
    """A ``tds:User`` element for ``CreateUsers`` / ``SetUser`` (password always present)."""
    return (
        f"<tds:User><tt:Username>{html.escape(username)}</tt:Username>"
        f"<tt:Password>{html.escape(password)}</tt:Password>"
        f"<tt:UserLevel>{level.value}</tt:UserLevel></tds:User>"
    )


def parse_fault(xml: str, status_code: int, *, password: object = None) -> AxisSoapFault | None:
    """Return the fault in a response body, or ``None`` if the body is not a fault.

    Fault *codes* are QNames from a controlled vocabulary (the SOAP envelope and
    ONVIF ``ter:*`` sets), never free device text, and any reply that quoted the
    sent credentials was already refused upstream -- so codes are quoted
    verbatim, and the fault's meaning survives even when the configured password
    happens to be a substring of a code (``Password`` in ``ter:PasswordTooWeak``).
    Only the *reason* -- free device text -- goes through
    :func:`~axis_cam.secrets.error_excerpt`, so a reason that holds the password
    is withheld while the fault still reaches the caller.
    """
    try:
        root = DefusedElementTree.fromstring(xml.strip())
    except (DefusedElementTree.ParseError, ValueError):
        return None
    fault = root.find("s:Body/s:Fault", _NS)
    if fault is None:
        return None

    def text_of(node: Element, path: str) -> str:
        return node.findtext(path, default="", namespaces=_NS).strip()

    code = text_of(fault, "s:Code/s:Value")
    subcodes: list[str] = []
    node = fault.find("s:Code/s:Subcode", _NS)
    while node is not None:
        subcodes.append(text_of(node, "s:Value"))
        node = node.find("s:Subcode", _NS)
    reason = error_excerpt(text_of(fault, "s:Reason/s:Text"), password=password)
    leaf = subcodes[-1] if subcodes else code
    meaning = _FAULT_MEANINGS.get(leaf)
    detail = f"{reason} ({leaf})" if reason else leaf
    message = f"{meaning} — device said: {detail}" if meaning else f"SOAP fault {detail}"
    return AxisSoapFault(
        f"HTTP {status_code}: {message}", code=code, subcodes=subcodes, reason=reason
    )


def parse_get_users(xml: str) -> OnvifAccounts:
    """Parse a ``GetUsersResponse``; unknown levels are kept as ``Extended``."""
    root = DefusedElementTree.fromstring(xml.strip())
    accounts: list[OnvifAccount] = []
    for user in root.iterfind("s:Body/tds:GetUsersResponse/tds:User", _NS):
        name = user.findtext("tt:Username", default="", namespaces=_NS)
        level_text = user.findtext("tt:UserLevel", default="", namespaces=_NS)
        try:
            level = OnvifUserLevel(level_text)
        except ValueError:
            level = OnvifUserLevel.EXTENDED
        accounts.append(OnvifAccount(username=name, level=level))
    return OnvifAccounts(accounts=accounts)


@register
class OnvifUsersAPI(BaseAPI):
    """Manage ONVIF users through the Device Management service on ``/vapix/services``.

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     users = await camera.onvif_users.list()
        ...     await camera.onvif_users.add("vms", "S3cret-pass", OnvifUserLevel.OPERATOR)
        ...     await camera.onvif_users.set_password("vms", "N3w-pass")
        ...     await camera.onvif_users.remove("vms")
    """

    name = "onvif_users"
    api_id = None  # SOAP service, not in the REST discovery; always attempted

    SERVICE_PATH: ClassVar[str] = "/vapix/services"

    async def read(self) -> OnvifAccounts:
        """Read the ONVIF user list (``ResourceModule`` protocol)."""
        return await self.list()

    async def list(self) -> OnvifAccounts:
        """``GetUsers``: every ONVIF user with its level. Passwords are never returned."""
        response = await self._call("<tds:GetUsers/>")
        return parse_get_users(response.text)

    async def add(self, username: str, password: str, level: OnvifUserLevel) -> OnvifAccount:
        """``CreateUsers`` for one user, then verify it is listed with that level.

        Raises:
            ValueError: Invalid user name or password (checked before any request).
            AxisUserError: The user already exists, or is missing / has the
                wrong level afterwards.
            AxisSoapFault: The device refused (``ter:UsernameClash``,
                ``ter:Password`` for a weak password, ``ter:TooManyUsers``, …).
        """
        validate_onvif_username(username)
        validate_onvif_password(password)
        if level is OnvifUserLevel.ANONYMOUS:
            raise ValueError("the Anonymous level cannot be assigned (ter:AnonymousNotAllowed)")
        if (await self.list()).get(username) is not None:
            raise AxisUserError(f"ONVIF user {username!r} already exists")
        await self._call(
            f"<tds:CreateUsers>{user_element(username, level, password)}</tds:CreateUsers>"
        )
        return await self._verify(username, level, verb="created")

    async def set_password(self, username: str, password: str) -> None:
        """``SetUser`` with a new password and the user's current level.

        ``GetUsers`` never returns passwords, so the device's acceptance is the
        result; verify by having the ONVIF client log in.

        Raises:
            ValueError: Invalid user name or password.
            AxisUserError: The user does not exist.
            AxisSoapFault: The device refused (``ter:PasswordTooWeak``, ``ter:FixedUser``).
        """
        validate_onvif_username(username)
        validate_onvif_password(password)
        current = (await self.list()).get(username)
        if current is None:
            raise AxisUserError(f"ONVIF user {username!r} does not exist")
        await self._call(
            f"<tds:SetUser>{user_element(username, current.level, password)}</tds:SetUser>"
        )

    async def set_level(
        self,
        username: str,
        level: OnvifUserLevel,
        password: str,
        *,
        allow_lockout: bool = False,
    ) -> OnvifAccount:
        """``SetUser`` with a new level and the user's password, then verify the level.

        The device will not change a level without a password (``ter:InvalidArgs``)
        and ONVIF never returns one, so the caller must supply it: the current
        password keeps the user's ONVIF clients working, a new one rotates it.

        Args:
            username: Existing ONVIF user.
            level: New level.
            password: The user's password (current or new).
            allow_lockout: Permit removing the last Administrator level.

        Raises:
            ValueError: Invalid user name or password, or the Anonymous level.
            AxisUserError: The user does not exist, or the level did not change.
            AxisLockoutError: The change would leave no ONVIF Administrator
                (without ``allow_lockout``).
            AxisSoapFault: The device refused.
        """
        validate_onvif_username(username)
        validate_onvif_password(password)
        if level is OnvifUserLevel.ANONYMOUS:
            raise ValueError("the Anonymous level cannot be assigned (ter:AnonymousNotAllowed)")
        accounts = await self.list()
        current = accounts.get(username)
        if current is None:
            raise AxisUserError(f"ONVIF user {username!r} does not exist")
        if (
            current.level is OnvifUserLevel.ADMINISTRATOR
            and level is not OnvifUserLevel.ADMINISTRATOR
        ):
            self._guard_last_administrator(accounts, current, "change the level of", allow_lockout)
        await self._call(f"<tds:SetUser>{user_element(username, level, password)}</tds:SetUser>")
        return await self._verify(username, level, verb="updated")

    async def remove(self, username: str, *, allow_lockout: bool = False) -> None:
        """``DeleteUsers`` for one user, then verify it is gone.

        Raises:
            ValueError: Invalid user name.
            AxisUserError: The user does not exist, or is still listed afterwards.
            AxisLockoutError: Removing the last ONVIF Administrator (without
                ``allow_lockout``).
            AxisSoapFault: The device refused (``ter:FixedUser``).
        """
        validate_onvif_username(username)
        accounts = await self.list()
        current = accounts.get(username)
        if current is None:
            raise AxisUserError(f"ONVIF user {username!r} does not exist")
        if current.level is OnvifUserLevel.ADMINISTRATOR:
            self._guard_last_administrator(accounts, current, "remove", allow_lockout)
        await self._call(
            f"<tds:DeleteUsers><tds:Username>{html.escape(username)}</tds:Username></tds:DeleteUsers>"
        )
        if (await self.list()).get(username) is not None:
            raise AxisUserError(
                f"device acknowledged deleting ONVIF user {username!r} but it is still listed"
            )

    # -- internals -----------------------------------------------------------

    async def _call(self, body: str) -> httpx.Response:
        """POST one operation; raise the SOAP fault if the device sent one."""
        response = await self._client.post_raw(
            self.SERVICE_PATH, soap_envelope(body), content_type=SOAP_CONTENT_TYPE
        )
        if response.status_code >= 400:
            # The client has already refused any reply that quotes this request's
            # credentials. What is quoted from the rest passes error_excerpt: a
            # fault field or an excerpt that holds the configured password is
            # withheld, while the fault's class and codes still reach the caller.
            text = response.text
            password = getattr(self._client, "password", None)
            fault = parse_fault(text, response.status_code, password=password)
            if fault is not None:
                raise fault
            raise AxisUserError(
                f"HTTP {response.status_code} from {self.SERVICE_PATH} without a SOAP fault: "
                f"{error_excerpt(text, password=password)!r}"
            )
        return response

    @staticmethod
    def _guard_last_administrator(
        accounts: OnvifAccounts, target: OnvifAccount, verb: str, allow_lockout: bool
    ) -> None:
        """Refuse to leave the ONVIF database without an Administrator unless asked.

        Unlike VAPIX accounts this is not a self-lockout — these credentials
        are never the ones this session uses — but a VMS that authenticates
        with that user loses administrative control of the device.
        """
        others = [a for a in accounts.administrators if a.username != target.username]
        if not others and not allow_lockout:
            raise AxisLockoutError(
                f"refusing to {verb} {target.username!r}: it is the only ONVIF Administrator. "
                "Pass allow_lockout=True to do it anyway."
            )

    async def _verify(self, username: str, level: OnvifUserLevel, *, verb: str) -> OnvifAccount:
        """Re-read the list and check the user has the expected level."""
        account = (await self.list()).get(username)
        if account is None:
            raise AxisUserError(
                f"device acknowledged that ONVIF user {username!r} was {verb} but it is not listed"
            )
        if account.level is not level:
            raise AxisUserError(
                f"ONVIF user {username!r} was {verb} but has level {account.level.value}; "
                f"expected {level.value}"
            )
        return account
