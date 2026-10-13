"""User accounts API module (``/axis-cgi/pwdgrp.cgi``).

The first module in this library that writes to a device, so it carries the
write-safety rules the later ones (restore, factory default) reuse:

- **Secrets travel in the request body.** Every write is a form-encoded POST;
  a password is never put in a URL (device access logs, proxies, shell
  history). The VAPIX documentation says the same.
- **A 200 is not success.** ``pwdgrp.cgi`` reports failure with HTTP 200 and a
  body beginning ``Error:``; the body is inspected and raised as
  :class:`~axis_cam.exceptions.AxisUserError`.
- **Every write is verified.** After ``add``, ``set_role`` and ``remove`` the
  account list is re-read and the result checked, because the device's
  acknowledgement text is not consistent across firmware. A password change
  cannot be verified by reading; the acknowledgement is all there is.
- **Lockout guard.** Removing or de-admining the account the client is
  authenticated as is refused unless ``allow_lockout=True``; removing the last
  administrator is refused outright (an Axis device with no administrator
  accepts an unauthenticated request to create one).

API reference: VAPIX System settings, "Add, modify and delete user accounts".
"""

import re
from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.api.registry import register
from axis_cam.exceptions import AxisLockoutError, AxisUserError
from axis_cam.models import UserAccount, UserAccounts, UserRole, role_to_sgrp

#: Account names are 1-14 characters from ``A-Z``, ``a-z``, ``0-9``.
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9]{1,14}$")
#: Passwords are 1-64 characters; under ``strict_pwd`` printable ASCII only.
PASSWORD_MAX_LENGTH = 64

_GROUP_LINE = re.compile(r'^\s*(?P<group>\w+)\s*=\s*"(?P<members>[^"]*)"\s*$')
_ROLE_GROUPS: tuple[tuple[str, UserRole], ...] = (
    ("admin", UserRole.ADMIN),
    ("operator", UserRole.OPERATOR),
    ("viewer", UserRole.VIEWER),
)
_FRIENDLY_ERRORS = {
    "Error: invalid password.": (
        "the device rejected the password: it must be 1-64 printable ASCII "
        "characters and comply with the device's passphrase policy"
    ),
    "Error: account user name.": (
        "the device rejected the user name: 1-14 characters from A-Z, a-z, 0-9"
    ),
    "Error: consult the system log file.": (
        "the device refused the operation and logged the reason in its system log "
        "(see `axiscam logs system`)"
    ),
}


def validate_username(username: str) -> None:
    """Check a user name against the VAPIX rules before contacting the device.

    Raises:
        ValueError: If the name is empty, longer than 14 characters, or uses
            characters outside ``A-Z a-z 0-9``.
    """
    if not USERNAME_PATTERN.match(username):
        raise ValueError(f"invalid user name {username!r}: 1-14 characters from A-Z, a-z and 0-9")


def validate_password(password: str, *, strict: bool = True) -> None:
    """Check a password against the VAPIX rules before contacting the device.

    Args:
        password: The candidate password. Never logged or echoed.
        strict: Apply the ``strict_pwd`` character rule (printable ASCII).

    Raises:
        ValueError: If the password is empty, longer than 64 characters, or (in
            strict mode) contains characters outside ``0x20-0x7E``.
    """
    if not 1 <= len(password) <= PASSWORD_MAX_LENGTH:
        raise ValueError(f"password must be 1-{PASSWORD_MAX_LENGTH} characters")
    if strict and any(not 0x20 <= ord(ch) <= 0x7E for ch in password):
        raise ValueError("password must contain only printable ASCII characters (0x20-0x7E)")


