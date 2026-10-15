"""Phase A: params, audit, backups, plans, and the secrets boundary.

Continues the decision document's first ten failing tests (7-10) and adds the
boundary assertions: no tool output, error text or stdio frame carries the
device password or its HTTP Basic form.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest
from mcp import Client

from axis_cam.audit import Status
from axis_cam.mcp_server.plans import PlanStore
from axis_cam.mcp_server.redact import REDACTED, Scrubber, is_secret_name, redact_params
from axis_cam.mcp_server.server import build_server
from tests.mcp_fakes import CANARY, CANARY_BASIC, PARAMS, two_cameras

if TYPE_CHECKING:
    from pathlib import Path


def _all_text(result: Any) -> str:
    return json.dumps(result.structured_content) + "".join(
        getattr(c, "text", "") for c in result.content
    )


# --- 7: query_params ----------------------------------------------------------------


class TestQueryParams:
    async def test_prefix_required(self) -> None:
        async with Client(build_server(two_cameras())) as client:
            result = await client.call_tool(
                "query_params", {"device": "back_of_house", "prefix": ""}
            )
        assert result.is_error is True

    async def test_limit_capped_at_200(self) -> None:
        async with Client(build_server(two_cameras())) as client:
            result = await client.call_tool(
                "query_params", {"device": "back_of_house", "prefix": "Network", "limit": 201}
            )
        assert result.is_error is True

    async def test_prefix_matches_whole_segments_and_pages(self) -> None:
        async with Client(build_server(two_cameras())) as client:
            first = (
                await client.call_tool(
                    "query_params", {"device": "back_of_house", "prefix": "Network", "limit": 2}
                )
            ).structured_content
            second = (
                await client.call_tool(
                    "query_params",
                    {"device": "back_of_house", "prefix": "root.Network", "limit": 2, "cursor": 2},
                )
            ).structured_content
        network = sorted(k for k in PARAMS if k.startswith("root.Network."))
        assert first["total"] == len(network)
        assert [i["name"] for i in first["items"]] == network[:2]
        assert first["next_cursor"] == 2
        assert [i["name"] for i in second["items"]] == network[2:4]

    async def test_secrets_are_redacted(self) -> None:
        async with Client(build_server(two_cameras())) as client:
            snmp = await client.call_tool(
                "query_params", {"device": "back_of_house", "prefix": "SNMP"}
            )
            proxy = await client.call_tool(
                "query_params", {"device": "back_of_house", "prefix": "Network.Proxy"}
            )
        items = {i["name"]: i for i in snmp.structured_content["items"]}
        assert items["root.SNMP.Enabled"]["value"] == "no"
        assert items["root.SNMP.ReadCommunity"] == {
            "name": "root.SNMP.ReadCommunity",
            "value": REDACTED,
            "redacted": True,
        }
        assert "s3cret-community" not in _all_text(snmp)  # pragma: allowlist secret
        assert CANARY not in _all_text(proxy)


class TestRedact:
    @pytest.mark.parametrize(
        "name",
        [
            "root.SNMP.ReadCommunity",
            "root.Network.Proxy.Password",
            "root.Network.Interface.I0.dot1x.EAPOL.KeyPassword",
            "root.Network.Wireless.PSK",
            "root.Some.ClientSecret",
            "root.Some.AccessToken",
        ],
    )
    def test_secret_names(self, name: str) -> None:
        assert is_secret_name(name)

    @pytest.mark.parametrize(
        "name", ["root.SNMP.Enabled", "root.Image.I0.Name", "root.Network.UPnP.Enabled"]
    )
    def test_ordinary_names(self, name: str) -> None:
        assert not is_secret_name(name)

    def test_empty_secret_stays_empty(self) -> None:
        assert redact_params({"root.SNMP.WriteCommunity": ""}) == {"root.SNMP.WriteCommunity": ""}

    def test_scrubber_removes_password_and_basic_form(self) -> None:
        scrub = Scrubber("admin", CANARY)
        text = f"sent {CANARY} as Basic {CANARY_BASIC}"
        assert scrub.text(text) == f"sent {REDACTED} as Basic {REDACTED}"
        assert scrub.data({"a": [CANARY, {"b": CANARY_BASIC}]}) == {
            "a": [REDACTED, {"b": REDACTED}]
        }


# --- 8: audit ----------------------------------------------------------------------


class TestAudit:
    async def test_structured_result_equals_the_library_report(self) -> None:
        resolver = two_cameras()
        async with Client(build_server(resolver)) as client:
            body = (
                await client.call_tool("security_audit", {"device": "back_of_house"})
            ).structured_content
        from axis_cam.audit import run_audit

        expected = (
            await run_audit(resolver.open("back_of_house"), device_name="back_of_house")
        ).to_dict()
        body["result"].pop("generated_at")
        expected.pop("generated_at")
        assert body == {"device": "back_of_house", "result": expected}

    async def test_status_filter(self) -> None:
        async with Client(build_server(two_cameras())) as client:
            body = (
                await client.call_tool(
                    "security_audit", {"device": "back_of_house", "status": "unknown"}
                )
            ).structured_content
        assert body["result"]["findings"]
        assert {f["status"] for f in body["result"]["findings"]} == {Status.UNKNOWN.value}


# --- 9: backups --------------------------------------------------------------------


class TestBackups:
    async def test_backup_goes_to_the_fixed_root_and_lists_and_verifies(
        self, tmp_path: Path
    ) -> None:
        async with Client(build_server(two_cameras(), backup_root=tmp_path)) as client:
            created = await client.call_tool("backup_create", {"device": "back_of_house"})
            assert created.is_error is False, _all_text(created)
            backup_id = created.structured_content["backup_id"]
            listed = (await client.call_tool("backup_list", {})).structured_content
            checked = (
                await client.call_tool("backup_verify", {"backup_id": backup_id})
            ).structured_content
        assert (tmp_path / backup_id).is_dir()
        assert [b["backup_id"] for b in listed["backups"]] == [backup_id]
        assert checked == {"backup_id": backup_id, "ok": True, "problems": []}
        assert CANARY not in _all_text(created)

    @pytest.mark.parametrize(
        "bad", ["../etc", "backup-../../x", "/tmp/backup-x", "backup-a/b", "manifest.json"]
    )
    async def test_traversal_ids_are_refused(self, tmp_path: Path, bad: str) -> None:
        async with Client(build_server(two_cameras(), backup_root=tmp_path)) as client:
            result = await client.call_tool("backup_verify", {"backup_id": bad})
        assert result.is_error is True

    async def test_no_tool_takes_a_destination_path(self) -> None:
        async with Client(build_server(two_cameras())) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools["backup_create"].input_schema["properties"]) == {"device"}


# --- 10: plans write nothing -------------------------------------------------------


class TestPlans:
    async def test_plan_restore_writes_nothing_and_returns_a_handle(self, tmp_path: Path) -> None:
        resolver = two_cameras()
        store = PlanStore()
        server = build_server(resolver, backup_root=tmp_path, plans=store)
        async with Client(server) as client:
            backup_id = (
                await client.call_tool("backup_create", {"device": "back_of_house"})
            ).structured_content["backup_id"]
            # the device drifts after the backup: one label and the SNMP write community.
            # (Network.* parameters are excluded from restore plans by design.)
            drifted = dict(PARAMS)
            drifted["root.Image.I0.Name"] = "Changed"
            drifted["root.SNMP.WriteCommunity"] = "new-community"  # pragma: allowlist secret
            dev = resolver.device("back_of_house")
            dev.params.export.return_value = drifted
            result = await client.call_tool(
                "plan_restore", {"device": "back_of_house", "backup_id": backup_id}
            )
        assert result.is_error is False, _all_text(result)
        body = result.structured_content
        assert body["kind"] == "param_restore"
        assert body["serial"] == "ACCC8E000001"
        changes = {c["name"]: c for c in body["plan"]["changes"]}
        assert changes["root.Image.I0.Name"] == {
            "name": "root.Image.I0.Name",
            "current": "Changed",
            "target": "View Area 1",
        }
        assert changes["root.SNMP.WriteCommunity"] == {
            "name": "root.SNMP.WriteCommunity",
            "current": REDACTED,
            "target": REDACTED,
        }
        text = _all_text(result)
        assert (
            "new-community" not in text and "s3cret-community" not in text
        )  # pragma: allowlist secret
        assert "root.Network.Proxy.Password" not in changes
        assert store.get(body["plan_id"]) is not None
        assert dev.params.set.call_count == 0
        assert "nothing was written" in body["note"]

    async def test_plan_account_change_reports_what_the_guard_would_refuse(self) -> None:
        async with Client(build_server(two_cameras())) as client:
            ok = (
                await client.call_tool(
                    "plan_account_change",
                    {
                        "device": "back_of_house",
                        "account": "second",
                        "action": "set_role",
                        "role": "operator",
                    },
                )
            ).structured_content
            self_remove = (
                await client.call_tool(
                    "plan_account_change",
                    {"device": "back_of_house", "account": "admin", "action": "remove"},
                )
            ).structured_content
        assert ok["plan"]["would_be_refused"] is None
        assert ok["plan"]["current_role"] == "admin" and ok["plan"]["new_role"] == "operator"
        assert "authenticates as" in self_remove["plan"]["would_be_refused"]

    def test_plans_are_single_use_and_expire(self) -> None:
        now = [0.0]
        store = PlanStore(ttl=10, clock=lambda: now[0])
        plan = store.mint("param_restore", "cam", "SERIAL", {"x": 1})
        assert store.take(plan.plan_id) is plan
        assert store.take(plan.plan_id) is None
        other = store.mint("param_restore", "cam", "SERIAL", {"x": 1})
        now[0] = 10.0
        assert store.get(other.plan_id) is None


# --- boundary: a real stdio run emits only JSON-RPC frames --------------------------


def test_stdio_subprocess_emits_only_json_rpc(tmp_path: Path) -> None:
    """Start the real entry point with a temp config and speak to it over stdio."""
    config = tmp_path / "config.yaml"
    config.write_text(
        "devices:\n"
        "  cam:\n"
        "    address: 192.0.2.10\n"
        "    username: admin\n"
        f"    password: '{CANARY}'\n"
    )
    config.chmod(0o600)
    script = (
        "import asyncio, sys\n"
        "from mcp import Client, StdioServerParameters\n"
        "async def main():\n"
        "    params = StdioServerParameters(command=sys.executable, args=['-c', "
        "'from axis_cam.mcp_server.server import main; main()'], "
        "env=dict(__import__('os').environ))\n"
        "    async with Client(params) as c:\n"
        "        tools = await c.list_tools()\n"
        "        r = await c.call_tool('list_devices', {})\n"
        "        print(len(tools.tools), r.structured_content['devices'][0]['name'])\n"
        "asyncio.run(main())\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("AXIS")}
    env.update(AXIS_CONFIG_DIR=str(tmp_path), XDG_DATA_HOME=str(tmp_path / "data"))
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=60
    )
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip() == "12 cam"
    assert CANARY not in out.stdout and CANARY not in out.stderr
