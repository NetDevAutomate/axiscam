"""``axis_cam.secrets``: credential parameter names, and the request's own credentials.

The library refuses any device reply that quotes the credentials its request
sent, and withholds an error excerpt that contains the configured password.
These tests pin what counts as "quotes": the header, the Basic token in every
common spelling and as fragments, the Digest ``response`` hash. They build real
``httpx`` requests so the header is exactly what the client sends. Decision
record: ``docs/plans/2026-10-15-secrets-boundary-decision.md`` (D1, D2, D6).
"""

from __future__ import annotations

import base64
import html
import json
import urllib.parse
from unittest.mock import MagicMock

import httpx
import pytest

from axis_cam.secrets import (
    BASE64_FRAGMENT,
    MIN_PASSWORD,
    contains_password,
    error_excerpt,
    quotes_sent_auth,
    token_windows,
)

USER = "root"
#: Chosen so the Basic token contains ``+``, ``/`` and ``=`` padding (asserted below).
PASSWORD = "Unit-T3st~~~?Pa55!"  # pragma: allowlist secret
TOKEN = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
BASIC = f"Basic {TOKEN}"
DIGEST_RESPONSE = "6629c513665a4ce987581eaac215e959"  # pragma: allowlist secret (made up)
DIGEST = (
    'Digest username="root", realm="AXIS_ACCC8E0000AA", nonce="0001c2d3", '
    f'uri="/axis-cgi/param.cgi", response="{DIGEST_RESPONSE}", qop=auth, nc=00000001, '
    'cnonce="a1b2c3d4"'
)


def _response(authorization: str | None, status: int = 200) -> httpx.Response:
    headers = {"Authorization": authorization} if authorization else {}
    request = httpx.Request("GET", "https://192.0.2.10/axis-cgi/param.cgi", headers=headers)
    return httpx.Response(status, text="", request=request)


def _fragments(secret: str, size: int) -> list[str]:
    return [secret[i : i + size] for i in range(len(secret) - size + 1)]


def test_the_canary_token_exercises_every_base64_special_character():
    assert "+" in TOKEN and "/" in TOKEN and TOKEN.endswith("=")


