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
request's own ``Authorization``. A well-behaved Axis device never echoes request
headers, but a proxy, WAF, debug page or hostile peer can, and the library quotes
device text in its error messages. An echo can re-spell the credential (URL
encoding, JSON escapes, stripped padding, base64url, upper-case hex), a peer can
cut it short, and a truncation can cut it in half -- each of which gets past a
whole-string scrubber such as the MCP ``Scrubber``. So:

- :func:`quotes_sent_auth` tells the client to *refuse* a success reply that
  quotes the request's credentials: that body is evidence of a peer echoing the
  request, not device data, and silently redacting it would alter data.
- :func:`redact_sent_auth` and :func:`error_excerpt` clean device text *before*
  it is cut into an error message.

Both recognise every common spelling, and any fragment of 8 or more base64
characters of a Basic token that covers at least 4 password bytes, or 12 or more
hex characters of a Digest ``response`` hash. The configured plain password is
matched whole (in every spelling), never as fragments: fragments of a dictionary
word would garble genuine device text. The Basic token built from the
configured credentials always counts: in AUTO mode a Basic attempt can precede
the Digest request that produced the response, and ``VapixAuth`` reuses one
``Request``, so neither ``response.request`` nor ``response.history`` still holds
it. Decision record: ``docs/plans/2026-10-15-secrets-boundary-decision.md``.

