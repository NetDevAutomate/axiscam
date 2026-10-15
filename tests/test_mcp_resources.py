"""Read-only resources: immutable data a host may cache and a model may cite.

Live device state is deliberately not a resource (resources are cacheable by
contract; device state is not). These three are fixed for the life of the
server or, for a manifest, for the life of the backup.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from mcp import Client

from axis_cam.audit import PARAM_CHECKS
from axis_cam.mcp_server.server import build_server
from tests.mcp_fakes import CANARY, two_cameras

if TYPE_CHECKING:
    from pathlib import Path


async def _read(client: Client, uri: str) -> Any:
    result = await client.read_resource(uri)
    (content,) = result.contents
    assert content.mime_type == "application/json"
    return json.loads(content.text)  # type: ignore[union-attr]


async def test_resources_and_templates_are_listed() -> None:
    async with Client(build_server(two_cameras())) as client:
        resources = [str(r.uri) for r in (await client.list_resources()).resources]
        templates = [
            t.uri_template for t in (await client.list_resource_templates()).resource_templates
        ]
    assert resources == ["axiscam://checks"]
    assert sorted(templates) == [
        "axiscam://backups/{backup_id}/manifest",
        "axiscam://schemas/{module}",
    ]


async def test_checks_lists_every_parameter_check_with_its_hardened_value() -> None:
    async with Client(build_server(two_cameras())) as client:
        body = await _read(client, "axiscam://checks")
    assert body["guide"].startswith("https://help.axis.com/")
    by_id = {c["id"]: c for c in body["checks"]}
    for check in PARAM_CHECKS:
        entry = by_id[check.check_id]
        assert entry["parameter"] == check.param
        assert entry["hardened_values"] == list(check.hardened)
        assert entry["severity"] == check.severity.value
    assert "https.only" in by_id and "network.firewall" in by_id
    assert all(set(c) >= {"id", "title", "severity", "reference"} for c in body["checks"])
    assert body["data_dependent"]  # named, so a reader knows the list is not exhaustive per device


async def test_schema_for_a_module_is_its_result_models_json_schema() -> None:
    from axis_cam.models import SshConfig

    async with Client(build_server(two_cameras())) as client:
        body = await _read(client, "axiscam://schemas/ssh")
    assert body == {"module": "ssh", "model": "SshConfig", "schema": SshConfig.model_json_schema()}


async def test_schema_for_an_unknown_module_is_an_error() -> None:
    async with Client(build_server(two_cameras())) as client:
        with pytest.raises(Exception, match="no readable module"):
            await client.read_resource("axiscam://schemas/params")


async def test_backup_manifest(tmp_path: Path) -> None:
    async with Client(build_server(two_cameras(), backup_root=tmp_path)) as client:
        backup_id = (
            await client.call_tool("backup_create", {"device": "back_of_house"})
        ).structured_content["backup_id"]
        body = await _read(client, f"axiscam://backups/{backup_id}/manifest")
    on_disk = json.loads((tmp_path / backup_id / "manifest.json").read_text())
    assert body == on_disk
    assert body["contains_credentials"]  # the fixture params hold SNMP/proxy secrets
    assert CANARY not in json.dumps(body)


@pytest.mark.parametrize("bad", ["..", "backup-..", "not-a-backup", "backup-nonexistent"])
async def test_manifest_for_a_bad_or_unknown_id_is_an_error(tmp_path: Path, bad: str) -> None:
    async with Client(build_server(two_cameras(), backup_root=tmp_path)) as client:
        with pytest.raises(Exception):  # noqa: B017 - the SDK raises its own error type
            await client.read_resource(f"axiscam://backups/{bad}/manifest")