class TestBasic:
    @pytest.mark.parametrize(
        ("label", "spelling"),
        [
            ("the header", BASIC),
            ("the bare token", TOKEN),
            ("url-encoded", urllib.parse.quote(TOKEN, safe="")),
            (
                "url-encoded, lower-case escapes",
                urllib.parse.quote(TOKEN, safe="")
                .replace("%2B", "%2b")
                .replace("%2F", "%2f")
                .replace("%3D", "%3d"),
            ),
            ("url-encoded twice", urllib.parse.quote(urllib.parse.quote(TOKEN, safe=""), safe="")),
            ("json, escaped slashes", TOKEN.replace("/", "\\/")),
            ("json, unicode escapes", TOKEN.replace("/", "\\u002f").replace("+", "\\u002b")),
            ("html, numeric entities", TOKEN.replace("/", "&#x2F;").replace("+", "&#43;")),
            ("html5, named entities", TOKEN.replace("/", "&sol;").replace("+", "&plus;")),
            ("padding stripped", TOKEN.rstrip("=")),
            ("base64url", TOKEN.replace("+", "-").replace("/", "_")),
        ],
    )
    def test_every_common_spelling_of_the_token_is_detected(self, label: str, spelling: str):
        assert quotes_sent_auth(f"echo: {spelling}.", _response(BASIC)), label

    @pytest.mark.parametrize(
        ("password", "encode"),
        [
            ("-?A~A~~~??A~1>", lambda t: urllib.parse.quote(t, safe="")),
            (">>--~-", lambda t: urllib.parse.quote(urllib.parse.quote(t, safe=""), safe="")),
            ("A-1?1?", lambda t: t.replace("/", "\\/")),
            ("~11?-A", lambda t: t.replace("+", "\\u002b").replace("/", "\\u002f")),
            ("~11?-A", lambda t: t.replace("+", "&plus;").replace("/", "&sol;")),
            ("~1?~~AA~?~", lambda t: t.replace("+", "-").replace("/", "_")),
        ],
        ids=[
            "url-encoded",
            "url-encoded-twice",
            "json-slash",
            "json-unicode",
            "html5-entities",
            "base64url",
        ],
    )
    def test_an_escaped_echo_of_a_dense_token_is_detected(self, password, encode):
        # Each password is chosen so that no 8-character window of its token
        # survives the re-spelling (asserted): only undoing it can match. For
        # the twice-encoded case not even one decode leaves a window.
        token = base64.b64encode(f"{USER}:{password}".encode()).decode()
        echo = encode(token)
        assert not any(window in echo for window in _fragments(token[4:], BASE64_FRAGMENT))
        if "%25" in echo:
            once = urllib.parse.unquote(echo)
            assert not any(w in once for w in _fragments(token[4:], BASE64_FRAGMENT))
        assert quotes_sent_auth(f"echo {echo} end", _response(f"Basic {token}"))

    def test_a_token_the_peer_already_cut_short_is_detected(self):
        assert quotes_sent_auth(f"x {TOKEN[8:22]} y", _response(BASIC))

    def test_fragments_below_the_bar_are_not(self):
        # 7 base64 characters (about 5 bytes) is below the 8-character bar.
        assert not quotes_sent_auth(f"x {TOKEN[9:16]} y", _response(BASIC))

    def test_the_username_part_of_the_token_is_not_a_credential(self):
        # Another credential for the same user (legitimate data) whose password
        # starts with the same three letters shares the token's first characters.
        other = base64.b64encode(b"root:Unix-other-thing").decode()
        assert other[:10] == TOKEN[:10]
        assert not quotes_sent_auth(f"value={other}", _response(BASIC))

    def test_the_configured_token_counts_when_this_request_sent_digest(self):
        # AUTO mode sends Basic first and retries with Digest on the same Request,
        # so the final request no longer carries the Basic token it sent.
        response = _response(DIGEST)
        assert not quotes_sent_auth(f"seen: {BASIC}", response)
        assert quotes_sent_auth(f"seen: {BASIC}", response, username=USER, password=PASSWORD)

    def test_the_configured_token_counts_without_any_response(self):
        assert quotes_sent_auth(TOKEN, None, username=USER, password=PASSWORD)


class TestTokenWindows:
    """The fragment bar, against an oracle computed from bit offsets."""

    @staticmethod
    def _oracle(username: str, password: str) -> set[str]:
        raw = f"{username}:{password}".encode()
        token = base64.b64encode(raw).decode()
        first = raw.index(b":") + 1  # the first password byte
        if len(raw) - first < MIN_PASSWORD:
            return set()
        expected = set()
        for i in range(len(token) - BASE64_FRAGMENT + 1):
            lo, hi = 6 * i, 6 * (i + BASE64_FRAGMENT)  # the bits the window encodes
            whole = [j for j in range(first, len(raw)) if 8 * j >= lo and 8 * j + 8 <= hi]
            if len(whole) >= MIN_PASSWORD:
                expected.add(token[i : i + BASE64_FRAGMENT])
        return expected

    @pytest.mark.parametrize("username", ["", "a", "ab", "root", "admin", "jöhn", "用户"])
    @pytest.mark.parametrize(
        "password", ["abcd", "abcde", "Pa55-w0rd!", "pässwörd-用户", "a:b:c:d"]
    )
    def test_every_window_covering_four_password_bytes_and_no_other(self, username, password):
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        assert token_windows(token) == self._oracle(username, password)

    @pytest.mark.parametrize("password", ["", "a", "abc"])
    def test_a_password_under_four_bytes_has_no_fragments(self, password):
        # Only the whole token counts: a window would be mostly username.
        assert token_windows(base64.b64encode(f"abc:{password}".encode()).decode()) == set()


