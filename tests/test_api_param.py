"""Tests for ParamAPI against the documented param.cgi text contract.

VAPIX Parameter management: ``action=list`` answers ``text/plain`` with one
``<parameter>=<value>`` line per parameter; an invalid request answers HTTP 200
with ``# Error: <description>``. Until 2026-10-13 this module parsed JSON and
every real device therefore produced empty results.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from axis_cam.api.param import (
    ParamAPI,
    full_name,
    group_parameters,
    parse_param_list,
    short_name,
)
from axis_cam.client import VapixClient
from axis_cam.exceptions import AxisAuthenticationError, AxisDeviceError
from axis_cam.models import DeviceParameter, ParameterGroup

# From the VAPIX page, example 3 ("only a small part of the response is shown").
DOC_EXAMPLE = """root.Network.Media=auto
root.Network.Autoneg=normal
root.Network.Enabled=yes
"""

LISTING = """root.Properties.FriendlyName=Front Door
root.Properties.Location=Building A, Entrance
root.Network.eth0.IPAddress=192.168.1.10
root.Network.eth0.MACAddress=AC:CC:8E:00:00:01
root.Network.Media=auto
root.Audio.MaxListeners=10
root.System.URL=https://example.com/a?b=c=d
"""


def _api(*bodies: str | Exception) -> tuple[ParamAPI, MagicMock]:
    client = MagicMock()
    client.host = "192.168.1.10"
    client.get = AsyncMock(
        side_effect=[b if isinstance(b, Exception) else MagicMock(text=b) for b in bodies]
    )
    return ParamAPI(client), client


def _requested(client) -> list[dict]:
    return [call.args[1] for call in client.get.await_args_list]


class TestParseParamList:
    def test_documented_example(self):
        assert parse_param_list(DOC_EXAMPLE) == {
            "root.Network.Media": "auto",
            "root.Network.Autoneg": "normal",
            "root.Network.Enabled": "yes",
        }

    def test_value_may_contain_equals_signs(self):
        assert parse_param_list(LISTING)["root.System.URL"] == "https://example.com/a?b=c=d"

    def test_empty_value_and_blank_and_comment_lines(self):
        assert parse_param_list("root.A.B=\n\n# a comment\nroot.A.C=x\n") == {
            "root.A.B": "",
            "root.A.C": "x",
        }

    def test_empty_body_is_no_parameters(self):
        assert parse_param_list("") == {}

    def test_error_body_raises(self):
        with pytest.raises(AxisDeviceError, match=r"param\.cgi: Error: No such group"):
            parse_param_list("# Error: No such group\n")

    def test_crlf_lines(self):
        assert parse_param_list("root.A.B=1\r\nroot.A.C=2\r\n") == {
            "root.A.B": "1",
            "root.A.C": "2",
        }


class TestNames:
    def test_full_and_short(self):
        assert full_name("Network.eth0.IPAddress") == "root.Network.eth0.IPAddress"
        assert full_name("root.Network.eth0.IPAddress") == "root.Network.eth0.IPAddress"
        assert short_name("root.Network.eth0.IPAddress") == "Network.eth0.IPAddress"
        assert short_name("Network") == "Network"

    def test_group_parameters(self):
        groups = group_parameters(parse_param_list(LISTING))

        assert [g.name for g in groups] == ["Audio", "Network", "Properties", "System"]
        network = next(g for g in groups if g.name == "Network")
        assert network.parameters[0] == DeviceParameter(
            name="Network.eth0.IPAddress", value="192.168.1.10", group="Network"
        )


class TestList:
    async def test_get_all_requests_everything_with_rfc_format(self):
        api, client = _api(LISTING)

        groups = await api.get_all()

        assert _requested(client) == [{"action": "list", "responseformat": "rfc"}]
        assert [g.name for g in groups] == ["Audio", "Network", "Properties", "System"]
        assert sum(len(g.parameters) for g in groups) == 7

    async def test_get_all_propagates_errors(self):
        api, _ = _api(AxisDeviceError("500"))

        with pytest.raises(AxisDeviceError):
            await api.get_all()

    async def test_get_group_strips_root_and_names_the_top_level_group(self):
        api, client = _api(
            "root.Network.eth0.IPAddress=192.168.1.10\nroot.Network.eth0.MACAddress=AC\n"
        )

        group = await api.get_group("root.Network.eth0")

        assert _requested(client) == [
            {"action": "list", "responseformat": "rfc", "group": "Network.eth0"}
        ]
        assert group.name == "Network"
        assert [p.name for p in group.parameters] == [
            "Network.eth0.IPAddress",
            "Network.eth0.MACAddress",
        ]

    async def test_get_group_unknown_is_empty(self):
        api, _ = _api("# Error: Error -1 getting param in group Nope\n")

        assert await api.get_group("Nope") == ParameterGroup(name="Nope")

    async def test_get_single_parameter(self):
        api, client = _api("root.Properties.FriendlyName=Front Door\n")

        value = await api.get("Properties.FriendlyName")

        assert value == "Front Door"
        assert _requested(client)[0]["group"] == "Properties.FriendlyName"

    async def test_get_accepts_full_name_too(self):
        api, _ = _api("root.Properties.FriendlyName=Front Door\n")
        assert await api.get("root.Properties.FriendlyName") == "Front Door"

    async def test_get_missing_parameter_is_none(self):
        api, _ = _api("# Error: Error -1 getting param in group Properties.Nope\n")
        assert await api.get("Properties.Nope") is None

    async def test_get_auth_error_propagates(self):
        api, _ = _api(AxisAuthenticationError("401"))
        with pytest.raises(AxisAuthenticationError):
            await api.get("Properties.FriendlyName")

    async def test_get_many_is_one_request(self):
        api, client = _api(
            "root.Properties.FriendlyName=Front Door\nroot.Properties.Location=Lab\n"
        )

        values = await api.get_many(
            ["root.Properties.FriendlyName", "Properties.Location", "Properties.Nope"]
        )

        assert len(client.get.await_args_list) == 1
        assert _requested(client)[0]["group"] == (
            "Properties.FriendlyName,Properties.Location,Properties.Nope"
        )
        assert values == {
            "root.Properties.FriendlyName": "Front Door",
            "Properties.Location": "Lab",
            "Properties.Nope": None,
        }

    async def test_get_many_empty(self):
        api, client = _api()
        assert await api.get_many([]) == {}
        client.get.assert_not_awaited()

    async def test_search_is_case_insensitive_on_the_short_name(self):
        api, _ = _api(LISTING)

        found = await api.search("ETH0")

        assert [p.name for p in found] == ["Network.eth0.IPAddress", "Network.eth0.MACAddress"]


class TestExport:
    async def test_export_is_the_flat_listing_with_full_names(self):
        api, client = _api(LISTING)

        exported = await api.export()

        assert _requested(client) == [{"action": "list", "responseformat": "rfc"}]
        assert exported == parse_param_list(LISTING)
        assert all(k.startswith("root.") for k in exported)

    async def test_export_propagates_errors_instead_of_changing_shape(self):
        api, _ = _api(AxisDeviceError("500"))
        with pytest.raises(AxisDeviceError):
            await api.export()


class TestConvenience:
    async def test_friendly_name_and_location(self):
        api, _ = _api("root.Properties.FriendlyName=Front Door\n", "root.Properties.Location=Lab\n")
        assert await api.get_friendly_name() == "Front Door"
        assert await api.get_location() == "Lab"

    async def test_friendly_name_missing_is_empty_string(self):
        api, _ = _api("# Error: nope\n")
        assert await api.get_friendly_name() == ""

    async def test_ip_address_first_candidate_wins(self):
        api, client = _api("root.Network.eth0.IPAddress=10.0.0.5\n")

        assert await api.get_ip_address() == "10.0.0.5"
        assert len(client.get.await_args_list) == 1  # one request for all candidates

    async def test_ip_address_falls_through_to_alternatives(self):
        api, _ = _api("root.Network.IPv4.Address=10.0.0.9\n")
        assert await api.get_ip_address() == "10.0.0.9"

    async def test_mac_address(self):
        api, _ = _api("root.Network.eth0.MACAddress=AC:CC:8E:00:00:01\n")
        assert await api.get_mac_address() == "AC:CC:8E:00:00:01"


class TestWire:
    """Through the real client: the request line and the text body, end to end."""

    @respx.mock
    async def test_list_sends_rfc_format_and_parses_text_plain(self):
        route = respx.get("https://192.168.1.10:443/axis-cgi/param.cgi").mock(
            return_value=httpx.Response(
                200, text=DOC_EXAMPLE, headers={"content-type": "text/plain"}
            )
        )

        async with VapixClient(
            "192.168.1.10", "root", "pw", port=443, use_https=True, use_digest_auth=False
        ) as client:
            groups = await ParamAPI(client).get_all()

        assert route.calls[0].request.url.params["action"] == "list"
        assert route.calls[0].request.url.params["responseformat"] == "rfc"
        assert [g.name for g in groups] == ["Network"]
        assert len(groups[0].parameters) == 3

    @respx.mock
    async def test_the_old_json_parse_would_have_hidden_everything(self):
        # Documenting the regression: text/plain is not JSON.
        respx.get("https://192.168.1.10:443/axis-cgi/param.cgi").mock(
            return_value=httpx.Response(200, text=DOC_EXAMPLE)
        )
        async with VapixClient(
            "192.168.1.10", "root", "pw", port=443, use_https=True, use_digest_auth=False
        ) as client:
            with pytest.raises(AxisDeviceError, match="Invalid JSON"):
                await client.get_json("/axis-cgi/param.cgi", {"action": "list"})
