"""The MCP secrets boundary over the real credential path.

The fake-backed boundary tests (``test_mcp_read_tools``, ``test_mcp_plan_tools``)
give the server a ``FakeDevice`` and a resolver that already holds the canary. They
never build an HTTP client, so they cannot show that what the server scrubs is what
actually went over the wire. Here nothing below the MCP server is faked except the
network::

    config.yaml (canary) -> load_config -> ConfigResolver -> DeviceConnection
        -> AxisCamera -> VapixClient -> VapixAuth -> httpx -> respx (the device)

The device is a legacy-CGI Axis camera (no ``/config/discover/apis``, every REST
path 404) in the two authentication behaviours seen on the live fleet on
2026-10-13: AXIS OS 12 offering only Basic over HTTPS, and 11.x offering only
Digest. It checks credentials for real -- Basic by token, Digest by recomputing the
``response`` from the canary -- so a run in which nothing authenticated cannot pass
as clean.

The needles are the canary, every Basic token and Digest ``response`` the device
received, and each credential the device holds as a parameter: the proxy password
is the admin password reused (the Scrubber's case), the SNMP communities and the
802.1X key password are distinct values (name-based redaction's case). A
credential cut in half by a truncation is still a credential, so fragments count.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import html
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any, Literal

import httpx
import mcp.types as t
import pytest
import respx
from mcp import Client

from axis_cam.api.param import ParamAPI
from axis_cam.client import VapixClient
from axis_cam.config import load_config
from axis_cam.exceptions import AxisParamNotWritableError
from axis_cam.mcp_server.devices import ConfigResolver
from axis_cam.mcp_server.redact import REDACTED
from axis_cam.mcp_server.server import TOOL_NAMES, build_server, resource_module_names

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from pathlib import Path

HOST = "192.0.2.10"  # TEST-NET-1 (RFC 5737): nothing real answers here
USER = "root"
#: Chosen so the Basic token contains ``+``, ``/`` and ``==`` (asserted below): a
#: token without them cannot show an echo that re-spells those characters.
CANARY = "Canary-W1re-S3cret~~~?a"  # pragma: allowlist secret
BASIC_TOKEN = base64.b64encode(f"{USER}:{CANARY}".encode()).decode()
SERIAL = "ACCC8E0000AA"
REALM = f"AXIS_{SERIAL}"
NONCE = "0001c2d3QxNjZjYTRmNmE5ZDM4OGRiYmQ3YjQ1NzM0"

READ_COMMUNITY = "rd-9fQ2zX7kLm"  # pragma: allowlist secret
WRITE_COMMUNITY = "wr-4Hk8Pq1VbN"  # pragma: allowlist secret
KEY_PASSWORD = "kp-2m6Td0HsWq"  # pragma: allowlist secret
PARAM_SECRETS = (CANARY, READ_COMMUNITY, WRITE_COMMUNITY, KEY_PASSWORD)

PARAMS: dict[str, str] = {
    "root.Brand.Brand": "AXIS",
    "root.Brand.ProdNbr": "M3216-LVE",
    "root.Properties.System.SerialNumber": SERIAL,
    "root.Image.I0.Name": "View Area 1",
    "root.Network.Bonjour.Enabled": "yes",
    "root.Network.UPnP.Enabled": "yes",
    "root.Network.Proxy.Password": CANARY,
    "root.Network.Interface.I0.dot1x.EAPOL.KeyPassword": KEY_PASSWORD,
    "root.SNMP.Enabled": "yes",
    "root.SNMP.ReadCommunity": READ_COMMUNITY,
    "root.SNMP.WriteCommunity": WRITE_COMMUNITY,
}
#: listdefinitions securityLevel digits are add/remove/read/write: 7 nobody, 6 admin.
READ_ONLY = frozenset(
    {"root.Brand.Brand", "root.Brand.ProdNbr", "root.Properties.System.SerialNumber"}
)

Reflect = Literal["httpbin", "straddle", "urlencoded", "json-slash", "replay", "ok-echo"]

#: basicdeviceinfo.cgi getAllProperties, the shape documented in device_info.py.
DEVICE_INFO = {
    "apiVersion": "1.3",
    "data": {
        "propertyList": {
            "Brand": "AXIS",
            "ProdNbr": "M3216-LVE",
            "ProdFullName": "AXIS M3216-LVE Dome Camera",
            "SerialNumber": SERIAL,
            "Version": "12.11.118",
        }
    },
}
#: pwdgrp.cgi?action=get, VAPIX System settings example 5 (verbatim).
PWDGRP = """admin="root,joe"
operator="root,joe,ellen"
viewer="root,joe,ellen,frank"
ptz="root,joe,ellen"
digusers="root,joe,ellen,frank"
"""
#: Apache 2.4's default 404 page.
NOT_FOUND = (
    '<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML 2.0//EN">\n<html><head>\n'
    "<title>404 Not Found</title>\n</head><body>\n<h1>Not Found</h1>\n"
    "<p>The requested URL was not found on this server.</p>\n</body></html>\n"
)


def _md5(text: str) -> str:
    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()  # RFC 7616 MD5


def _digest_fields(header: str) -> dict[str, str]:
    """The key=value pairs of a ``Digest`` Authorization header."""
    return urllib.request.parse_keqv_list(
        urllib.request.parse_http_list(header.removeprefix("Digest "))
    )


def _cgi_args(request: httpx.Request) -> dict[str, str]:
    """What param.cgi reads: the query string and a form body, alike.

    Live, 2026-10-22: two M3216-LVE (AXIS OS 12), an I8016-LVE and a C1410 (11.x,
    Digest) answer a POST form body exactly as they answer the same arguments in
    the query string.
    """
    args = dict(request.url.params)
    if request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
        args.update(urllib.parse.parse_qsl(request.content.decode()))
    return args


class Camera:
    """A legacy-CGI Axis camera behind respx that checks credentials for real.

    Args:
        scheme: The only scheme it offers: ``basic`` (AXIS OS 12, policy
            'recommended') or ``digest`` (11.x).
        password: The password it accepts; a different one models a client
            configured with the wrong password.
        reflect: What its pages echo. No Axis device echoes anything; these
            model a hostile or broken peer, or a proxy in front of one.
            ``httpbin``: the request headers as sorted JSON, like httpbin.
            ``straddle``: the Authorization header, placed so the credential in
            it (Basic token, Digest ``response``) spans the client's 200-character
            truncation of device text -- the adversarial worst case.
            ``urlencoded``: the header percent-encoded, straddling the cut.
            ``json-slash``: the header in JSON with ``/`` escaped (PHP style).
            ``replay``: the *first* header the device ever saw, straddling the
            cut. Against the Digest device that is AUTO mode's Basic attempt,
            which the request that gets the error page no longer carries.
            ``ok-echo``: the header appended to every successful param.cgi
            listing (HTTP 200), so the echo arrives as data, not as an error.
    """

    def __init__(
        self,
        scheme: Literal["basic", "digest"],
        *,
        password: str = CANARY,
        reflect: Reflect | None = None,
    ) -> None:
        self.scheme = scheme
        self.password = password
        self.reflect = reflect
        self.params = dict(PARAMS)
        #: Every Authorization header value the device received.
        self.received: list[str] = []
        #: Requests answered as authenticated.
        self.served = 0
        #: Every authenticated param.cgi ``action=update`` request.
        self.updates: list[httpx.Request] = []

    def needles(self) -> list[str]:
        """Every credential this device saw on the wire or holds as a parameter."""
        found = {BASIC_TOKEN, *PARAM_SECRETS}
        for header in self.received:
            if header.startswith("Basic "):
                found.add(header.removeprefix("Basic "))
            elif header.startswith("Digest "):
                found.add(_digest_fields(header)["response"])
        return sorted(found)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        header = request.headers.get("Authorization")
        if header:
            self.received.append(header)
        if not self._authenticated(request, header):
            return self._challenge()
        self.served += 1
        return self._route(request)

    # -- authentication ----------------------------------------------------------

    def _authenticated(self, request: httpx.Request, header: str | None) -> bool:
        if header is None:
            return False
        if self.scheme == "basic":
            token = base64.b64encode(f"{USER}:{self.password}".encode()).decode()
            return header == f"Basic {token}"
        if not header.startswith("Digest "):
            return False
        f = _digest_fields(header)
        if (f.get("username"), f.get("realm"), f.get("nonce")) != (USER, REALM, NONCE):
            return False
        if f.get("uri") != request.url.raw_path.decode():
            return False
        ha1 = _md5(f"{USER}:{REALM}:{self.password}")
        ha2 = _md5(f"{request.method}:{f['uri']}")
        expected = _md5(f"{ha1}:{NONCE}:{f['nc']}:{f['cnonce']}:{f['qop']}:{ha2}")
        return f.get("response") == expected

    def _challenge(self, body: str = "Unauthorized\n") -> httpx.Response:
        if self.scheme == "basic":
            value = f'Basic realm="{REALM}"'
        else:
            value = f'Digest realm="{REALM}", nonce="{NONCE}", algorithm=MD5, qop="auth"'
        return httpx.Response(401, headers={"WWW-Authenticate": value}, text=body)

    # -- endpoints ---------------------------------------------------------------

    def _route(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        query = dict(request.url.params)
        if path == "/axis-cgi/basicdeviceinfo.cgi" and request.method == "POST":
            return httpx.Response(200, json=DEVICE_INFO)
        if path == "/axis-cgi/pwdgrp.cgi" and query.get("action") == "get":
            return httpx.Response(200, text=PWDGRP)
        if path == "/axis-cgi/param.cgi":
            args = _cgi_args(request)
            if args.get("action") == "update":
                self.updates.append(request)
            return self._param_cgi(args, request.headers.get("Authorization", ""))
        return self._not_found(request)

    def _param_cgi(self, query: dict[str, str], header: str = "") -> httpx.Response:
        action = query.pop("action", None)
        query.pop("responseformat", None)
        if action == "list":
            echo = f"root.Debug.Seen={header}\n" if self.reflect == "ok-echo" else ""
            return httpx.Response(200, text=self._list(query.get("group")) + echo)
        if action == "listdefinitions":
            return httpx.Response(200, text=self._definitions())
        if action == "update":
            for short, value in query.items():
                full = f"root.{short}"
                if full in READ_ONLY:
                    # AXIS OS 11 and 12 (live, 2026-10-22): param.cgi's own 401, a
                    # challenge with no body, for a parameter nobody may write.
                    return self._challenge(body="")
                if full not in self.params:
                    return httpx.Response(
                        200, text=f"# Error: Error setting '{full}' to '{value}'!"
                    )
                self.params[full] = value
            return httpx.Response(200, text="OK")
        return httpx.Response(200, text="# Error: Unknown action\n")

    def _list(self, groups: str | None) -> str:
        """``action=list``: one parameter echoes as requested (no ``root.``, as live)."""
        if not groups:
            return "".join(f"{k}={v}\n" for k, v in self.params.items())
        lines: list[str] = []
        for group in groups.split(","):
            full = group if group.startswith("root.") else f"root.{group}"
            if full in self.params:
                lines.append(f"{group}={self.params[full]}\n")
            else:
                lines += [f"{k}={v}\n" for k, v in self.params.items() if k.startswith(full + ".")]
        return "".join(lines) or f"# Error: Error -1 getting param in group '{groups}'\n"

    def _definitions(self) -> str:
        """``listdefinitions&listformat=xmlschema``, nested groups, with current values."""
        tree: dict[str, Any] = {}
        for name, value in self.params.items():
            *groups, leaf = name.split(".")[1:]
            node = tree
            for group in groups:
                node = node.setdefault(group, {})
            node[leaf] = (value, "7707" if name in READ_ONLY else "7766")

        def render(node: dict[str, Any]) -> str:
            parts = []
            for key, child in node.items():
                if isinstance(child, dict):
                    parts.append(f'<group name="{key}">{render(child)}</group>')
                else:
                    value, level = child
                    parts.append(
                        f'<parameter name="{key}" value="{html.escape(value)}" '
                        f'securityLevel="{level}"/>'
                    )
            return "".join(parts)

        return (
            '<?xml version="1.0"?><parameterDefinitions version="1.0">'
            f'<group name="root">{render(tree)}</group></parameterDefinitions>'
        )

    #: Text a reflected error page puts in front of what it echoes.
    PAD = "."

    @property
    def marker(self) -> str:
        """A substring that reaches the output only if a reflected page did.

        Every reflection is refused by the client (``AxisEchoError``), whatever
        the status, so the refusal is the evidence the page arrived and was
        handled -- never a part of the page itself.
        """
        return "quotes this request's credentials" if self.reflect else ""

    @staticmethod
    def _secret_of(header: str) -> str:
        if header.startswith("Basic "):
            return header.removeprefix("Basic ")
        return _digest_fields(header)["response"]

    def _straddling(self, echoed: str, secret: str) -> httpx.Response:
        """A 404 whose body puts the middle of ``secret`` at character 200."""
        at = echoed.index(secret)
        pad = self.PAD * max(8, 200 - (at + len(secret) // 2))
        return httpx.Response(404, text=pad + echoed)

    def _not_found(self, request: httpx.Request) -> httpx.Response:
        if self.reflect in (None, "ok-echo"):
            return httpx.Response(404, text=NOT_FOUND, headers={"Content-Type": "text/html"})
        if self.reflect == "httpbin":
            echo = {
                "headers": {k.title(): v for k, v in sorted(request.headers.items())},
                "method": request.method,
                "url": str(request.url),
            }
            return httpx.Response(404, json=echo)
        header = request.headers["Authorization"]
        if self.reflect == "replay":
            header = self.received[0]
        if self.reflect == "json-slash":
            body = json.dumps({"reflected-by-peer": True, "echo": header})
            return httpx.Response(404, text=body.replace("/", "\\/"))
        secret = self._secret_of(header)
        if self.reflect == "urlencoded":
            return self._straddling(
                urllib.parse.quote(header, safe=""), urllib.parse.quote(secret, safe="")
            )
        return self._straddling(header, secret)


class Unreachable(Camera):
    """Every request fails in transport, after the client has built its headers."""

    def __init__(self, error: Callable[[httpx.Request], Exception]) -> None:
        super().__init__("basic")
        self.error = error

    def __call__(self, request: httpx.Request) -> httpx.Response:
        header = request.headers.get("Authorization")
        if header:
            self.received.append(header)
        raise self.error(request)


class Human:
    """An elicitation callback that approves and records what it was shown."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def __call__(self, context: Any, params: Any) -> t.ElicitResult:
        self.seen.append(params.message)
        return t.ElicitResult(action="accept", content={"approve": True})


