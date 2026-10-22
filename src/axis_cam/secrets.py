"""Credential handling: which parameters hold secrets, and the request's own credentials.

Axis devices keep some secrets in ordinary parameters -- SNMP community
strings, proxy and 802.1X passwords, wireless PSKs -- and
``param.cgi?action=list`` returns them like any other value. Everything that
handles the parameter tree uses :func:`is_secret_name` to recognise them: backup
manifests declare them, restore leaves them alone unless asked, the CLI does
not echo them and the MCP server redacts them.

The rule is by *name* and deliberately broad: a false positive costs one
parameter that needs an explicit opt-in; a false negative leaks a credential.

The rest of this module closes the *other* path a credential can take out: the
request's own ``Authorization``. No Axis device echoes request headers, but a
proxy, WAF, debug page or hostile peer can, and the library quotes device text
in its error messages. So:

- :func:`quotes_sent_auth` recognises a reply that quotes the credentials its
  request sent, and the client refuses every such reply, whatever its status
  (:class:`~axis_cam.exceptions.AxisEchoError`). Such a reply is not device
  data; refusing it rather than editing it keeps every data path faithful, and
  nothing downstream ever sees, parses or quotes it.
- :func:`error_excerpt` quotes genuine device error text verbatim (cut to 200
  characters) and withholds an excerpt that contains the configured password
  (:func:`contains_password`), the one secret a reply may carry without being
  an echo.

"Quotes" covers the header itself, the Basic token in every common spelling --
percent-encoded (also twice), JSON slash and ``uXXXX`` escapes, HTML entities,
stripped padding, base64url -- and any fragment of 8 or more of its
base64 characters that covers at least 4 password bytes, plus 12 or more hex
characters of a Digest ``response`` hash in either case. The client passes
every ``Authorization`` value it sent (``VapixAuth.sent``), not only the one of
the request at hand: a reply can replay an earlier request's Digest hash, a
download is decoded after its response is gone, and in AUTO mode a Basic attempt
precedes the Digest request that produced the response (``VapixAuth`` reuses one
``Request``, so neither ``response.request`` nor ``response.history`` still
holds it). The Basic token built from the configured credentials always counts
as well, for a caller without that record. Redirects are checked before they
are followed: a target URL that carries the token is never requested. Decision
record: ``docs/plans/2026-10-15-secrets-boundary-decision.md``.

Stated limits: a peer that already holds the credential and deliberately
re-encodes it (reversed, base32) defeats any text check. The configured password
stored *base64-encoded* in genuine device data is refused for some username
lengths; no Axis parameter is known to store one.
"""

from __future__ import annotations

import base64
import html
import json
import re
import urllib.parse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    import httpx

#: Replacement marker for any redacted credential (library and MCP share it).
REDACTED = "[redacted]"

#: Matched case-insensitively against the full dotted name.
SECRET_NAME = re.compile(
    r"(?i)pass(word|wd|phrase)?|secret|community|psk|token|credential|privatekey"
)

#: A fragment this long is a credential: 8 base64 characters (6 bytes), 12 hex.
BASE64_FRAGMENT = 8
HEX_FRAGMENT = 12
#: Fewer password bytes than this are not a credential worth a fragment rule:
#: they match ordinary text, and no substring rule can protect them anyway.
MIN_PASSWORD = 4
#: Longest excerpt of device error text quoted in a message.
EXCERPT_LIMIT = 200

#: The hex ``response`` value inside a Digest ``Authorization`` header.
_DIGEST_RESPONSE = re.compile(r'(?i)\bresponse\s*=\s*"?([0-9a-f]{8,})"?')
#: A run of hex digits (lower case) long enough to hold a Digest fragment.
_HEX_RUN = re.compile(rf"[0-9a-f]{{{HEX_FRAGMENT},}}")
#: One percent escape, for the lower-case-hex spellings of a password.
_PERCENT = re.compile(r"%[0-9A-F]{2}")
#: The escapes an echo commonly applies. Undone twice, for double encoding.
_ESCAPE = re.compile(
    r"%(?P<pct>[0-9A-Fa-f]{2})"
    r"|\\u(?P<uni>[0-9A-Fa-f]{4})"
    r"|\\(?P<slash>/)"
    r"|(?P<entity>&(?:[A-Za-z][A-Za-z0-9]{1,31}|#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6});)"
)
#: base64url's alphabet folded onto base64's.
_BASE64URL = str.maketrans({"-": "+", "_": "/"})


