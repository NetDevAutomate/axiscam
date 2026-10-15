"""Tests for the params-only restore path (Phase 5, narrowed)."""

import base64
import json
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from axis_cam.api.param import ParamAPI, ParamDefinition, parse_param_definitions
from axis_cam.backup import MANIFEST_FILE, BackupFile, BackupManifest
from axis_cam.client import VapixClient
from axis_cam.devices.base import AxisDevice
from axis_cam.exceptions import AxisAuthenticationError, AxisDeviceError
from axis_cam.restore import (
    SERIAL_PARAM,
    ChangeResult,
    ParamChange,
    RestoreDriftError,
    SkipReason,
    apply_param_restore,
    diff_params,
    load_backup_params,
    plan_param_restore,
)

CURRENT = {
    SERIAL_PARAM: "B8A44F9F0228",
    "root.Brand.Brand": "AXIS",
    "root.Properties.FriendlyName": "AXIS M3216-LVE",
    "root.Network.eth0.IPAddress": "192.168.10.12",
    "root.Audio.MaxListeners": "10",
    "root.Image.I0.Appearance.Compression": "30",
    "root.Time.POSIXTimeZone": "GMT0BST,M3.5.0/1,M10.5.0",
}

# securityLevel codes as the M3216-LVE reports them (digits: add, remove, read, write)
LEVELS = {
    SERIAL_PARAM: "7707",
    "root.Brand.Brand": "7707",
    "root.Properties.FriendlyName": "7717",
    "root.Network.eth0.IPAddress": "7766",
    "root.Audio.MaxListeners": "7716",
    "root.Image.I0.Appearance.Compression": "7714",
    "root.Time.POSIXTimeZone": "7716",
}
DEFINITIONS = {
    name: ParamDefinition(name=name, value=CURRENT[name], security_level=level)
    for name, level in LEVELS.items()
}

# Verbatim shape of listdefinitions&listformat=xmlschema on AXIS OS 12.11
LISTDEFINITIONS_XML = """<?xml version="1.0" encoding="iso-8859-1" ?>
<parameterDefinitions xmlns="http://www.axis.com/ParameterDefinitionsSchema"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <model>M3216-LVE</model>
  <firmwareVersion>12.11.118</firmwareVersion>
  <group name="root">
    <group name="Brand">
      <parameter name="Brand" value="AXIS" securityLevel="7707" niceName="Brand">
        <type><string readonly="true" /></type>
      </parameter>
    </group>
    <group name="Image">
      <group name="I0">
        <parameter name="Name" value="View Area 1" securityLevel="7704" niceName="Name">
          <type><string /></type>
        </parameter>
      </group>
    </group>
    <group name="HTTPS">
      <parameter name="Enabled" value="yes" securityLevel="7706" niceName="Enabled">
        <type><bool true="yes" false="no" /></type>
      </parameter>
    </group>
  </group>
</parameterDefinitions>
"""


def _backup_dir(tmp_path: Path, params: dict, serial: str | None = "B8A44F9F0228") -> Path:
    root = tmp_path / "backup-x"
    root.mkdir()
    content = json.dumps(params).encode()
    (root / "params.json").write_bytes(content)
    import hashlib

    manifest = BackupManifest(
        format_version=1,
        created_at="2026-10-13T12:00:00+00:00",
        tool={"name": "axiscam", "version": "0.1.0"},
        device={"host": "10.0.0.5", "name": "cam", **({"serial_number": serial} if serial else {})},
        files=[
            BackupFile(
                "params",
                "params.json",
                hashlib.sha256(content).hexdigest(),
                len(content),
                "param.cgi",
            )
        ],
    )
    (root / MANIFEST_FILE).write_text(json.dumps(manifest.to_dict()))
    return root


def _rehash(root: Path, content: bytes) -> None:
    """Make the manifest vouch for a rewritten params.json (what a legitimate edit must do)."""
    import hashlib

    manifest = json.loads((root / MANIFEST_FILE).read_text())
    entry = next(f for f in manifest["files"] if f["file"] == "params.json")
    entry["sha256"] = hashlib.sha256(content).hexdigest()
    entry["size"] = len(content)
    (root / MANIFEST_FILE).write_text(json.dumps(manifest))