_HEX = re.compile(r"[0-9a-f]+")
_UNICODE_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")


def _views(text: str) -> list[str]:
    """``text``, and ``text`` with the common echo escapes undone.

    Written with the standard library on purpose, independent of the code under
    test: percent-encoding, JSON ``\\/`` and ``\\uXXXX``, and base64url.
    """
    undone = _UNICODE_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), urllib.parse.unquote(text))
    undone = undone.replace("\\/", "/")
    return [text, undone, undone.replace("-", "+").replace("_", "/")]


def leaked(text: str, needles: Iterable[str]) -> list[str]:
    """Needles found in ``text``, in any common spelling, whole or as a fragment.

    A fragment is 8 characters, or 12 for a hex Digest hash, compared without
    case (an echo may upper-case hex).
    """
    views = _views(text)
    found = []
    for needle in needles:
        is_hex = bool(_HEX.fullmatch(needle.lower()))
        k = min(len(needle), 12 if is_hex else 8)
        probe = needle.lower() if is_hex else needle
        windows = {probe[i : i + k] for i in range(len(probe) - k + 1)}
        if any(w in (view.lower() if is_hex else view) for view in views for w in windows):
            found.append(needle)
    return found


def test_the_canary_token_exercises_every_base64_special_character():
    assert "+" in BASIC_TOKEN and "/" in BASIC_TOKEN and BASIC_TOKEN.endswith("==")