def parse_account_list(text: str) -> UserAccounts:
    """Parse the ``action=get`` response.

    The device answers one line per group, ``group="user1,user2"``. Access
    groups are cumulative (an administrator is listed under ``admin``,
    ``operator`` and ``viewer``); ``digusers`` lists every account. The highest
    access group an account appears in becomes its role.

    Raises:
        AxisUserError: If the body is a ``pwdgrp.cgi`` error message.
    """
    stripped = text.strip()
    if stripped.startswith("Error"):
        raise AxisUserError(f"device refused to list accounts: {stripped}")

    groups: dict[str, list[str]] = {}
    for line in stripped.splitlines():
        match = _GROUP_LINE.match(line)
        if match:
            members = [m.strip() for m in match.group("members").split(",") if m.strip()]
            groups[match.group("group")] = members

    # digusers is the authoritative list; fall back to the union of all groups
    # for firmware that omits it, preserving first-seen order.
    names: list[str] = list(groups.get("digusers", []))
    for members in groups.values():
        for name in members:
            if name not in names:
                names.append(name)

    accounts = []
    for name in names:
        role = next((r for grp, r in _ROLE_GROUPS if name in groups.get(grp, [])), None)
        accounts.append(UserAccount(username=name, role=role, ptz=name in groups.get("ptz", [])))
    return UserAccounts(accounts=accounts)