A stated limit: a peer that already holds the credential and deliberately
re-encodes it (reversed, base32) defeats any free-text filter. The guarantee is
against reflection -- verbatim echoes, the common encodings, and truncation.
"""

from __future__ import annotations

import base64
import html
import math
import re
from bisect import bisect_right
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    import httpx

#: Replacement marker for any redacted credential (library and MCP share it).
REDACTED = "[redacted]"

#: Matched case-insensitively against the full dotted name.
SECRET_NAME = re.compile(
    r"(?i)pass(word|wd|phrase)?|secret|community|psk|token|credential|privatekey"
)

#: The hex ``response`` value inside a Digest ``Authorization`` header.
_DIGEST_RESPONSE = re.compile(r'response\s*=\s*"?([0-9a-fA-F]{8,})"?')

#: A fragment this long is a credential: 8 base64 characters (6 bytes), 12 hex.
BASE64_FRAGMENT = 8
HEX_FRAGMENT = 12
#: A configured password shorter than this is not hunted in free text: it would
#: match ordinary words, and no substring rule can protect it anyway.
MIN_PASSWORD = 4

#: The escapes an echo commonly applies, each decoding to one character.
_ESCAPE = re.compile(
    r"%(?P<pct>[0-9A-Fa-f]{2})"
    r"|\\u(?P<uni>[0-9A-Fa-f]{4})"
    r"|\\(?P<slash>/)"
    r"|&(?:amp|lt|gt|quot|apos|#\d{1,7}|#[xX][0-9A-Fa-f]{1,6});"
)
#: base64url's alphabet folded onto base64's, for matching only.
_BASE64URL = str.maketrans({"-": "+", "_": "/"})
#: An error body that dumps request headers is withheld outright.
_HEADER_DUMP = re.compile(r"(?i)\bauthorization\b[\"']?\s*[:=]")


def is_secret_name(name: str) -> bool:
    """Whether a parameter name looks like it holds a credential."""
    return bool(SECRET_NAME.search(name))


def credential_names(params: Mapping[str, str]) -> list[str]:
    """Sorted names of credential parameters that have a value.

    An empty value is "not set" and is not a credential worth declaring.
    """
    return sorted(name for name, value in params.items() if value and is_secret_name(name))


# -- the request's own credentials ---------------------------------------------


class _Credentials:
    """What a request authenticated with: header values, Basic tokens, Digest hashes."""

    def __init__(self, response: httpx.Response, username: object, password: object) -> None:
        self.headers: set[str] = set()
        self.tokens: set[str] = set()
        self.hashes: set[str] = set()
        try:
            header = response.request.headers.get("Authorization")
        except (AttributeError, RuntimeError):  # no request attached (httpx raises)
            header = None
        if isinstance(header, str) and header.strip():
            self.headers.add(header)
            scheme, _, rest = header.partition(" ")
            if scheme.lower() == "basic" and rest.strip():
                self.tokens.add(rest.strip())
            elif scheme.lower() == "digest":
                self.hashes.update(m.group(1) for m in _DIGEST_RESPONSE.finditer(rest))
        if isinstance(username, str) and isinstance(password, str) and password:
            # Sent in AUTO mode before a Digest retry; see the module docstring.
            self.tokens.add(base64.b64encode(f"{username}:{password}".encode()).decode())

    def spans(self, view: _View, plain: str | None = None) -> list[tuple[int, int]]:
        """Decoded spans of ``view`` covered by a credential fragment, merged.

        Token fragments are matched with base64url folded onto base64, hash
        fragments case-insensitively, and the plain password only whole.
        """
        folded = view.decoded.translate(_BASE64URL)
        spans: list[tuple[int, int]] = []
        for token in self.tokens:
            whole = {token, token.rstrip("=")}
            spans += _covered(folded, _token_windows(token) | whole)
        for digest in self.hashes:
            spans += _covered(view.decoded, _windows(digest, HEX_FRAGMENT), ignore_case=True)
        if plain:
            spans += _covered(view.decoded, {plain})
        return _merge(spans)


class _View:
    """``text`` with common escapes undone, mapping decoded positions back."""

    def __init__(self, text: str) -> None:
        self.text = text
        #: Per segment: decoded start, original start, original length if the
        #: segment is one escape (else 0, a literal run of equal length).
        self._starts: list[int] = []
        self._origins: list[int] = []
        self._escapes: list[int] = []
        parts: list[str] = []
        pos = decoded = 0
        for match in _ESCAPE.finditer(text):
            if match.start() > pos:
                self._segment(decoded, pos, 0)
                parts.append(text[pos : match.start()])
                decoded += match.start() - pos
            self._segment(decoded, match.start(), match.end() - match.start())
            parts.append(_unescape(match))
            decoded += 1
            pos = match.end()
        if pos < len(text):
            self._segment(decoded, pos, 0)
            parts.append(text[pos:])
        self.decoded = "".join(parts)

    def _segment(self, decoded: int, origin: int, escape: int) -> None:
        self._starts.append(decoded)
        self._origins.append(origin)
        self._escapes.append(escape)

    def original(self, start: int, end: int) -> tuple[int, int]:
        """The original span of the decoded span ``[start, end)``."""
        return self._origin(start), self._origin(end - 1, after=True)

    def _origin(self, index: int, *, after: bool = False) -> int:
        seg = bisect_right(self._starts, index) - 1
        if self._escapes[seg]:
            return self._origins[seg] + (self._escapes[seg] if after else 0)
        return self._origins[seg] + index - self._starts[seg] + (1 if after else 0)


def _unescape(match: re.Match[str]) -> str:
    if match.group("pct"):
        return chr(int(match.group("pct"), 16))
    if match.group("uni"):
        return chr(int(match.group("uni"), 16))
    if match.group("slash"):
        return "/"
    decoded = html.unescape(match.group(0))
    return decoded if len(decoded) == 1 else "\ufffd"


def _windows(needle: str, size: int) -> set[str]:
    if len(needle) <= size:
        return {needle}
    return {needle[i : i + size] for i in range(len(needle) - size + 1)}


def _token_windows(token: str) -> set[str]:
    """The fragments of a Basic token that carry at least 4 bytes of the password.

    The token's first characters encode only ``username:``. A window made mostly
    of them would match any other credential for the same user (a legitimate
    value), so windows start where at least 4 password bytes are covered.
    """
    try:
        colon = base64.b64decode(token + "=" * (-len(token) % 4)).index(b":")
    except ValueError:  # not base64, or no separator: every window counts
        return _windows(token, BASE64_FRAGMENT)
    # Window i covers bytes [6i/8, 6i/8 + 6); password bytes start at colon + 1.
    start = max(0, math.ceil((colon + 1 - 2) * 8 / 6))
    tail = token[start:]
    if len(tail) < BASE64_FRAGMENT:
        return {token}
    return _windows(tail, BASE64_FRAGMENT)


def _covered(
    haystack: str, windows: set[str], *, ignore_case: bool = False
) -> list[tuple[int, int]]:
    """Every span of ``haystack`` that some window covers (overlapping matches)."""
    probe = haystack.lower() if ignore_case else haystack
    if not any((w.lower() if ignore_case else w) in probe for w in windows):
        return []  # the common case, decided by C-speed substring search
    # Longest first, so at each position the longest window wins the alternation.
    alternatives = "|".join(map(re.escape, sorted(windows, key=lambda w: (-len(w), w))))
    pattern = re.compile(f"(?=({alternatives}))", re.IGNORECASE if ignore_case else 0)
    return [(m.start(1), m.end(1)) for m in pattern.finditer(haystack)]


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def quotes_sent_auth(
    text: str, response: httpx.Response, *, username: object = None, password: object = None
) -> bool:
    """Whether a reply quotes the credentials its request sent, in any spelling.

    For success replies: such a body is a peer echoing the request, not device
    data, and the client refuses it rather than altering it. The configured
    *plain* password does not count -- a device legitimately stores it in other
    parameters (an administrator password reused as the proxy password), so it
    would refuse real data. Non-string text and mocks answer ``False``.
    """
    if not isinstance(text, str):
        return False
    creds = _Credentials(response, username, password)
    if any(header in text for header in creds.headers):
        return True
    return bool(creds.spans(_View(text)))


def redact_sent_auth(
    text: str, response: httpx.Response, *, username: object = None, password: object = None
) -> str:
    """Remove the credentials a request sent from the text its response carries.

    Call this on device text *before* it is truncated into an error message.
    The request's ``Authorization`` value is replaced whole first; then every
    span covered by a fragment of a Basic token or a Digest ``response`` hash,
    in any common spelling, and of the configured plain password (4 characters
    or more), is replaced. Nothing else in a Digest header (realm, nonce,
    cnonce, username) is a credential.

    Genuine Axis text never contains the request's own credential, so this is a
    no-op on it. A response without a request, or mocks, contribute nothing.
    """
    if not isinstance(text, str):
        return text
    creds = _Credentials(response, username, password)
    for header in sorted(creds.headers, key=len, reverse=True):
        text = text.replace(header, REDACTED)
    plain = password if isinstance(password, str) and len(password) >= MIN_PASSWORD else None
    view = _View(text)
    for start, end in reversed(creds.spans(view, plain)):
        first, last = view.original(start, end)
        text = text[:first] + REDACTED + text[last:]
    return text


def error_excerpt(
    text: str,
    response: httpx.Response,
    *,
    username: object = None,
    password: object = None,
    limit: int = 200,
) -> str:
    """The part of an error body that is safe to quote: redacted, then cut.

    A body that dumps the request headers (``Authorization: ...``) is withheld
    outright: it has no diagnostic value and every reason to hold a credential.
    """
    if not isinstance(text, str):
        return ""
    if _HEADER_DUMP.search(text):
        return f"[{len(text)} characters withheld: the reply quotes the request headers]"
    return redact_sent_auth(text, response, username=username, password=password)[:limit]


__all__ = [
    "BASE64_FRAGMENT",
    "HEX_FRAGMENT",
    "MIN_PASSWORD",
    "REDACTED",
    "SECRET_NAME",
    "credential_names",
    "error_excerpt",
    "is_secret_name",
    "quotes_sent_auth",
    "redact_sent_auth",
]
