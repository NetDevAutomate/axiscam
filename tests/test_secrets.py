"""``axis_cam.secrets``: credential parameter names, and the request's own credentials.

The library quotes device text in its error messages. A peer that echoes the
request (a proxy, a WAF, a debug page, a broken or hostile device) can put the
credentials this client sent into that text, in any of the usual spellings, and
a truncation can cut them in half past any later whole-string scrubber. These
tests build real ``httpx`` requests, so the header is exactly what the client
sends. Decision record: ``docs/plans/2026-10-15-secrets-boundary-decision.md``.
"""

from __future__ import annotations

import base64
import json
import urllib.parse
from unittest.mock import MagicMock

import httpx
import pytest

from axis_cam.secrets import REDACTED, error_excerpt, quotes_sent_auth, redact_sent_auth

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


def _response(authorization: str | None, status: int = 500) -> httpx.Response:
    headers = {"Authorization": authorization} if authorization else {}
    request = httpx.Request("GET", "https://192.0.2.10/axis-cgi/param.cgi", headers=headers)
    return httpx.Response(status, text="", request=request)


def _fragments(secret: str, size: int) -> list[str]:
    return [secret[i : i + size] for i in range(len(secret) - size + 1)]


def _leaks(text: str, secret: str, size: int = 8) -> list[str]:
    folded = text.lower()
    return [f for f in _fragments(secret.lower(), size) if f in folded]


def test_the_canary_token_exercises_every_base64_special_character():
    assert "+" in TOKEN and "/" in TOKEN and TOKEN.endswith("=")


