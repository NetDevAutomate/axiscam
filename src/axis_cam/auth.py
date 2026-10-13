"""HTTP authentication that follows the device's challenge.

Axis's guidance (VAPIX Authentication): use Basic over HTTPS and Digest over
HTTP, and let the device's ``WWW-Authenticate`` header tell you which it
accepts. In practice a fleet mixes both: an AXIS OS 12 camera with
``Network.HTTP.AuthenticationPolicy=recommended`` offers *only* Basic on HTTPS,
while a speaker on 11.x offers only Digest. A fixed client-side choice therefore
fails on part of any real fleet.

:class:`VapixAuth` in ``auto`` mode starts with the scheme Axis recommends for
the transport, and if the device answers 401 offering the other scheme, retries
with that and remembers the decision for the rest of the session. Basic over
plain HTTP is never chosen automatically.
"""

from collections.abc import Generator
from enum import Enum

import httpx


class AuthMode(str, Enum):
    """How to authenticate to a device."""

    AUTO = "auto"
    BASIC = "basic"
    DIGEST = "digest"


def offered_schemes(response: httpx.Response) -> set[str]:
    """Lower-cased scheme names from every ``WWW-Authenticate`` header."""
    return {
        header.split(" ", 1)[0].strip().lower()
        for header in response.headers.get_list("www-authenticate")
        if header.strip()
    }


class VapixAuth(httpx.Auth):
    """``httpx.Auth`` that picks Basic or Digest from the device's challenge.

    Args:
        username: Account name.
        password: Account password.
        mode: ``AUTO`` follows the challenge; ``BASIC``/``DIGEST`` force a scheme.
        https: Whether the transport is TLS (decides the first attempt in AUTO).
        allow_insecure_basic: Permit falling back to Basic over plain HTTP when
            the device offers nothing else. Off by default: cleartext credentials.
    """

    requires_response_body = False

    def __init__(
        self,
        username: str,
        password: str,
        *,
        mode: AuthMode = AuthMode.AUTO,
        https: bool = True,
        allow_insecure_basic: bool = False,
    ) -> None:
        self.mode = mode
        self.https = https
        self.allow_insecure_basic = allow_insecure_basic
        self._basic = httpx.BasicAuth(username, password)
        self._digest = httpx.DigestAuth(username, password)
        self._chosen: httpx.Auth | None = None

    @property
    def scheme(self) -> str | None:
        """``"basic"`` or ``"digest"`` once a scheme has been settled, else ``None``."""
        if self._chosen is self._basic:
            return "basic"
        if self._chosen is self._digest:
            return "digest"
        return None

    def _first_choice(self) -> httpx.Auth:
        if self.mode is AuthMode.BASIC:
            return self._basic
        if self.mode is AuthMode.DIGEST:
            return self._digest
        return self._basic if self.https else self._digest

    @staticmethod
    def _run(
        auth: httpx.Auth, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, httpx.Response]:
        """Drive another Auth's flow to completion and return its final response."""
        flow = auth.auth_flow(request)
        outgoing = next(flow)
        while True:
            response = yield outgoing
            try:
                outgoing = flow.send(response)
            except StopIteration:
                return response

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        """Authenticate ``request``, switching scheme once if the device demands it.

        Runs the current (or first-choice) scheme's flow. In ``AUTO`` mode, a
        401 whose ``WWW-Authenticate`` offers the *other* scheme triggers one
        retry with that scheme, which is then remembered for the session. A
        401 that offers the same scheme is a genuine rejection and is returned.
        """
        primary = self._chosen or self._first_choice()
        response = yield from self._run(primary, request)
        if self._chosen is not None or self.mode is not AuthMode.AUTO:
            return
        if response.status_code != 401:
            self._chosen = primary
            return

        offered = offered_schemes(response)
        if primary is self._basic and "digest" in offered:
            fallback: httpx.Auth | None = self._digest
        elif (
            primary is self._digest
            and "basic" in offered
            and "digest" not in offered
            and (self.https or self.allow_insecure_basic)
        ):
            fallback = self._basic
        else:
            fallback = None  # genuinely rejected, or Basic-only over plain HTTP
        if fallback is None:
            return
        self._chosen = fallback
        request.headers.pop("Authorization", None)
        yield from self._run(fallback, request)