def _text(result: Any) -> str:
    return json.dumps(result.structured_content) + "".join(
        getattr(c, "text", "") for c in result.content
    )


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A config dir whose only device carries the canary; the cached loader cleared."""
    for key in [k for k in os.environ if k.startswith("AXIS_")]:
        monkeypatch.delenv(key)
    directory = tmp_path / "config"
    directory.mkdir()
    config = directory / "config.yaml"
    config.write_text(
        f"devices:\n  cam:\n    address: {HOST}\n    username: {USER}\n    password: '{CANARY}'\n"
    )
    config.chmod(0o600)
    monkeypatch.setenv("AXIS_CONFIG_DIR", str(directory))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    load_config.cache_clear()
    yield directory
    load_config.cache_clear()


@contextlib.contextmanager
def on_the_wire(camera: Camera) -> Iterator[None]:
    """Route every request to ``camera``; a request for any other host raises."""
    with respx.mock(assert_all_called=False) as router:
        router.route(host=HOST).mock(side_effect=camera)
        yield


class Session:
    """Calls tools and resources, keeping every output by surface."""

    def __init__(self, client: Client) -> None:
        self.client = client
        self.surfaces: dict[str, str] = {}
        self.called: set[str] = set()

    async def tool(self, name: str, args: dict[str, Any], label: str = "") -> Any:
        result = await self.client.call_tool(name, args)
        self.called.add(name)
        self.surfaces[f"tool {name} {label}".rstrip()] = _text(result)
        return result

    async def resource(self, uri: str) -> str:
        result = await self.client.read_resource(uri)
        text = "".join(getattr(c, "text", "") for c in result.contents)
        self.surfaces[f"resource {uri}"] = text
        return text


def _assert_nothing_leaked(surfaces: dict[str, str], needles: list[str]) -> None:
    leaks = {surface: leaked(text, needles) for surface, text in surfaces.items()}
    assert {surface: found for surface, found in leaks.items() if found} == {}


# --- every tool and resource, honest device ---------------------------------------


@pytest.mark.parametrize("scheme", ["basic", "digest"])
async def test_every_tool_and_resource_over_the_wire_leaks_no_credential(
    scheme: Literal["basic", "digest"],
    config_dir: Path,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG)
    camera = Camera(scheme)
    human = Human()
    dev = {"device": "cam"}
    server = build_server(ConfigResolver(), backup_root=tmp_path / "backups")
    with on_the_wire(camera):
        async with Client(server, elicitation_callback=human) as client:
            s = Session(client)
            await s.tool("list_devices", {})
            await s.tool("list_modules", dev)
            reads = {
                m: (await s.tool("read_module", {**dev, "module": m}, m)).structured_content
                for m in resource_module_names()
            }
            await s.tool("device_report", {**dev, "full": True})
            for op in ("info", "report", "audit"):
                await s.tool("fleet_read", {"selection": "all", "op": op}, op)
            pages = {
                prefix: (
                    await s.tool("query_params", {**dev, "prefix": prefix}, prefix)
                ).structured_content
                for prefix in ("Network.Proxy", "Network.Interface", "SNMP")
            }
            await s.tool("security_audit", dev)
            backup = (await s.tool("backup_create", dev)).structured_content
            await s.tool("backup_list", {})
            await s.tool("backup_verify", {"backup_id": backup["backup_id"]})
            await s.tool(
                "plan_account_change",
                {**dev, "account": "joe", "action": "set_role", "role": "viewer"},
            )
            camera.params["root.Image.I0.Name"] = "Changed"  # drift after the backup
            plan = (
                await s.tool("plan_restore", {**dev, "backup_id": backup["backup_id"]})
            ).structured_content
            applied = (await s.tool("apply_plan", {"plan_id": plan["plan_id"]})).structured_content
            await s.resource("axiscam://checks")
            await s.resource("axiscam://schemas/device_info")
            await s.resource(f"axiscam://backups/{backup['backup_id']}/manifest")

    # Coverage: a new tool or resource cannot skip this test.
    assert s.called == set(TOOL_NAMES)
    async with Client(server) as client:
        templates = {
            r.uri_template for r in (await client.list_resource_templates()).resource_templates
        }
        uris = {str(r.uri) for r in (await client.list_resources()).resources}
    assert len(templates | uris) == 3

    # Positive controls: the canary crossed the wire, the device accepted it, and
    # every path the needles could ride ran for real.
    assert camera.served > 50
    if scheme == "digest":
        assert any(h.startswith("Digest ") for h in camera.received)
    assert reads["device_info"]["status"] == "ok"
    assert reads["device_info"]["value"]["serial_number"] == SERIAL
    assert reads["users"]["status"] == "ok"
    secret_items = [i for page in pages.values() for i in page["items"] if i["redacted"]]
    assert {i["name"] for i in secret_items} == {k for k, v in PARAMS.items() if v in PARAM_SECRETS}
    assert {i["value"] for i in secret_items} == {REDACTED}
    assert plan["plan"]["changes"] == [
        {"name": "root.Image.I0.Name", "current": "Changed", "target": "View Area 1"}
    ]
    assert applied["status"] == "applied"
    assert camera.params["root.Image.I0.Name"] == "View Area 1"
    # F6: the write travelled in a form body; its URL carried no argument at all.
    assert camera.updates
    assert all(r.method == "POST" and r.url.query == b"" for r in camera.updates)
    assert len(human.seen) == 1 and SERIAL in human.seen[0]
    # httpx request logging is pinned to WARNING in MCP mode: request URLs carry the
    # device address and parameter names (writes go in the body since F6), and stderr
    # is the host's log. Nothing below WARNING.
    assert not any(r.name == "httpx" and r.levelno < logging.WARNING for r in caplog.records)

    captured = capfd.readouterr()
    assert captured.out == ""
    surfaces = {
        **s.surfaces,
        "elicitation": "\n".join(human.seen),
        "logs": caplog.text,
        "stderr": captured.err,
    }
    _assert_nothing_leaked(surfaces, camera.needles())


# --- failures on the wire -----------------------------------------------------------


def _connect_refused(request: httpx.Request) -> Exception:
    return httpx.ConnectError("[Errno 61] Connection refused", request=request)


def _read_timeout(request: httpx.Request) -> Exception:
    return httpx.ReadTimeout("timed out", request=request)


FAILURES: dict[str, Callable[[], Camera]] = {
    "basic, wrong password": lambda: Camera("basic", password="not-the-canary"),
    "digest, wrong password": lambda: Camera("digest", password="not-the-canary"),
    "basic, httpbin-style echo": lambda: Camera("basic", reflect="httpbin"),
    "digest, httpbin-style echo": lambda: Camera("digest", reflect="httpbin"),
    "basic, credential across the cut": lambda: Camera("basic", reflect="straddle"),
    "digest, credential across the cut": lambda: Camera("digest", reflect="straddle"),
    "basic, url-encoded across the cut": lambda: Camera("basic", reflect="urlencoded"),
    "digest, url-encoded across the cut": lambda: Camera("digest", reflect="urlencoded"),
    "basic, json-escaped echo": lambda: Camera("basic", reflect="json-slash"),
    "digest, json-escaped echo": lambda: Camera("digest", reflect="json-slash"),
    "basic, first header replayed": lambda: Camera("basic", reflect="replay"),
    "digest, AUTO's Basic attempt replayed": lambda: Camera("digest", reflect="replay"),
    "basic, echo in a success reply": lambda: Camera("basic", reflect="ok-echo"),
    "digest, echo in a success reply": lambda: Camera("digest", reflect="ok-echo"),
    "unreachable": lambda: Unreachable(_connect_refused),
    "timeout": lambda: Unreachable(_read_timeout),
}


@pytest.mark.parametrize("failure", list(FAILURES))
async def test_failures_on_the_wire_leak_no_credential(
    failure: str,
    config_dir: Path,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG)
    camera = FAILURES[failure]()
    dev = {"device": "cam"}
    server = build_server(ConfigResolver(), backup_root=tmp_path / "backups")
    with on_the_wire(camera):
        async with Client(server) as client:
            s = Session(client)
            await s.tool("list_modules", dev)
            for module in ("device_info", "ssh", "users", "onvif_users"):
                await s.tool("read_module", {**dev, "module": module}, module)
            await s.tool("device_report", {**dev, "full": True})
            await s.tool("fleet_read", {"selection": "all", "op": "info"})
            await s.tool("query_params", {**dev, "prefix": "SNMP"})
            await s.tool("security_audit", dev)
            await s.tool("backup_create", dev)

    # Positive controls: credentials went out, and device text reached the output.
    assert camera.received
    if camera.reflect:
        assert any(camera.marker in text for text in s.surfaces.values())

    captured = capfd.readouterr()
    assert captured.out == ""
    surfaces = {**s.surfaces, "logs": caplog.text, "stderr": captured.err}
    _assert_nothing_leaked(surfaces, camera.needles())


# --- a peer that echoes into every reply ---------------------------------------------


def _echo_everything(request: httpx.Request) -> httpx.Response:
    """A proxy that reflects the request into every 200, not only into param.cgi."""
    if request.headers.get("Authorization") != f"Basic {BASIC_TOKEN}":
        return httpx.Response(401, headers={"WWW-Authenticate": f'Basic realm="{REALM}"'})
    lines = "".join(f"{k}: {v}\n" for k, v in request.headers.items())
    return httpx.Response(200, text=f"{request.method} {request.url.path}\n{lines}")


@pytest.mark.parametrize("module", resource_module_names())
async def test_a_peer_echoing_every_reply_never_reads_as_ok(
    module: str, config_dir: Path, tmp_path: Path
) -> None:
    # Module methods that turn a device error into "API absent" defaults must not
    # swallow the refusal: a value read through an echoing peer is never "ok".
    server = build_server(ConfigResolver(), backup_root=tmp_path / "backups")
    with respx.mock(assert_all_called=False) as router:
        router.route(host=HOST).mock(side_effect=_echo_everything)
        async with Client(server) as client:
            result = await client.call_tool("read_module", {"device": "cam", "module": module})
    status = (result.structured_content or {}).get("status")
    assert result.is_error or status != "ok", result.structured_content
    assert leaked(_text(result), [BASIC_TOKEN, CANARY]) == []


# --- the library on the same wire ----------------------------------------------------


@pytest.mark.parametrize("scheme", ["basic", "digest"])
async def test_an_unwritable_parameter_is_its_own_refusal_over_either_scheme(
    scheme: Literal["basic", "digest"],
) -> None:
    # F14 through the real client and AUTO authentication: the camera answers an
    # update of a parameter nobody may write with param.cgi's own 401. A restore reads
    # the device before it writes; with Digest settled, httpx's DigestAuth retries the
    # 401 once (it spends its one retry on the unauthenticated first leg of a cold
    # client's first request), which is the two log lines per update on the C1410.
    camera = Camera(scheme)
    with on_the_wire(camera):
        async with VapixClient(HOST, USER, CANARY, port=443, use_https=True) as client:
            api = ParamAPI(client)
            assert await api.get("root.Image.I0.Name") == "View Area 1"  # as restore does
            with pytest.raises(AxisParamNotWritableError) as caught:
                await api.set("root.Brand.Brand", "Other")
            await api.set("root.Image.I0.Name", "Hall")  # the client still works

    assert camera.params["root.Brand.Brand"] == "AXIS"
    assert camera.params["root.Image.I0.Name"] == "Hall"
    assert "root.Brand.Brand" in str(caught.value) and "Other" not in str(caught.value)
    assert leaked(str(caught.value), camera.needles()) == []
    assert all(r.method == "POST" and r.url.query == b"" for r in camera.updates)
    assert len(camera.updates) == (3 if scheme == "digest" else 2)
