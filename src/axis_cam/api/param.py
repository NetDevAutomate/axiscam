"""Parameter API module (``/axis-cgi/param.cgi``).

Device parameters are organised in dotted groups (``root.Network.eth0.IPAddress``)
and control most legacy settings. ``param.cgi?action=list`` answers
``text/plain`` with one ``<parameter>=<value>`` line per parameter; an invalid
request answers HTTP 200 with ``# Error: <description>``. This module parses
exactly that format (VAPIX Parameter management, fetched 2026-10-13) and always
sends ``responseformat=rfc`` as the documentation asks.

Parameters are read with ``action=list`` and written one at a time with
``action=update`` (:meth:`ParamAPI.set`), which is the only write the module
offers. An update travels in a POST form body, never in the URL. The restore
path in :mod:`axis_cam.restore` drives it through the plan → confirm → apply →
verify pattern.
"""

import re
from dataclasses import dataclass
from typing import Any

from defusedxml import ElementTree as DefusedElementTree

from axis_cam.api.base import BaseAPI
from axis_cam.api.registry import register
from axis_cam.exceptions import AxisApiNotSupportedError, AxisDeviceError
from axis_cam.models import DeviceParameter, ParameterGroup
from axis_cam.secrets import MIN_PASSWORD, REDACTED, error_excerpt, is_secret_name

ROOT_PREFIX = "root."


def _withhold_value(body: str, name: str, value: str) -> str:
    """``body`` with a credential parameter's sent value withheld.

    The refusal quotes the name and the value exactly (``Error setting '<name>'
    to '<value>'!``). AXIS OS 11 and 12 quote the *full* name although
    :meth:`ParamAPI.set` sends the short one (live, 2026-10-22); the VAPIX page
    writes the short form. Either spelling of that phrase is rebuilt with the
    value replaced, so the parameter name stays readable whatever the value is
    (a community string ``SNMP`` must not turn ``SNMP.ReadCommunity`` into
    ``[redacted].ReadCommunity``). Elsewhere the value is replaced only when it
    is 4 characters or more: shorter values match ordinary text (``e``, ``1``),
    and no substring rule can protect them anyway.
    """
    phrase = re.compile(
        rf"'((?:{re.escape(ROOT_PREFIX)})?{re.escape(short_name(name))})' to '{re.escape(value)}'"
    )
    pieces = []
    for index, piece in enumerate(phrase.split(body)):
        if index % 2:  # a captured name: the refusal phrase itself
            pieces.append(f"'{piece}' to '{REDACTED}'")
        elif len(value) >= MIN_PASSWORD:
            pieces.append(piece.replace(value, REDACTED))
        else:
            pieces.append(piece)
    return "".join(pieces)


def parse_param_list(text: str) -> dict[str, str]:
    """Parse ``action=list`` output into ``{full name: value}``.

    Keys are normalised to full names (``root.Group.Name``). The device echoes
    a *single-parameter* group the way the request spelled it — ``group=
    Image.I0.Name`` answers ``Image.I0.Name=...`` with no ``root.`` — while a
    real group always lists ``root.``-prefixed lines (AXIS OS 12.11, live).
    Values keep every character after the first ``=``, so a value containing
    ``=`` (a URL, a key) survives. Comment lines (``#``) and blanks are ignored.

    Raises:
        AxisDeviceError: The body is the CGI's ``# Error: <description>``.
    """
    stripped = text.strip()
    if stripped.startswith("# Error"):
        raise AxisDeviceError(f"param.cgi: {stripped.lstrip('# ')}")
    values: dict[str, str] = {}
    for raw_line in stripped.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if separator:
            values[full_name(name.strip())] = value
    return values


def full_name(name: str) -> str:
    """``Network.eth0.IPAddress`` → ``root.Network.eth0.IPAddress``."""
    return name if name.startswith(ROOT_PREFIX) else f"{ROOT_PREFIX}{name}"


def short_name(name: str) -> str:
    """``root.Network.eth0.IPAddress`` → ``Network.eth0.IPAddress``."""
    return name.removeprefix(ROOT_PREFIX)


def group_parameters(values: dict[str, str]) -> list[ParameterGroup]:
    """Organise a flat listing into top-level groups, sorted by group name.

    ``DeviceParameter.name`` is the name without ``root.``; ``group`` is the
    first component (``Network`` for ``root.Network.eth0.IPAddress``).
    """
    grouped: dict[str, list[DeviceParameter]] = {}
    for name, value in values.items():
        short = short_name(name)
        group = short.split(".", 1)[0] if short else "Other"
        grouped.setdefault(group, []).append(DeviceParameter(name=short, value=value, group=group))
    return [
        ParameterGroup(name=group, parameters=params) for group, params in sorted(grouped.items())
    ]