class TestBasic:
    def test_the_echoed_header_is_redacted_whole(self):
        text = f"<p>you sent: Authorization: {BASIC}</p>"
        assert redact_sent_auth(text, _response(BASIC)) == (
            f"<p>you sent: Authorization: {REDACTED}</p>"
        )

    def test_the_bare_token_is_redacted(self):
        text = f'{{"auth": "{TOKEN}"}}'
        assert redact_sent_auth(text, _response(BASIC)) == f'{{"auth": "{REDACTED}"}}'

    @pytest.mark.parametrize(
        ("label", "spelling"),
        [
            ("url-encoded", urllib.parse.quote(TOKEN, safe="")),
            (
                "url-encoded, lower-case escapes",
                urllib.parse.quote(TOKEN, safe="")
                .replace("%2B", "%2b")
                .replace("%2F", "%2f")
                .replace("%3D", "%3d"),
            ),
            ("json, escaped slashes", TOKEN.replace("/", "\\/")),
            ("json, unicode escapes", TOKEN.replace("/", "\\u002f").replace("+", "\\u002b")),
            ("padding stripped", TOKEN.rstrip("=")),
            ("base64url", TOKEN.replace("+", "-").replace("/", "_")),
        ],
    )
    def test_every_common_spelling_of_the_token_is_redacted(self, label: str, spelling: str):
        out = redact_sent_auth(f"echo: {spelling}.", _response(BASIC))
        assert _leaks(out, TOKEN) == [], label
        assert out.startswith("echo: ") and out.endswith(".")

    def test_a_base64url_echo_of_a_token_with_no_plain_window_is_redacted(self):
        # Every 8-character window past the username part holds a "+" or "/",
        # so only folding base64url back onto base64 can match it: the canary
        # above cannot show that (its plain windows match without folding).
        password = "~1?~~AA~?~"  # pragma: allowlist secret
        token = base64.b64encode(f"{USER}:{password}".encode()).decode()
        body = token[4:]
        assert all(set(body[i : i + 8]) & {"+", "/"} for i in range(len(body) - 7))
        url_form = token.replace("+", "-").replace("/", "_")
        out = redact_sent_auth(f"tok={url_form}", _response(f"Basic {token}"))
        assert _leaks(out, url_form[4:]) == []

    @pytest.mark.parametrize(
        ("password", "encode"),
        [
            ("-?A~A~~~??A~1>", lambda t: urllib.parse.quote(t, safe="")),
            ("A-1?1?", lambda t: t.replace("/", "\\/")),
            ("~11?-A", lambda t: t.replace("+", "\\u002b").replace("/", "\\u002f")),
        ],
        ids=["url-encoded", "json-slash", "json-unicode"],
    )
    def test_an_escaped_echo_of_a_dense_token_is_redacted(self, password, encode):
        # Each password is chosen so that no 8-character window of its token
        # survives the escaping (asserted): only undoing the escapes can match.
        token = base64.b64encode(f"{USER}:{password}".encode()).decode()
        body = token.rstrip("=")[4:]
        echo = encode(token)
        assert not any(window in echo for window in _fragments(token[4:], 8))
        out = redact_sent_auth(f"echo {echo} end", _response(f"Basic {token}"))
        decoded = urllib.parse.unquote(out).replace("\\/", "/")
        decoded = decoded.replace("\\u002b", "+").replace("\\u002f", "/")
        assert _leaks(decoded, body) == []
        assert out.startswith("echo ") and out.endswith(" end")

    def test_no_fragment_survives_a_truncation_across_the_token(self):
        # The worst case: the cut falls in the middle of the token.
        text = "." * (200 - len("Basic ") - len(TOKEN) // 2) + BASIC
        assert TOKEN[:8] in text[:200]  # the precondition: unredacted, it leaks
        cut = redact_sent_auth(text, _response(BASIC))[:200]
        assert _leaks(cut, TOKEN) == []

    def test_a_token_the_peer_already_cut_short_is_redacted(self):
        fragment = TOKEN[8:22]  # 14 characters of the password part, no header
        out = redact_sent_auth(f"x {fragment} y", _response(BASIC))
        assert _leaks(out, TOKEN[8:]) == []
        assert out.startswith("x ") and out.endswith(" y")

    def test_fragments_below_the_bar_are_left_alone(self):
        # 7 base64 characters (about 5 bytes) is below the 8-character bar.
        out = redact_sent_auth(f"x {TOKEN[9:16]} y", _response(BASIC))
        assert TOKEN[9:16] in out

    def test_the_username_part_of_the_token_is_not_a_credential(self):
        # The first characters encode only "root:" and the start of the password.
        # Another credential for the same user (legitimate data) whose password
        # starts with the same three letters shares them, and must not be hit.
        other = base64.b64encode(b"root:Unix-other-thing").decode()
        assert other[:10] == TOKEN[:10]
        out = redact_sent_auth(f"value={other}", _response(BASIC))
        assert out == f"value={other}"

    def test_the_configured_token_is_redacted_when_this_request_sent_digest(self):
        # AUTO mode sends Basic first and retries with Digest on the same Request,
        # so the final request no longer carries the Basic token it sent.
        text = "." * 180 + BASIC
        out = redact_sent_auth(text, _response(DIGEST), username=USER, password=PASSWORD)
        assert _leaks(out, TOKEN) == []


class TestDigest:
    def test_the_echoed_header_is_redacted_whole(self):
        text = f"Authorization: {DIGEST}"
        assert redact_sent_auth(text, _response(DIGEST)) == f"Authorization: {REDACTED}"

    def test_the_response_hash_is_redacted_on_its_own(self):
        # A JSON echo escapes the header's quotes, so only the hash itself matches.
        text = f'{{"response": "{DIGEST_RESPONSE}"}}'
        assert redact_sent_auth(text, _response(DIGEST)) == f'{{"response": "{REDACTED}"}}'

    def test_an_upper_cased_hash_is_redacted(self):
        out = redact_sent_auth(f"response={DIGEST_RESPONSE.upper()}", _response(DIGEST))
        assert _leaks(out, DIGEST_RESPONSE, 12) == []

    def test_a_hash_fragment_of_twelve_hex_characters_is_redacted(self):
        out = redact_sent_auth(f"r={DIGEST_RESPONSE[:16]}", _response(DIGEST))
        assert _leaks(out, DIGEST_RESPONSE, 12) == []

    def test_the_rest_of_a_digest_header_is_not_a_credential(self):
        # nonce, cnonce, realm and username are not secret: only the hash is removed.
        text = 'nonce="0001c2d3" realm="AXIS_ACCC8E0000AA"'
        assert redact_sent_auth(text, _response(DIGEST)) == text


class TestConfiguredPassword:
    @pytest.mark.parametrize(
        "spelling",
        [PASSWORD, urllib.parse.quote(PASSWORD, safe=""), urllib.parse.quote_plus(PASSWORD)],
    )
    def test_the_password_is_redacted_in_its_common_spellings(self, spelling: str):
        out = redact_sent_auth(f"user root pass {spelling}", _response(BASIC), password=PASSWORD)
        assert _leaks(out, PASSWORD) == []

    def test_a_password_shorter_than_four_characters_is_not_hunted(self):
        # Three characters match ordinary words; no substring rule can protect them.
        out = redact_sent_auth("abc abcdef", _response(None), password="abc")
        assert out == "abc abcdef"


class TestNothingToRedact:
    def test_genuine_device_text_is_unchanged(self):
        text = "# Error: Error setting 'Image.I0.Name' to 'Hall'!"
        assert redact_sent_auth(text, _response(BASIC), username=USER, password=PASSWORD) == text

    def test_a_request_without_authorization(self):
        assert redact_sent_auth(f"echo {TOKEN}", _response(None)) == f"echo {TOKEN}"

    def test_a_response_built_without_a_request(self):
        # httpx raises RuntimeError from Response.request when none was attached.
        response = httpx.Response(500, text="oops")
        assert redact_sent_auth("oops", response) == "oops"

    def test_mocks_pass_through(self):
        # Unit tests across the suite pass MagicMock responses and clients.
        mock = MagicMock()
        out = redact_sent_auth("oops", mock, username=mock.username, password=mock.password)
        assert out == "oops"


class TestQuotesSentAuth:
    """The refusal test for a success reply: does it quote what this request sent?"""

    @pytest.mark.parametrize(
        "text",
        [
            f"root.Echo={BASIC}",
            urllib.parse.quote(TOKEN, safe=""),
            json.dumps({"seen": TOKEN.replace("/", "\\/")}),
            TOKEN[8:20],
            DIGEST_RESPONSE.upper(),
        ],
    )
    def test_any_spelling_or_fragment_of_a_sent_credential(self, text: str):
        response = _response(BASIC if "Basic" in text or "%" in text else DIGEST, 200)
        assert quotes_sent_auth(text, response, username=USER, password=PASSWORD)

    def test_the_plain_password_alone_is_data_not_an_echo(self):
        # An administrator password reused as the proxy password is legitimate
        # device data; refusing it would break backups. (A stated limit.)
        text = f"root.Network.Proxy.Password={PASSWORD}\n"
        assert not quotes_sent_auth(text, _response(BASIC, 200), username=USER, password=PASSWORD)

    def test_genuine_text_and_mocks(self):
        assert not quotes_sent_auth("root.Image.I0.Name=Hall\n", _response(BASIC, 200))
        assert not quotes_sent_auth(MagicMock(), MagicMock())  # type: ignore[arg-type]


class TestErrorExcerpt:
    def test_a_dump_of_the_request_headers_is_withheld(self):
        body = json.dumps({"headers": {"Authorization": BASIC, "Accept": "*/*"}})
        out = error_excerpt(body, _response(BASIC, 404))
        assert _leaks(out, TOKEN) == []
        assert "withheld" in out and "request headers" in out
        assert str(len(body)) in out

    def test_ordinary_text_is_redacted_then_cut(self):
        text = "." * 190 + BASIC
        out = error_excerpt(text, _response(BASIC, 404), limit=200)
        assert len(out) <= 200
        assert _leaks(out, TOKEN) == []

    def test_genuine_axis_text_is_kept(self):
        text = "<h1>Not Found</h1>"
        assert error_excerpt(text, _response(BASIC, 404)) == text