def is_secret_name(name: str) -> bool:
    """Whether a parameter name looks like it holds a credential."""
    return bool(SECRET_NAME.search(name))


def credential_names(params: Mapping[str, str]) -> list[str]:
    """Sorted names of credential parameters that have a value.

    An empty value is "not set" and is not a credential worth declaring.
    """
    return sorted(name for name, value in params.items() if value and is_secret_name(name))


# -- the request's own credentials ---------------------------------------------


def _unescape(match: re.Match[str]) -> str:
    if match.group("pct"):
        return chr(int(match.group("pct"), 16))
    if match.group("uni"):
        return chr(int(match.group("uni"), 16))
    if match.group("slash"):
        return "/"
    decoded = html.unescape(match.group("entity"))
    # An entity html.unescape does not know comes back unchanged: keep it.
    return decoded if len(decoded) == 1 else match.group(0)


def _decoded(text: str) -> str:
    """``text`` with the common echo escapes undone, twice (for double encoding).

    The second pass runs only when the first left an escape behind, which is
    rare in genuine text; this halves the cost on escape-dense bodies.
    """
    once = _ESCAPE.sub(_unescape, text)
    return _ESCAPE.sub(_unescape, once) if _ESCAPE.search(once) else once


def token_windows(token: str) -> set[str]:
    """The 8-character fragments of a Basic token that cover 4 or more password bytes.

    The token's first characters encode ``username:``. A window covering fewer
    password bytes would also match another credential of the same user (a
    legitimate value), so it does not count. For a password under 4 bytes no
    fragment counts; only the whole token does.
    """
    try:
        raw = base64.b64decode(token + "=" * (-len(token) % 4))
        first = raw.index(b":") + 1  # the first password byte
    except ValueError:  # not base64, or no separator: every window counts
        return {token[i : i + BASE64_FRAGMENT] for i in range(len(token) - BASE64_FRAGMENT + 1)}
    windows: set[str] = set()
    for i in range(len(token) - BASE64_FRAGMENT + 1):
        lo, hi = 6 * i, 6 * (i + BASE64_FRAGMENT)  # the bits this window encodes
        covered = sum(1 for j in range(first, len(raw)) if 8 * j >= lo and 8 * j + 8 <= hi)
        if covered >= MIN_PASSWORD:
            windows.add(token[i : i + BASE64_FRAGMENT])
    return windows


class _SentCredentials:
    """What the client authenticated with: header values, Basic tokens, Digest hashes."""

    def __init__(
        self,
        response: httpx.Response | None,
        username: object,
        password: object,
        sent: Iterable[object] = (),
    ) -> None:
        self.headers: set[str] = set()
        self.tokens: set[str] = set()
        self.hashes: set[str] = set()
        try:
            header = response.request.headers.get("Authorization")  # type: ignore[union-attr]
        except (AttributeError, RuntimeError):  # None, or no request attached (httpx raises)
            header = None
        if isinstance(header, str) and header.strip():
            self.headers.add(header)  # this request's, also matched verbatim
        for value in (header, *sent):
            self._add(value)
        if isinstance(username, str) and isinstance(password, str) and password:
            # Sent in AUTO mode before a Digest retry; see the module docstring.
            self.tokens.add(base64.b64encode(f"{username}:{password}".encode()).decode())

    def _add(self, header: object) -> None:
        if not isinstance(header, str):
            return
        scheme, _, rest = header.strip().partition(" ")
        if scheme.lower() == "basic" and rest.strip():
            self.tokens.add(rest.strip())
        elif scheme.lower() == "digest":
            self.hashes.update(m.group(1).lower() for m in _DIGEST_RESPONSE.finditer(rest))

    def found_in(self, text: str) -> bool:
        if any(header in text for header in self.headers):
            return True
        if not self.tokens and not self.hashes:
            return False
        decoded = _decoded(text)
        folded = decoded.translate(_BASE64URL)
        for token in self.tokens:
            needles = token_windows(token) | {token, token.rstrip("=")}
            if any(needle in folded for needle in needles):
                return True
        return bool(self.hashes) and _holds_hex_window(decoded.lower(), self.hashes)