#: Privilege needed for an operation, as encoded in ``securityLevel`` digits.
#: 0 anonymous, 1 viewer, 4 operator, 6 admin, 7 root — i.e. nobody over VAPIX.
ACCESS_LEVELS: dict[str, str] = {
    "0": "anonymous",
    "1": "viewer",
    "4": "operator",
    "6": "admin",
    "7": "none",
}


@dataclass(frozen=True)
class ParamDefinition:
    """What ``listdefinitions`` says about one parameter.

    ``security_level`` is the raw four-digit code; the digits are the privilege
    needed to *add*, *remove*, *read* and *write* (``7`` = nobody). Evidence,
    AXIS OS 12.11 (M3216-LVE): ``Brand.Brand`` is ``7707`` (anyone reads, nobody
    writes); ``HTTPS.Enabled`` is ``7706``, which the Param API page documents
    as readable by viewer/operator/admin and writable; the 1200 parameters the
    beta Param API ``$export`` marks as writable are exactly the 1200 whose
    fourth digit is not ``7`` and the beta API drops.
    """

    name: str  # full name, root.Group.Name
    value: str
    security_level: str

    @property
    def writable(self) -> bool:
        """True unless the write digit says nobody may write."""
        return len(self.security_level) == 4 and self.security_level[3] != "7"

    @property
    def write_access(self) -> str:
        """Who may write: ``anonymous``/``viewer``/``operator``/``admin``/``none``."""
        if len(self.security_level) != 4:
            return "unknown"
        return ACCESS_LEVELS.get(self.security_level[3], "unknown")


def parse_param_definitions(xml: str) -> dict[str, ParamDefinition]:
    """Parse ``listdefinitions&listformat=xmlschema`` into ``{full name: definition}``.

    The document is ``<parameterDefinitions><group name="root"><group ...>
    <parameter name= value= securityLevel=/>``; names are rebuilt from the
    nesting. Parsed with defusedxml: the body comes from the network.

    Raises:
        AxisDeviceError: The body is not that document (``# Error`` or HTML).
    """
    stripped = xml.strip()
    if stripped.startswith("# Error"):
        raise AxisDeviceError(f"param.cgi: {stripped.lstrip('# ')}")
    try:
        root = DefusedElementTree.fromstring(stripped)
    except (DefusedElementTree.ParseError, ValueError) as exc:
        raise AxisDeviceError(f"param.cgi: listdefinitions did not return XML: {exc}") from exc

    definitions: dict[str, ParamDefinition] = {}

    def walk(element: Any, path: tuple[str, ...]) -> None:
        for child in element:
            tag = child.tag.rsplit("}", 1)[-1]
            name = child.get("name")
            if name is None:
                continue
            if tag == "group":
                walk(child, (*path, name))
            elif tag == "parameter":
                full = full_name(".".join((*path, name)))
                definitions[full] = ParamDefinition(
                    name=full,
                    value=child.get("value", ""),
                    security_level=child.get("securityLevel", ""),
                )

    walk(root, ())
    return definitions