@register
class UsersAPI(BaseAPI):
    """Manage VAPIX user accounts via ``pwdgrp.cgi``.

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     accounts = await camera.users.list()
        ...     await camera.users.add("ops", "S3cret-pass", UserRole.OPERATOR)
        ...     await camera.users.set_password("ops", "N3w-pass")
        ...     await camera.users.remove("ops")
    """

    name = "users"
    api_id = None  # legacy CGI; not in /config/discover/apis

    CGI_PATH = "/axis-cgi/pwdgrp.cgi"

    async def read(self) -> UserAccounts:
        """Read the account list (``ResourceModule`` protocol)."""
        return await self.list()

    async def list(self) -> UserAccounts:
        """List every account with its role and PTZ right.

        Requires administrator credentials on the client.
        """
        text = await self._get_text(self.CGI_PATH, params={"action": "get"})
        return parse_account_list(text)

    async def add(
        self,
        username: str,
        password: str,
        role: UserRole,
        *,
        ptz: bool = False,
        comment: str = "",
        strict_password: bool = True,
    ) -> UserAccount:
        """Create an account and verify it exists with the requested role.

        Args:
            username: 1-14 characters from ``A-Z a-z 0-9``.
            password: 1-64 characters; printable ASCII when ``strict_password``.
            role: Access role.
            ptz: Grant PTZ control.
            comment: Free-text description stored on the device.
            strict_password: Ask the device to enforce its passphrase policy.

        Returns:
            The account as the device reports it after creation.

        Raises:
            ValueError: Invalid user name or password (checked before any request).
            AxisUserError: The account already exists, the device refused, or
                the account is missing or has the wrong role afterwards.
        """
        validate_username(username)
        validate_password(password, strict=strict_password)
        if (await self.list()).get(username) is not None:
            raise AxisUserError(f"account {username!r} already exists")

        data: dict[str, Any] = {
            "action": "add",
            "user": username,
            "pwd": password,
            "grp": "users",
            "sgrp": role_to_sgrp(role, ptz),
            "comment": comment,
        }
        if strict_password:
            data["strict_pwd"] = "1"
        self._check_reply(await self._post_form(self.CGI_PATH, data), "create", username)
        return await self._verify_account(username, role, ptz, verb="created")

    async def set_password(
        self, username: str, password: str, *, strict_password: bool = True
    ) -> None:
        """Change an account's password.

        The device acknowledges with ``Modified account <user>.``; there is no
        way to verify a password by reading, so that acknowledgement is the
        result.

        Raises:
            ValueError: Invalid user name or password.
            AxisUserError: The account does not exist or the device refused.
        """
        validate_username(username)
        validate_password(password, strict=strict_password)
        if (await self.list()).get(username) is None:
            raise AxisUserError(f"account {username!r} does not exist")

        data: dict[str, Any] = {"action": "update", "user": username, "pwd": password}
        if strict_password:
            data["strict_pwd"] = "1"
        self._check_reply(
            await self._post_form(self.CGI_PATH, data), "change the password of", username
        )

    async def set_role(
        self,
        username: str,
        role: UserRole,
        *,
        ptz: bool = False,
        allow_lockout: bool = False,
    ) -> UserAccount:
        """Change an account's role and verify the change.

        Args:
            username: Existing account.
            role: New access role.
            ptz: Grant PTZ control.
            allow_lockout: Permit de-admining the account the client is
                authenticated as.

        Raises:
            ValueError: Invalid user name.
            AxisUserError: The account does not exist, the device refused, or
                the role did not change.
            AxisLockoutError: The change would de-admin the authenticated
                account (without ``allow_lockout``) or remove the last
                administrator.
        """
        validate_username(username)
        accounts = await self.list()
        current = accounts.get(username)
        if current is None:
            raise AxisUserError(f"account {username!r} does not exist")
        if current.role is UserRole.ADMIN and role is not UserRole.ADMIN:
            self._guard_losing_admin(accounts, current, "change the role of", allow_lockout)

        data = {"action": "update", "user": username, "sgrp": role_to_sgrp(role, ptz)}
        self._check_reply(
            await self._post_form(self.CGI_PATH, data), "change the role of", username
        )
        return await self._verify_account(username, role, ptz, verb="updated")

    async def remove(self, username: str, *, allow_lockout: bool = False) -> None:
        """Remove an account and verify it is gone.

        Args:
            username: Existing account.
            allow_lockout: Permit removing the account the client is
                authenticated as.

        Raises:
            ValueError: Invalid user name.
            AxisUserError: The account does not exist, the device refused, or
                the account is still present afterwards.
            AxisLockoutError: Removing the authenticated account (without
                ``allow_lockout``) or the last administrator.
        """
        validate_username(username)
        accounts = await self.list()
        current = accounts.get(username)
        if current is None:
            raise AxisUserError(f"account {username!r} does not exist")
        if current.role is UserRole.ADMIN:
            self._guard_losing_admin(accounts, current, "remove", allow_lockout)
        elif self._is_self(username) and not allow_lockout:
            raise AxisLockoutError(
                f"refusing to remove {username!r}: it is the account this session is "
                "authenticated as. Pass allow_lockout=True to do it anyway."
            )

        self._check_reply(
            await self._post_form(self.CGI_PATH, {"action": "remove", "user": username}),
            "remove",
            username,
        )
        if (await self.list()).get(username) is not None:
            raise AxisUserError(
                f"device acknowledged removing {username!r} but the account is still listed"
            )

    # -- internals -----------------------------------------------------------

    def _is_self(self, username: str) -> bool:
        return username == self._client.username

    def _guard_losing_admin(
        self, accounts: UserAccounts, target: UserAccount, verb: str, allow_lockout: bool
    ) -> None:
        """Refuse changes that remove administrator access unsafely."""
        others = [a for a in accounts.admins if a.username != target.username]
        if not others:
            raise AxisLockoutError(
                f"refusing to {verb} {target.username!r}: it is the only administrator. "
                "A device with no administrator accepts an unauthenticated request to "
                "create one; add another administrator first."
            )
        if self._is_self(target.username) and not allow_lockout:
            raise AxisLockoutError(
                f"refusing to {verb} {target.username!r}: it is the account this session is "
                "authenticated as and would lose administrator access. Pass "
                "allow_lockout=True to do it anyway."
            )

    @staticmethod
    def _check_reply(text: str, verb: str, username: str) -> None:
        """Raise if a 200 reply body is one of the CGI's error messages."""
        stripped = text.strip()
        if stripped.startswith("Error"):
            reason = _FRIENDLY_ERRORS.get(stripped, stripped)
            raise AxisUserError(f"could not {verb} account {username!r}: {reason}")

    async def _verify_account(
        self, username: str, role: UserRole, ptz: bool, *, verb: str
    ) -> UserAccount:
        """Re-read the list and check the account has the expected rights."""
        account = (await self.list()).get(username)
        if account is None:
            raise AxisUserError(
                f"device acknowledged that {username!r} was {verb} but it is not listed"
            )
        if account.role is not role or account.ptz is not ptz:
            actual = account.role.value if account.role else "none"
            raise AxisUserError(
                f"account {username!r} was {verb} but has role {actual} (ptz={account.ptz}); "
                f"expected {role.value} (ptz={ptz})"
            )
        return account