def _device(current: dict[str, str], *, set_results=None, definitions=None) -> AxisDevice:
    params = MagicMock()
    params.export = AsyncMock(return_value=dict(current))
    params.definitions = AsyncMock(
        return_value=dict(DEFINITIONS) if definitions is None else definitions
    )
    state = dict(current)

    async def fake_set(name, value):
        if set_results and name in set_results:
            outcome = set_results[name]
            if isinstance(outcome, Exception):
                raise outcome
            state[name] = outcome  # device "accepted" but stored something else
            return
        state[name] = value

    async def fake_get(name):
        return state.get(name)

    params.set = AsyncMock(side_effect=fake_set)
    params.get = AsyncMock(side_effect=fake_get)
    device = MagicMock()
    device.params = params
    return cast("AxisDevice", device)


class TestParseDefinitions:
    def test_names_rebuilt_from_nesting_and_levels_kept(self):
        defs = parse_param_definitions(LISTDEFINITIONS_XML)

        assert set(defs) == {"root.Brand.Brand", "root.Image.I0.Name", "root.HTTPS.Enabled"}
        assert defs["root.Image.I0.Name"] == ParamDefinition(
            "root.Image.I0.Name", "View Area 1", "7704"
        )

    def test_write_digit_decides_writability(self):
        defs = parse_param_definitions(LISTDEFINITIONS_XML)

        assert defs["root.Brand.Brand"].writable is False
        assert defs["root.Brand.Brand"].write_access == "none"
        assert defs["root.Image.I0.Name"].writable is True
        assert defs["root.Image.I0.Name"].write_access == "operator"
        # The Param API page's own example: 7706 is readable by all roles and writable.
        assert defs["root.HTTPS.Enabled"].writable is True
        assert defs["root.HTTPS.Enabled"].write_access == "admin"

    def test_malformed_level_is_not_writable_and_unknown(self):
        definition = ParamDefinition("root.X.Y", "", "")
        assert definition.writable is False and definition.write_access == "unknown"

    def test_error_body_raises(self):
        with pytest.raises(AxisDeviceError, match="Error -1"):
            parse_param_definitions("# Error: Error -1 getting param in group 'Nope'\n")

    def test_html_raises(self):
        with pytest.raises(AxisDeviceError, match="did not return XML"):
            parse_param_definitions("<html><body>login")

    async def test_definitions_requests_xmlschema(self):
        client = MagicMock()
        client.host = "h"
        client.get = AsyncMock(return_value=MagicMock(text=LISTDEFINITIONS_XML))

        defs = await ParamAPI(client).definitions()

        client.get.assert_awaited_once_with(
            "/axis-cgi/param.cgi", {"action": "listdefinitions", "listformat": "xmlschema"}
        )
        assert len(defs) == 3


