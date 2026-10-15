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

from collections import deque
from collections.abc import Generator
from enum import Enum

import httpx

#: How many distinct ``Authorization`` values a :class:`VapixAuth` remembers.
#: Basic sends one value; Digest a new one per request (nonce count, cnonce).
SENT_MEMORY = 64


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
        #: Every distinct ``Authorization`` value sent, oldest first, at most
        #: :data:`SENT_MEMORY`. A reply or a download decoded later that quotes
        #: any of them is an echo (:mod:`axis_cam.secrets`); the ``Request``
        #: itself keeps only the last value, because the flows mutate it.
        self.sent: deque[str] = deque(maxlen=SENT_MEMORY)

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

    def _run(
        self, auth: httpx.Auth, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, httpx.Response]:
        """Drive another Auth's flow to completion and return its final response.

        Records each ``Authorization`` value as it goes out (:attr:`sent`).
        """
        flow = auth.auth_flow(request)
        outgoing = next(flow)
        while True:
            self._remember(outgoing)
            response = yield outgoing
            try:
                outgoing = flow.send(response)
            except StopIteration:
                return response

    def _remember(self, request: httpx.Request) -> None:
        value = request.headers.get("Authorization")
        if value and value not in self.sent:
            self.sent.append(value)

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        """Authenticate ``request``, switching scheme when the device demands it.

        Runs the settled (or first-choice) scheme's flow. In ``AUTO`` mode a 401
        whose ``WWW-Authenticate`` offers only the *other* scheme triggers one
        retry with that scheme, which is then remembered. A 401 that offers the
        scheme just used is a genuine rejection and is returned. Only a 2xx
        settles the choice: a 404 for a CGI the device lacks says nothing about
        which scheme it accepts (an 11.x speaker answered 404 to a Basic request
        and then demanded Digest on the next CGI, verified 2026-10-13).
        """
        current = self._chosen or self._first_choice()
        response = yield from self._run(current, request)
        if self.mode is not AuthMode.AUTO:
            return
        if 200 <= response.status_code < 300:
            self._chosen = current
            return
        if response.status_code != 401:
            return
        offered = offered_schemes(response)
        current_name = "basic" if current is self._basic else "digest"
        if current_name in offered or not offered:
            return  # same scheme offered back (or no challenge): genuine rejection
        if current is self._basic and "digest" in offered:
            fallback: httpx.Auth = self._digest
        elif (
            current is self._digest
            and "basic" in offered
            and (self.https or self.allow_insecure_basic)
        ):
            fallback = self._basic
        else:
            return  # Basic-only over plain HTTP without explicit permission
        request.headers.pop("Authorization", None)
        retry = yield from self._run(fallback, request)
        if 200 <= retry.status_code < 300:
            self._chosen = fallback