def _holds_hex_window(lowered: str, hashes: set[str]) -> bool:
    """Whether ``lowered`` holds 12 or more hex characters of any hash, in one pass.

    Each window of each hex run in the text is looked up in a set, so the cost
    does not grow with the number of hashes (a client remembers every Digest
    request it sent). A window inside a longer run counts.
    """
    windows = {h[i : i + HEX_FRAGMENT] for h in hashes for i in range(len(h) - HEX_FRAGMENT + 1)}
    for run in _HEX_RUN.finditer(lowered):
        digits = run.group()
        if any(
            digits[i : i + HEX_FRAGMENT] in windows for i in range(len(digits) - HEX_FRAGMENT + 1)
        ):
            return True
    return False


def quotes_sent_auth(
    text: str,
    response: httpx.Response | None,
    *,
    username: object = None,
    password: object = None,
    sent: Iterable[object] = (),
) -> bool:
    """Whether a reply quotes credentials the client sent, in any common spelling.

    ``response`` supplies its request's ``Authorization`` header; ``sent`` adds
    every other value the client sent (``VapixAuth.sent``), so a reply that
    replays an earlier request's Digest hash, or a download decoded after the
    response is gone, is recognised too; ``username`` and ``password`` add the
    Basic token they make (see the module docstring). The configured *plain*
    password does not count -- a device legitimately stores it in other
    parameters (an administrator password reused as the proxy password), so it
    would refuse real data. Non-string text and mocks answer ``False``.
    """
    if not isinstance(text, str):
        return False
    return _SentCredentials(response, username, password, sent).found_in(text)


def contains_password(text: str, password: object) -> bool:
    """Whether ``text`` holds the configured password in a common spelling.

    Literal, percent-encoded (path and form style, UTF-8, upper- or lower-case
    hex), JSON-escaped (ASCII or not) and HTML-escaped forms, and anything
    :func:`_decoded` undoes. Passwords under 4 characters are not hunted: they
    match ordinary words.
    """
    if not isinstance(text, str) or not isinstance(password, str):
        return False
    if len(password) < MIN_PASSWORD:
        return False
    percent = {
        urllib.parse.quote(password, safe=""),
        urllib.parse.quote(password),
        urllib.parse.quote_plus(password),
    }
    spellings = {
        password,
        *percent,
        *(_PERCENT.sub(lambda m: m.group().lower(), spelling) for spelling in percent),
        json.dumps(password)[1:-1],
        json.dumps(password, ensure_ascii=False)[1:-1],
        html.escape(password),
        html.escape(password, quote=False),
    }
    return any(s in text for s in spellings) or password in _decoded(text)


def error_excerpt(
    text: str,
    *,
    password: object = None,
    secrets: Iterable[str] = (),
    limit: int = EXCERPT_LIMIT,
) -> str:
    """Device error text to quote in a message: verbatim and cut, or withheld.

    Call it only on a reply :func:`quotes_sent_auth` has cleared (the client
    refuses the others). An excerpt that contains the configured password, or a
    credential the request itself carried (``secrets``: a parameter update's
    value, a ``pwdgrp`` ``pwd``, in a form body an echo can quote back), is
    withheld whole, before any cut, so no part of it survives. Both are matched
    in the spellings :func:`contains_password` knows.
    """
    if not isinstance(text, str):
        return ""
    if contains_password(text, password):
        return f"[{len(text)} characters withheld: the reply contains the configured password]"
    if any(contains_password(text, secret) for secret in secrets):
        return f"[{len(text)} characters withheld: the reply quotes a credential this request sent]"
    return text[:limit]


__all__ = [
    "BASE64_FRAGMENT",
    "EXCERPT_LIMIT",
    "HEX_FRAGMENT",
    "MIN_PASSWORD",
    "REDACTED",
    "SECRET_NAME",
    "contains_password",
    "credential_names",
    "error_excerpt",
    "is_secret_name",
    "quotes_sent_auth",
    "token_windows",
]