class TestDigest:
    def test_the_echoed_header_is_detected(self):
        assert quotes_sent_auth(f"Authorization: {DIGEST}", _response(DIGEST))

    @pytest.mark.parametrize(
        "spelling",
        [DIGEST_RESPONSE, DIGEST_RESPONSE.upper(), DIGEST_RESPONSE[:16], DIGEST_RESPONSE[10:22]],
        ids=["whole", "upper-case", "first-16", "middle-12"],
    )
    def test_the_hash_and_its_fragments_are_detected(self, spelling: str):
        assert quotes_sent_auth(f'{{"r": "{spelling}"}}', _response(DIGEST))

    def test_eleven_hex_characters_are_below_the_bar(self):
        assert not quotes_sent_auth(f"r={DIGEST_RESPONSE[:11]}", _response(DIGEST))

    def test_the_parameter_name_is_matched_without_case(self):
        header = DIGEST.replace("response=", "RESPONSE=")
        assert quotes_sent_auth(f"r={DIGEST_RESPONSE}", _response(header))

    def test_the_rest_of_a_digest_header_is_not_a_credential(self):
        # nonce, cnonce, realm and username are not secret: only the hash counts.
        text = 'nonce="0001c2d3" realm="AXIS_ACCC8E0000AA" username="root"'
        assert not quotes_sent_auth(text, _response(DIGEST))


class TestNothingToDetect:
    def test_genuine_device_text(self):
        text = "root.Image.I0.Name=Hall\n# Error: Error setting 'Image.I0.Name' to 'x'!\n"
        assert not quotes_sent_auth(text, _response(BASIC), username=USER, password=PASSWORD)

    def test_the_plain_password_alone_is_data_not_an_echo(self):
        # An administrator password reused as the proxy password is legitimate
        # device data; refusing it would break backups. (A stated limit.)
        text = f"root.Network.Proxy.Password={PASSWORD}\n"
        assert not quotes_sent_auth(text, _response(BASIC), username=USER, password=PASSWORD)

    def test_a_response_built_without_a_request(self):
        # httpx raises RuntimeError from Response.request when none was attached.
        assert not quotes_sent_auth(f"echo {TOKEN}", httpx.Response(200, text="x"))

    def test_mocks_pass_through(self):
        mock = MagicMock()
        assert not quotes_sent_auth("oops", mock, username=mock.username, password=mock.password)
        assert not quotes_sent_auth(mock, mock)  # type: ignore[arg-type]


class TestContainsPassword:
    @pytest.mark.parametrize(
        ("password", "spelling"),
        [
            (PASSWORD, PASSWORD),
            (PASSWORD, urllib.parse.quote(PASSWORD, safe="")),
            ("ab cd-pw", "ab+cd-pw"),  # form encoding
            ("päss-word", urllib.parse.quote("päss-word")),  # UTF-8 percent-encoding
            ('ab"cd-pw', 'ab\\"cd-pw'),  # JSON string escape
            ("ab\U0001f600cd", "ab\\ud83d\\ude00cd"),  # JSON surrogate pair
            ("a<b&c-pw", html.escape("a<b&c-pw")),
            ("a+b-pw", "a&plus;b-pw"),  # HTML5 named entity
        ],
    )
    def test_every_common_spelling(self, password: str, spelling: str):
        assert contains_password(f"pass={spelling};", password)

    def test_json_dumps_round_trip(self):
        assert contains_password(json.dumps({"pass": PASSWORD}), PASSWORD)

    def test_a_password_shorter_than_four_characters_is_not_hunted(self):
        assert not contains_password("abc abcdef", "abc")

    def test_mocks_and_missing_values(self):
        assert not contains_password("text", None)
        assert not contains_password("text", MagicMock())
        assert not contains_password(MagicMock(), "secret-value")  # type: ignore[arg-type]


