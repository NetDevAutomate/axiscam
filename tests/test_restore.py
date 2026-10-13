"""Tests for the params-only restore path (Phase 5, narrowed)."""

import json
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from axis_cam.api.param import ParamAPI
from axis_cam.backup import MANIFEST_FILE, BackupFile, BackupManifest
from axis_cam.devices.base import AxisDevice
from axis_cam.exceptions import AxisAuthenticationError, AxisDeviceError
from axis_cam.restore import (
    SERIAL_PARAM,
    ChangeResult,
    ParamChange,
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


def _device(current: dict[str, str], *, set_results=None) -> AxisDevice:
    params = MagicMock()
    params.export = AsyncMock(return_value=dict(current))
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


class TestDiff:
    def test_only_differing_writable_params_become_changes(self):
        target = dict(CURRENT, **{"root.Audio.MaxListeners": "20"})

        plan = diff_params(CURRENT, target)

        assert plan.changes == [ParamChange("root.Audio.MaxListeners", current="10", target="20")]
        assert len(plan.skipped[SkipReason.UNCHANGED]) == len(CURRENT) - 1

    def test_identity_groups_are_skipped_with_a_reason(self):
        target = dict(CURRENT, **{"root.Brand.Brand": "ACME", "root.Properties.FriendlyName": "x"})

        plan = diff_params(CURRENT, target)

        assert plan.is_empty
        assert sorted(plan.skipped[SkipReason.IDENTITY]) == [
            "root.Brand.Brand",
            "root.Properties.FriendlyName",
        ]

    def test_network_excluded_unless_asked(self):
        target = dict(CURRENT, **{"root.Network.eth0.IPAddress": "192.168.10.99"})

        plan = diff_params(CURRENT, target)
        assert plan.is_empty and plan.skipped[SkipReason.NETWORK] == ["root.Network.eth0.IPAddress"]

        plan = diff_params(CURRENT, target, include_network=True)
        assert [c.name for c in plan.changes] == ["root.Network.eth0.IPAddress"]
        assert plan.changes[0].group == "Network"

    def test_params_missing_on_device_are_skipped(self):
        target = dict(CURRENT, **{"root.Gone.Param": "1"})

        plan = diff_params(CURRENT, target)

        assert plan.skipped[SkipReason.MISSING_ON_DEVICE] == ["root.Gone.Param"]

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
        root = _backup_dir(tmp_path, CURRENT)
        (root / "params.json").write_text(json.dumps({"root.A": {"nested": 1}}))

        with pytest.raises(ValueError, match="flat mapping"):
            load_backup_params(root)


class TestPlan:
    async def test_plan_reads_the_device_and_never_writes(self, tmp_path):
        root = _backup_dir(tmp_path, dict(CURRENT, **{"root.Audio.MaxListeners": "20"}))
        device = _device(CURRENT)

        plan = await plan_param_restore(device, root)

        assert [c.name for c in plan.changes] == ["root.Audio.MaxListeners"]
        assert plan.backup_dir == root and plan.device_identity["serial_number"] == "B8A44F9F0228"
        device.params.set.assert_not_awaited()

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

    async def test_auth_error_aborts(self):
        plan = diff_params(CURRENT, dict(CURRENT, **{"root.Audio.MaxListeners": "20"}))
        device = _device(CURRENT)
        device.params.set = AsyncMock(side_effect=AxisAuthenticationError("401"))

        with pytest.raises(AxisAuthenticationError):
            await apply_param_restore(device, plan)