class TestParamApiSet:
    async def test_sends_action_update_with_short_name(self):
        client = MagicMock()
        client.host = "h"
        client.get = AsyncMock(return_value=MagicMock(text="OK\n"))
        api = ParamAPI(client)

        await api.set("root.Audio.MaxListeners", "5")

        client.get.assert_awaited_once_with(
            "/axis-cgi/param.cgi", {"action": "update", "Audio.MaxListeners": "5"}
        )

    async def test_error_body_raises(self):
        client = MagicMock()
        client.host = "h"
        client.get = AsyncMock(
            return_value=MagicMock(text="# Error: Error setting 'Brand.Brand' to 'X'!\n")
        )

        with pytest.raises(AxisDeviceError, match=r"Error setting 'Brand\.Brand'"):
            await ParamAPI(client).set("Brand.Brand", "X")

    async def test_unexpected_body_raises(self):
        client = MagicMock()
        client.host = "h"
        client.get = AsyncMock(return_value=MagicMock(text="<html>login</html>"))

        with pytest.raises(AxisDeviceError, match="unexpected reply"):
            await ParamAPI(client).set("Audio.MaxListeners", "5")

    async def test_a_refused_credential_value_is_not_echoed_into_the_error(self):
        # The device's refusal quotes the value it was sent. For a credential
        # parameter that value is a secret, and restore prints the error.
        community = "rd-9fQ2zX7kLm"  # pragma: allowlist secret
        client = MagicMock()
        client.host = "h"
        client.get = AsyncMock(
            return_value=MagicMock(
                text=f"# Error: Error setting 'SNMP.ReadCommunity' to '{community}'!\n"
            )
        )

        with pytest.raises(AxisDeviceError) as caught:
            await ParamAPI(client).set("root.SNMP.ReadCommunity", community)
        assert community not in str(caught.value)
        assert "Error setting 'SNMP.ReadCommunity' to '[redacted]'" in str(caught.value)

    async def test_an_ordinary_value_is_still_quoted(self):
        client = MagicMock()
        client.host = "h"
        client.get = AsyncMock(
            return_value=MagicMock(text="# Error: Error setting 'Image.I0.Name' to 'Hall'!\n")
        )

        with pytest.raises(AxisDeviceError, match="to 'Hall'"):
            await ParamAPI(client).set("Image.I0.Name", "Hall")

    @staticmethod
    def _replying(text: str) -> MagicMock:
        client = MagicMock()
        client.host = "h"
        client.get = AsyncMock(return_value=MagicMock(text=text))
        return client

    @pytest.mark.parametrize("value", ["OK", "K", "O"])
    async def test_a_secret_value_that_spells_part_of_ok_still_succeeds(self, value: str):
        # Replacing before checking for "OK" turned these successes into errors.
        await ParamAPI(self._replying("OK\n")).set("root.SNMP.ReadCommunity", value)

    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("SNMP.ReadCommunity", "e"),
            ("SNMP.ReadCommunity", "E"),
            ("SNMP.ReadCommunity", "#"),
            ("SNMP.ReadCommunity", "SNMP"),
            ("Network.Interface.I0.dot1x.EAPOL.KeyPassword", "1"),
        ],
    )
    async def test_a_short_secret_value_leaves_the_refusal_readable(self, name: str, value: str):
        refusal = f"# Error: Error setting '{name}' to '{value}'!\n"
        with pytest.raises(AxisDeviceError) as caught:
            await ParamAPI(self._replying(refusal)).set(f"root.{name}", value)
        assert str(caught.value) == f"param.cgi: Error: Error setting '{name}' to '[redacted]'!"

    async def test_a_secret_quoted_outside_the_refusal_context_is_redacted(self):
        community = "rd-9fQ2zX7kLm"  # pragma: allowlist secret
        reply = f"<html>bad value {community} for SNMP</html>"
        with pytest.raises(AxisDeviceError, match="unexpected reply") as caught:
            await ParamAPI(self._replying(reply)).set("root.SNMP.ReadCommunity", community)
        assert community not in str(caught.value)

    @respx.mock
    async def test_an_echoed_credential_in_a_success_reply_is_refused(self):
        # A peer that echoes the request headers in its 200 reply. The client
        # refuses the reply rather than letting set() quote any of it.
        password = "Param-Echo-T3st!"  # pragma: allowlist secret
        token = base64.b64encode(f"root:{password}".encode()).decode()
        pad = "." * (120 - len("Basic ") - len(token) // 2)
        respx.get("https://192.0.2.10:443/axis-cgi/param.cgi").mock(
            side_effect=lambda request: httpx.Response(
                200, text=pad + request.headers["Authorization"]
            )
        )
        async with VapixClient(
            "192.0.2.10", "root", password, port=443, use_https=True, auth_mode="basic"
        ) as client:
            with pytest.raises(
                AxisDeviceError, match="quotes this request's credentials"
            ) as caught:
                await ParamAPI(client).set("Image.I0.Name", "Hall")
        fragments = [token[i : i + 8] for i in range(len(token) - 7)]
        assert [f for f in fragments if f in str(caught.value)] == []


class TestDiff:
    def test_only_differing_writable_params_become_changes(self):
        target = dict(CURRENT, **{"root.Audio.MaxListeners": "20"})

        plan = diff_params(CURRENT, target, DEFINITIONS)

        assert plan.changes == [ParamChange("root.Audio.MaxListeners", current="10", target="20")]
        assert len(plan.skipped[SkipReason.UNCHANGED]) == len(CURRENT) - 1

    def test_read_only_per_the_device_is_skipped_with_a_reason(self):
        target = dict(CURRENT, **{"root.Brand.Brand": "ACME", "root.Properties.FriendlyName": "x"})

        plan = diff_params(CURRENT, target, DEFINITIONS)

        assert plan.is_empty
        assert sorted(plan.skipped[SkipReason.READ_ONLY]) == [
            "root.Brand.Brand",
            "root.Properties.FriendlyName",
        ]

    def test_without_definitions_every_difference_is_a_change(self):
        # No listdefinitions: the device's # Error at apply time is the authority.
        target = dict(CURRENT, **{"root.Brand.Brand": "ACME"})

        plan = diff_params(CURRENT, target)

        assert [c.name for c in plan.changes] == ["root.Brand.Brand"]

    def test_parameter_without_a_definition_is_attempted(self):
        target = dict(CURRENT, **{"root.Audio.MaxListeners": "20"})
        defs = {k: v for k, v in DEFINITIONS.items() if k != "root.Audio.MaxListeners"}

        plan = diff_params(CURRENT, target, defs)

        assert [c.name for c in plan.changes] == ["root.Audio.MaxListeners"]

    def test_network_excluded_unless_asked(self):
        target = dict(CURRENT, **{"root.Network.eth0.IPAddress": "192.168.10.99"})

        plan = diff_params(CURRENT, target, DEFINITIONS)
        assert plan.is_empty and plan.skipped[SkipReason.NETWORK] == ["root.Network.eth0.IPAddress"]

        plan = diff_params(CURRENT, target, DEFINITIONS, include_network=True)
        assert [c.name for c in plan.changes] == ["root.Network.eth0.IPAddress"]
        assert plan.changes[0].group == "Network"

    def test_params_missing_on_device_are_skipped(self):
        target = dict(CURRENT, **{"root.Gone.Param": "1"})

        plan = diff_params(CURRENT, target)

        assert plan.skipped[SkipReason.MISSING_ON_DEVICE] == ["root.Gone.Param"]

    def test_credentials_excluded_unless_asked(self):
        current = dict(
            CURRENT, **{"root.SNMP.WriteCommunity": "old", "root.Audio.MaxListeners": "10"}
        )
        target = dict(
            current, **{"root.SNMP.WriteCommunity": "new", "root.Audio.MaxListeners": "20"}
        )

        plan = diff_params(current, target)
        assert [c.name for c in plan.changes] == ["root.Audio.MaxListeners"]
        assert plan.skipped[SkipReason.CREDENTIAL] == ["root.SNMP.WriteCommunity"]

        plan = diff_params(current, target, include_secrets=True)
        assert sorted(c.name for c in plan.changes) == [
            "root.Audio.MaxListeners",
            "root.SNMP.WriteCommunity",
        ]

    def test_unchanged_credential_is_unchanged_not_credential(self):
        current = dict(CURRENT, **{"root.SNMP.WriteCommunity": "same"})
        plan = diff_params(current, current)
        assert "root.SNMP.WriteCommunity" in plan.skipped[SkipReason.UNCHANGED]
        assert plan.skipped[SkipReason.CREDENTIAL] == []

    def test_skip_counts_omit_zero_reasons(self):
        plan = diff_params(CURRENT, CURRENT)
        assert plan.skip_counts() == {SkipReason.UNCHANGED.value: len(CURRENT)}


class TestLoadBackup:
    def test_reads_params_and_identity(self, tmp_path):
        root = _backup_dir(tmp_path, CURRENT)

        params, identity = load_backup_params(root)

        assert params == CURRENT and identity["serial_number"] == "B8A44F9F0228"

    def test_backup_without_params_file(self, tmp_path):
        root = _backup_dir(tmp_path, CURRENT)
        (root / "params.json").unlink()
        manifest = json.loads((root / MANIFEST_FILE).read_text())
        manifest["files"] = []
        (root / MANIFEST_FILE).write_text(json.dumps(manifest))

        with pytest.raises(FileNotFoundError, match=r"contains no params\.json"):
            load_backup_params(root)

    def test_wrong_shape_is_rejected(self, tmp_path):
        root = _backup_dir(tmp_path, {"root.A": "1"})
        content = json.dumps({"root.A": {"nested": 1}}).encode()
        (root / "params.json").write_bytes(content)
        _rehash(root, content)

        with pytest.raises(ValueError, match="flat mapping"):
            load_backup_params(root)

    def test_edited_params_file_is_refused(self, tmp_path):
        # The manifest vouches for a hash; a file that no longer matches is not restored.
        root = _backup_dir(tmp_path, CURRENT)
        edited = dict(CURRENT, **{"root.Audio.MaxListeners": "1"})
        (root / "params.json").write_text(json.dumps(edited))

        with pytest.raises(ValueError, match="does not match the hash"):
            load_backup_params(root)


class TestPlan:
    async def test_plan_reads_the_device_and_never_writes(self, tmp_path):
        root = _backup_dir(tmp_path, dict(CURRENT, **{"root.Audio.MaxListeners": "20"}))
        device = _device(CURRENT)

        plan = await plan_param_restore(device, root)

        assert [c.name for c in plan.changes] == ["root.Audio.MaxListeners"]
        assert plan.backup_dir == root and plan.device_identity["serial_number"] == "B8A44F9F0228"
        device.params.definitions.assert_awaited_once()
        cast("MagicMock", device.params).set.assert_not_awaited()

    async def test_plan_uses_the_device_definitions_to_skip_read_only(self, tmp_path):
        root = _backup_dir(tmp_path, dict(CURRENT, **{"root.Brand.Brand": "ACME"}))

        plan = await plan_param_restore(_device(CURRENT), root)

        assert plan.is_empty and plan.skipped[SkipReason.READ_ONLY] == ["root.Brand.Brand"]

    async def test_refuses_a_backup_from_another_device(self, tmp_path):
        root = _backup_dir(tmp_path, CURRENT, serial="ACCC8E000001")
        device = _device(CURRENT)

        with pytest.raises(ValueError, match="refusing to restore across devices"):
            await plan_param_restore(device, root)

    async def test_backup_without_serial_is_allowed(self, tmp_path):
        root = _backup_dir(tmp_path, CURRENT, serial=None)
        plan = await plan_param_restore(_device(CURRENT), root)
        assert plan.is_empty

    async def test_auth_error_propagates(self, tmp_path):
        root = _backup_dir(tmp_path, CURRENT)
        device = _device(CURRENT)
        device.params.export = AsyncMock(side_effect=AxisAuthenticationError("401"))

        with pytest.raises(AxisAuthenticationError):
            await plan_param_restore(device, root)


class TestApply:
    async def test_drift_since_the_plan_refuses_before_any_write(self):
        target = dict(
            CURRENT,
            **{"root.Audio.MaxListeners": "20", "root.Image.I0.Appearance.Compression": "40"},
        )
        plan = diff_params(CURRENT, target)
        # someone changed one planned parameter between plan and apply
        device = _device(dict(CURRENT, **{"root.Image.I0.Appearance.Compression": "35"}))

        with pytest.raises(RestoreDriftError) as excinfo:
            await apply_param_restore(device, plan)

        assert excinfo.value.names == ["root.Image.I0.Appearance.Compression"]
        assert "root.Image.I0.Appearance.Compression" in str(excinfo.value)
        cast("MagicMock", device.params).set.assert_not_awaited()

    async def test_drifted_credential_is_named_but_its_value_is_not(self):
        current = dict(CURRENT, **{"root.SNMP.ReadCommunity": "old-community"})
        target = dict(current, **{"root.SNMP.ReadCommunity": "backup-community"})
        plan = diff_params(current, target, include_secrets=True)
        device = _device(dict(current, **{"root.SNMP.ReadCommunity": "rotated-community"}))

        with pytest.raises(RestoreDriftError) as excinfo:
            await apply_param_restore(device, plan)

        message = str(excinfo.value)
        assert "root.SNMP.ReadCommunity" in message
        assert not any(
            v in message for v in ("old-community", "rotated-community", "backup-community")
        )

    async def test_a_different_device_refuses_before_any_write(self):
        target = dict(CURRENT, **{"root.Audio.MaxListeners": "20"})
        plan = diff_params(CURRENT, target)
        plan.device_identity = {"serial_number": "ACCC8E999999"}
        device = _device(CURRENT)

        with pytest.raises(RestoreDriftError, match="serial"):
            await apply_param_restore(device, plan)
        cast("MagicMock", device.params).set.assert_not_awaited()

    async def test_an_empty_plan_reads_nothing(self):
        device = _device(CURRENT)
        assert await apply_param_restore(device, diff_params(CURRENT, CURRENT)) == []
        cast("MagicMock", device.params).export.assert_not_awaited()

    async def test_writes_each_change_and_verifies(self):
        target = dict(
            CURRENT,
            **{"root.Audio.MaxListeners": "20", "root.Image.I0.Appearance.Compression": "40"},
        )
        plan = diff_params(CURRENT, target)
        device = _device(CURRENT)

        results = await apply_param_restore(device, plan)

        assert [(r.change.name, r.ok, r.detail) for r in results] == [
            ("root.Audio.MaxListeners", True, "verified"),
            ("root.Image.I0.Appearance.Compression", True, "verified"),
        ]
        assert device.params.set.await_count == 2 and device.params.get.await_count == 2

    async def test_device_refusal_is_recorded_and_the_run_continues(self):
        target = dict(
            CURRENT,
            **{"root.Audio.MaxListeners": "20", "root.Image.I0.Appearance.Compression": "40"},
        )
        plan = diff_params(CURRENT, target)
        device = _device(
            CURRENT,
            set_results={
                "root.Audio.MaxListeners": AxisDeviceError("param.cgi: Error setting ...")
            },
        )

        results = await apply_param_restore(device, plan)

        assert results[0].ok is False and "Error setting" in results[0].detail
        assert results[1].ok is True

    async def test_accepted_but_not_kept_is_a_failure(self):
        target = dict(CURRENT, **{"root.Audio.MaxListeners": "20"})
        plan = diff_params(CURRENT, target)
        device = _device(CURRENT, set_results={"root.Audio.MaxListeners": "10"})  # keeps old value

        results = await apply_param_restore(device, plan)

        assert results == [
            ChangeResult(plan.changes[0], False, "device accepted the update but reads back '10'")
        ]

    async def test_a_secret_read_back_is_not_quoted(self):
        # restore --include-secrets prints this detail; a credential's read-back
        # value is a secret even when it is the wrong one.
        current = {"root.SNMP.ReadCommunity": "old-c0mmunity"}  # pragma: allowlist secret
        target = {"root.SNMP.ReadCommunity": "new-c0mmunity"}  # pragma: allowlist secret
        plan = diff_params(current, target, include_secrets=True)
        assert plan.changes, "precondition: the credential is in the plan"
        device = _device(current, set_results={"root.SNMP.ReadCommunity": "other-c0mm"})

        results = await apply_param_restore(device, plan)

        assert results[0].ok is False
        assert "other-c0mm" not in results[0].detail
        assert results[0].detail == (
            "device accepted the update but reads back a different value (withheld: a credential)"
        )

    async def test_auth_error_aborts(self):
        plan = diff_params(CURRENT, dict(CURRENT, **{"root.Audio.MaxListeners": "20"}))
        device = _device(CURRENT)
        device.params.set = AsyncMock(side_effect=AxisAuthenticationError("401"))

        with pytest.raises(AxisAuthenticationError):
            await apply_param_restore(device, plan)