@register
class ParamAPI(BaseAPI):
    """Read device parameters via ``param.cgi``.

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     ip = await camera.params.get("Network.eth0.IPAddress")
        ...     network = await camera.params.get_group("Network")
        ...     everything = await camera.params.export()   # {"root.X.Y": "value", ...}
    """

    name = "params"
    api_id = None  # legacy CGI; always available

    CGI_PATH = "/axis-cgi/param.cgi"

    async def _list(self, group: str | None = None) -> dict[str, str]:
        """``action=list`` for one group (or everything), parsed.

        Raises:
            AxisDeviceError: Invalid group (``# Error`` body) or HTTP error.
            AxisAuthenticationError / AxisConnectionError: Propagate.
        """
        params: dict[str, Any] = {"action": "list", "responseformat": "rfc"}
        if group:
            params["group"] = short_name(group)
        return parse_param_list(await self._get_text(self.CGI_PATH, params))

    async def get(self, param_name: str) -> str | None:
        """Get a single parameter value.

        Args:
            param_name: Full or short name (``root.Network.eth0.IPAddress`` or
                ``Network.eth0.IPAddress``).

        Returns:
            The value, or ``None`` if the device has no such parameter.
        """
        try:
            values = await self._list(param_name)
        except (AxisDeviceError, AxisApiNotSupportedError):
            return None
        return values.get(full_name(param_name))

    async def get_group(self, group_name: str) -> ParameterGroup:
        """Get all parameters in a group.

        Args:
            group_name: ``Network`` or ``root.Network`` (nested groups such as
                ``Network.eth0`` work too).

        Returns:
            ParameterGroup named after the top-level group; empty if the group
            does not exist.
        """
        top_level = short_name(group_name).split(".", 1)[0]
        try:
            values = await self._list(group_name)
        except (AxisDeviceError, AxisApiNotSupportedError):
            return ParameterGroup(name=top_level)
        return ParameterGroup(
            name=top_level,
            parameters=[p for group in group_parameters(values) for p in group.parameters],
        )

    async def get_all(self) -> list[ParameterGroup]:
        """Get every parameter the account may read, organised by top-level group.

        Errors propagate: an empty list means the device listed nothing, not
        that the request failed.
        """
        return group_parameters(await self._list())

    async def get_many(self, param_names: list[str]) -> dict[str, str | None]:
        """Get several parameters in one request.

        Returns:
            Mapping of the names as given to their values (``None`` if absent).
        """
        if not param_names:
            return {}
        try:
            values = await self._list(",".join(short_name(n) for n in param_names))
        except (AxisDeviceError, AxisApiNotSupportedError):
            return dict.fromkeys(param_names)
        return {name: values.get(full_name(name)) for name in param_names}

    async def search(self, pattern: str) -> list[DeviceParameter]:
        """Parameters whose name contains ``pattern`` (case-insensitive)."""
        needle = pattern.lower()
        return [
            param
            for group in await self.get_all()
            for param in group.parameters
            if needle in param.name.lower()
        ]

    async def export(self) -> dict[str, str]:
        """The whole parameter tree as the device lists it: ``{"root.X.Y": value}``.

        One shape, always: full names as keys. This is the backup payload and
        what ``param.cgi?action=update`` consumes on restore.
        """
        return await self._list()

    async def definitions(self) -> dict[str, ParamDefinition]:
        """``action=listdefinitions``: every parameter with its access levels.

        This is how a caller learns, before writing, which parameters the
        device will refuse (``ParamDefinition.writable``). Large (~400 KB on
        a camera) — call it once, not per parameter.

        Raises:
            AxisDeviceError: Not the XML document (``# Error`` or HTML).
            AxisAuthenticationError / AxisConnectionError: Propagate.
        """
        params: dict[str, Any] = {"action": "listdefinitions", "listformat": "xmlschema"}
        return parse_param_definitions(await self._get_text(self.CGI_PATH, params))

    async def set(self, param_name: str, value: str) -> None:
        """Update one existing parameter (``action=update``), in a POST form body.

        The arguments never go in the URL: a credential parameter's value would
        reach the device access log, httpx's request log, any proxy's log and a
        peer that echoes URLs. param.cgi reads a form body exactly as it reads
        the query string (VAPIX: GET/POST; live on AXIS OS 11 and 12, 2026-10-22).

        The device answers HTTP 200 with ``OK`` on success and HTTP 200 with
        ``# Error: Error setting '<group.name>' to '<value>'!`` for a parameter
        it does not have (and, per VAPIX, an invalid value). A parameter nobody
        may write (``listdefinitions`` write level 7, e.g. ``Brand.Brand``) gets
        **HTTP 401** instead, on AXIS OS 11 and 12 alike (live, 2026-10-22),
        which raises :class:`AxisAuthenticationError`; check
        ``ParamDefinition.writable`` first (filed as F14). Only the device knows
        which parameters are writable; callers should treat a refusal as a
        per-parameter fact, not a transport failure.

        Args:
            param_name: Full or short name.
            value: New value, as a string.

        Raises:
            AxisDeviceError: The device refused the update (``# Error`` body), or
                answered something else (a redirect turns the POST into a
                bodyless GET, which never reads ``OK``). For a credential-named
                parameter the value is withheld from the message: the device's
                refusal quotes it, and an echoing peer may re-spell it.
            AxisAuthenticationError: Wrong credentials, or a parameter nobody
                may write (the device answers 401; see above).
            AxisConnectionError: Propagate.
        """
        name = short_name(param_name)
        secrets = (value,) if value and is_secret_name(param_name) else ()
        raw = (
            await self._post_form(self.CGI_PATH, {"action": "update", name: value}, secrets=secrets)
        ).strip()
        if raw == "OK":  # decided before any redaction: a value can spell "OK"
            return
        if raw.startswith("# Error"):
            body = _withhold_value(raw, name, value) if secrets else raw
            raise AxisDeviceError(f"param.cgi: {body.removeprefix('#').strip()}")
        excerpt = error_excerpt(raw, password=self._client.password, secrets=secrets, limit=120)
        raise AxisDeviceError(f"param.cgi: unexpected reply to update: {excerpt!r}")

    # Convenience methods for common parameters

    async def get_friendly_name(self) -> str:
        """User-assigned device name, or ``""``."""
        return await self.get("root.Properties.FriendlyName") or ""

    async def get_location(self) -> str:
        """Device location description, or ``""``."""
        return await self.get("root.Properties.Location") or ""

    async def get_ip_address(self) -> str:
        """Primary IPv4 address, or ``""``."""
        values = await self.get_many(
            [
                "root.Network.eth0.IPAddress",
                "root.Network.VolatileHostName.IPv4Address",
                "root.Network.IPv4.Address",
            ]
        )
        return next((v for v in values.values() if v), "")

    async def get_mac_address(self) -> str:
        """MAC address of ``eth0``, or ``""``."""
        return await self.get("root.Network.eth0.MACAddress") or ""