class TestErrorExcerpt:
    def test_genuine_text_is_kept_and_cut(self):
        text = "<h1>Not Found</h1>" + "." * 300
        assert error_excerpt(text, password=PASSWORD) == text[:200]

    def test_an_excerpt_holding_the_configured_password_is_withheld(self):
        body = "." * 190 + f"user=root&pass={urllib.parse.quote_plus(PASSWORD)}"
        out = error_excerpt(body, password=PASSWORD)
        assert (
            out == f"[{len(body)} characters withheld: the reply contains the configured password]"
        )

    def test_without_a_configured_password(self):
        assert error_excerpt("<h1>Not Found</h1>") == "<h1>Not Found</h1>"
        assert error_excerpt(MagicMock()) == ""  # type: ignore[arg-type]

    def test_an_excerpt_quoting_a_secret_the_request_sent_is_withheld(self):
        # F6: a credential the request carried in its body (a parameter update's
        # value, a pwdgrp ``pwd``) is withheld like the configured password, in the
        # form-encoded spelling an echo of the body carries.
        sent = "Rd 9f/Q2+zX7kLm"  # pragma: allowlist secret
        body = "." * 190 + "SNMP.ReadCommunity=" + urllib.parse.quote_plus(sent)
        out = error_excerpt(body, password=PASSWORD, secrets=(sent,))
        assert out == (
            f"[{len(body)} characters withheld: the reply quotes a credential this request sent]"
        )

    def test_a_short_or_empty_sent_secret_is_not_hunted(self):
        # Under 4 characters a value matches ordinary text, as for the password.
        text = "<h1>Bad Request</h1> value 1"
        assert error_excerpt(text, secrets=("1", "")) == text


class TestEverythingTheClientSent:
    """``sent``: every Authorization value the client sent is a needle (milestone-3 council)."""

    HASH = "0123456789abcdef0123456789abcdef"  # pragma: allowlist secret
    DIGEST = (
        f'Digest username="root", realm="r", nonce="n", uri="/a", response="{HASH}", '
        'qop=auth, nc=00000001, cnonce="c"'
    )

    def test_an_earlier_digest_hash_is_found(self):
        assert quotes_sent_auth(f'seen response="{self.HASH}"', None, sent=[self.DIGEST])

    def test_an_earlier_header_verbatim_is_found(self):
        assert quotes_sent_auth(f"echo: {self.DIGEST}", None, sent=[self.DIGEST])

    def test_a_fragment_inside_a_longer_upper_case_hex_run_is_found(self):
        text = "id=deadbeef" + self.HASH[2:16].upper() + "cafe"
        assert quotes_sent_auth(text, None, sent=[self.DIGEST])

    def test_unrelated_hex_is_not(self):
        # A long hex run that is not a window of the Digest response (a device serial,
        # a stored checksum) must not be mistaken for the hash.
        hexish = "deadbeefcafef00d1234567890abcdef"  # pragma: allowlist secret
        assert not quotes_sent_auth(f"checksum {hexish}", None, sent=[self.DIGEST])

    def test_a_sent_basic_header_is_found_by_its_fragments(self):
        token = base64.b64encode(b"root:Sent-Basic~T3st?").decode()
        assert quotes_sent_auth(f"x{token[4:20]}x", None, sent=[f"Basic {token}"])


class TestPasswordSpellingsLowerHex:
    """UTF-8 percent-encoding with lower-case hex (milestone-3 council, Opus F7)."""

    def test_lower_case_percent_encoding_of_a_non_ascii_password(self):
        import re

        password = "Pässwörd Ünïcode-1"  # pragma: allowlist secret
        upper = urllib.parse.quote(password, safe="")
        lower = re.sub(r"%[0-9A-F]{2}", lambda m: m.group(0).lower(), upper)
        assert lower != upper  # precondition: it has escapes with letters
        assert contains_password(f"reason: {lower}", password)
        assert contains_password(f"reason: {lower.replace('%20', '+')}", password)  # form style
