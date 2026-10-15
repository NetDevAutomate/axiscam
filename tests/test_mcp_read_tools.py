"""Phase A read tools, exercised through the SDK's in-process client.

Order follows the decision document's "first ten failing tests": each test
names the production change it forced.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from mcp import Client

from axis_cam.exceptions import (
    AxisApiNotSupportedError,
    AxisAuthenticationError,
    AxisConnectionError,
    AxisDeviceError,
    AxisPermissionError,
)
from axis_cam.mcp_server.server import TOOL_NAMES, build_server
from tests.mcp_fakes import CANARY, CANARY_BASIC, SSH, FakeDevice, FakeModule, two_cameras

if TYPE_CHECKING:
    from typing import NoReturn

# --- 1: tools/list deterministic, nothing on stdout -------------------------------


class TestToolsList:
    async def test_tools_list_is_sorted_and_stable_with_a_ttl(self, capsys) -> None:
        server = build_server(two_cameras())
        async with Client(server) as client:
            first = await client.list_tools()
            second = await client.list_tools()
        names = [t.name for t in first.tools]
        assert names == sorted(names)
        assert names == [t.name for t in second.tools]
        assert names == sorted(TOOL_NAMES)
        assert len(names) == 13
        assert first.ttl_ms is not None and first.ttl_ms > 0
        # the device enum is this user's config: never shareable across users
        assert first.cache_scope == "private"
        assert capsys.readouterr().out == ""

    async def test_only_apply_plan_is_destructive(self) -> None:
        server = build_server(two_cameras())
        async with Client(server) as client:
            tools = (await client.list_tools()).tools
        for tool in tools:
            assert tool.annotations is not None, tool.name
            assert tool.annotations.open_world_hint is False, tool.name
            if tool.name == "apply_plan":
                assert tool.annotations.destructive_hint is True
                assert tool.annotations.read_only_hint is False
                continue
            assert tool.annotations.destructive_hint is False, tool.name
            if tool.name.startswith("plan_") or tool.name == "backup_create":
                # a plan is server-side state; a backup writes to the server's disk
                assert tool.annotations.read_only_hint is False, tool.name
            else:
                assert tool.annotations.read_only_hint is True, tool.name

    async def test_no_tool_input_property_names_a_secret(self) -> None:
        server = build_server(two_cameras())
        async with Client(server) as client:
            tools = (await client.list_tools()).tools
        import re

        banned = re.compile(r"(?i)pass|secret|community|token|host|address|url")
        for tool in tools:
            for prop in tool.input_schema.get("properties", {}):
                assert not banned.search(prop), f"{tool.name}.{prop}"

    def test_import_writes_nothing_to_stdout_and_does_not_import_the_cli(self) -> None:
        code = (
            "import sys, axis_cam.mcp_server.server; "
            "sys.stderr.write(repr(sorted(m for m in sys.modules "
            "if m == 'axis_cam.cli' or m.startswith('axis_cam.cli.') or m == 'typer')))"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        )
        assert out.stdout == ""
        assert out.stderr.strip() == "[]"


# --- 2 & 3: devices are an enum from config; never credentials --------------------


class TestDevices:
    async def test_list_devices_never_contains_credentials(self) -> None:
        server = build_server(two_cameras())
        async with Client(server) as client:
            result = await client.call_tool("list_devices", {})
        assert result.is_error is False
        text = json.dumps(result.structured_content) + "".join(
            getattr(c, "text", "") for c in result.content
        )
        assert CANARY not in text and CANARY_BASIC not in text and "admin" not in text
        devices = result.structured_content["devices"]
        assert [d["name"] for d in devices] == ["back_of_house", "front_of_house"]
        assert devices[0] == {
            "name": "back_of_house",
            "device_type": "camera",
            "groups": ["indoor"],
            "host": "192.168.10.21",
        }

    async def test_device_argument_is_an_enum_of_configured_names(self) -> None:
        server = build_server(two_cameras())
        async with Client(server) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            schema = tools["read_module"].input_schema
            device_schema = schema["properties"]["device"]
            if "$ref" in device_schema:
                device_schema = schema["$defs"][device_schema["$ref"].rsplit("/", 1)[1]]
            assert device_schema["enum"] == ["back_of_house", "front_of_house"]

            rejected = await client.call_tool(
                "read_module", {"device": "192.168.10.21", "module": "ssh"}
            )
        assert rejected.is_error is True
        assert "192.168.10.21" in "".join(getattr(c, "text", "") for c in rejected.content)
        # the fake was never opened: validation refused the call before the tool ran
        assert two_cameras().device("back_of_house").entered == 0

    async def test_module_argument_is_an_enum_of_registered_resources(self) -> None:
        server = build_server(two_cameras())
        async with Client(server) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
        schema = tools["read_module"].input_schema
        module_schema = schema["properties"]["module"]
        if "$ref" in module_schema:
            module_schema = schema["$defs"][module_schema["$ref"].rsplit("/", 1)[1]]
        values = module_schema["enum"]
        assert values == sorted(values)
        assert {"ssh", "device_info", "users", "onvif_users", "ntp"} <= set(values)
        # download-only modules and the parameter tree are not resources
        assert not {"logs", "serverreport", "params"} & set(values)


# --- 4, 5, 6: read_module envelope ---------------------------------------------------


class TestReadModule:
    async def test_read_module_ok_ssh(self) -> None:
        resolver = two_cameras()
        server = build_server(resolver)
        async with Client(server) as client:
            result = await client.call_tool(
                "read_module", {"device": "back_of_house", "module": "ssh"}
            )
        assert result.is_error is False
        assert result.structured_content == {
            "device": "back_of_house",
            "module": "ssh",
            "status": "ok",
            "model": "SshConfig",
            "value": SSH.model_dump(mode="json"),
            "reason": None,
        }
        dev = resolver.device("back_of_house")
        assert (dev.entered, dev.exited) == (1, 1)

    async def test_read_module_not_advertised_has_null_value(self) -> None:
        server = build_server(two_cameras())
        async with Client(server) as client:
            result = await client.call_tool(
                "read_module", {"device": "front_of_house", "module": "ssh"}
            )
        assert result.is_error is False
        body = result.structured_content
        assert body["status"] == "not_advertised"
        assert body["value"] is None
        assert "ssh" in body["reason"] and "advertise" in body["reason"]

    @pytest.mark.parametrize(
        ("error", "status", "reason_contains"),
        [
            (AxisPermissionError("403 Forbidden for /config/rest/ssh/v2"), "unreadable", "403"),
            (AxisApiNotSupportedError("404 Not Found"), "unreadable", "404"),
            (AxisAuthenticationError("Authentication failed for admin"), "error", "Authentication"),
            (AxisConnectionError("Connection refused"), "error", "Connection refused"),
            (AxisDeviceError("device returned garbage"), "error", "garbage"),
        ],
    )
    async def test_errors_map_to_statuses_and_except_order_is_right(
        self, error: Exception, status: str, reason_contains: str
    ) -> None:
        device = FakeDevice("10.0.0.1", [FakeModule("ssh", error, api_id="ssh")])
        server = build_server(two_cameras(back_of_house=device))
        async with Client(server) as client:
            result = await client.call_tool(
                "read_module", {"device": "back_of_house", "module": "ssh"}
            )
        assert (
            result.is_error is False
        )  # a device that will not answer is a result, not a tool failure
        body = result.structured_content
        assert body["status"] == status
        assert body["value"] is None
        assert reason_contains in body["reason"]

    async def test_a_bug_in_a_module_is_scrubbed_to_its_class_name(self) -> None:
        device = FakeDevice(
            "10.0.0.1",
            [FakeModule("ssh", KeyError(f"leaked {CANARY}"), api_id="ssh")],
        )
        server = build_server(two_cameras(back_of_house=device))
        async with Client(server) as client:
            result = await client.call_tool(
                "read_module", {"device": "back_of_house", "module": "ssh"}
            )
        body = result.structured_content
        assert body["status"] == "error"
        assert body["reason"] == "internal error: KeyError"
        assert CANARY not in json.dumps(body)

    async def test_module_the_device_does_not_have_at_all(self) -> None:
        device = FakeDevice(
            "10.0.0.1",
            [
                FakeModule(
                    "device_info",
                    two_cameras().device("back_of_house").resources["device_info"]._result,
                )
            ],
        )
        server = build_server(two_cameras(back_of_house=device))
        async with Client(server) as client:
            result = await client.call_tool(
                "read_module", {"device": "back_of_house", "module": "ssh"}
            )
        body = result.structured_content
        assert body["status"] == "not_advertised"
        assert body["value"] is None


class TestListModules:
    async def test_lists_advertised_not_advertised_and_never_gated(self) -> None:
        server = build_server(two_cameras())
        async with Client(server) as client:
            back = (
                await client.call_tool("list_modules", {"device": "back_of_house"})
            ).structured_content
            front = (
                await client.call_tool("list_modules", {"device": "front_of_house"})
            ).structured_content
        assert back == {
            "device": "back_of_house",
            "advertised": ["ssh"],
            "not_advertised": [],
            "never_gated": ["device_info"],
        }
        assert front == {
            "device": "front_of_house",
            "advertised": [],
            "not_advertised": ["ssh"],
            "never_gated": ["device_info"],
        }

    async def test_authentication_failure_is_a_tool_error_without_the_password(self) -> None:
        class Broken(FakeDevice):
            async def __aenter__(self):
                raise AxisAuthenticationError(f"401 for admin (sent {CANARY})")

        server = build_server(two_cameras(back_of_house=Broken("10.0.0.1")))
        async with Client(server) as client:
            result = await client.call_tool("list_modules", {"device": "back_of_house"})
        assert result.is_error is True
        text = "".join(getattr(c, "text", "") for c in result.content)
        assert "401" in text and CANARY not in text and CANARY_BASIC not in text


class TestUnexpectedErrors:
    """An exception that is not an ``AxisError`` never shows its text, anywhere."""

    @staticmethod
    def _validation_error_holding_the_canary() -> Exception:
        from pydantic import BaseModel, ValidationError

        class Strict(BaseModel):
            enabled: bool

        try:
            Strict.model_validate({"enabled": CANARY})
        except ValidationError as exc:
            assert CANARY in str(exc)  # precondition: pydantic quotes the input
            return exc
        raise AssertionError("unreachable")

    async def test_device_report_never_shows_or_logs_validation_input(
        self, caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]
    ) -> None:
        caplog.set_level(logging.DEBUG)
        error = self._validation_error_holding_the_canary()
        device = FakeDevice("192.0.2.1", [FakeModule("ssh", error, api_id="ssh")])
        server = build_server(two_cameras(back_of_house=device))
        async with Client(server) as client:
            result = await client.call_tool(
                "device_report", {"device": "back_of_house", "full": True}
            )
        wire = "".join(getattr(item, "text", "") for item in result.content)
        captured = capfd.readouterr()
        assert result.is_error is True
        assert "internal error: ValidationError" in wire
        for surface in (wire, caplog.text, captured.out, captured.err):
            assert CANARY not in surface
        assert "Traceback" not in caplog.text

    async def test_a_sync_tool_never_shows_or_logs_its_exception(
        self,
        caplog: pytest.LogCaptureFixture,
        capfd: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Opus F3: three tools are sync (list_devices, backup_list, backup_verify);
        # the wrapper's sync branch needs its own test.
        caplog.set_level(logging.DEBUG)
        resolver = two_cameras()
        server = build_server(resolver)

        def explode(name: str) -> NoReturn:
            raise RuntimeError(f"describe saw {CANARY} for {name}")

        monkeypatch.setattr(resolver, "describe", explode)
        async with Client(server) as client:
            result = await client.call_tool("list_devices", {})
        wire = "".join(getattr(item, "text", "") for item in result.content)
        captured = capfd.readouterr()
        assert result.is_error is True
        assert "internal error: RuntimeError" in wire
        for surface in (wire, caplog.text, captured.out, captured.err):
            assert CANARY not in surface
        assert "Traceback" not in caplog.text
