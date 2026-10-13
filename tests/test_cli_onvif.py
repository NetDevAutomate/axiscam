"""Tests for ``axiscam onvif``: the write-safety pattern on the ONVIF user database.

``DeviceContext.open`` is patched with a fake device whose ``onvif_users``
module records calls, so each test can assert exactly which writes happened.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from axis_cam.cli import DeviceContext, app
from axis_cam.config import AppConfig
from axis_cam.exceptions import AxisLockoutError, AxisSoapFault
from axis_cam.models import OnvifAccount, OnvifAccounts, OnvifUserLevel

runner = CliRunner()
HOST_ARGS = ["--host", "10.0.0.5", "-u", "root", "-p", "rootpw"]
ONVIF = OnvifAccount(username="onvif", level=OnvifUserLevel.ADMINISTRATOR)
VMS = OnvifAccount(username="vms", level=OnvifUserLevel.OPERATOR)


class FakeOnvifUsers:
    def __init__(self, accounts: list[OnvifAccount]):
        self.list = AsyncMock(return_value=OnvifAccounts(accounts=accounts))
        self.add = AsyncMock(
            return_value=OnvifAccount(username="nvr", level=OnvifUserLevel.OPERATOR)
        )
        self.set_password = AsyncMock(return_value=None)
        self.set_level = AsyncMock(
            return_value=OnvifAccount(username="vms", level=OnvifUserLevel.USER)
        )
        self.remove = AsyncMock(return_value=None)

    def writes(self) -> int:
        return sum(
            m.await_count for m in (self.add, self.set_password, self.set_level, self.remove)
        )


class FakeDevice:
    def __init__(self, onvif_users: FakeOnvifUsers):
        self.host = "10.0.0.5"
        self.onvif_users = onvif_users

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None


@pytest.fixture
def no_config():
    with patch("axis_cam.cli.context.load_config", return_value=AppConfig()):
        yield


@pytest.fixture
def users():
    return FakeOnvifUsers([ONVIF, VMS])


def _text(result) -> str:
    """Output with Rich panel borders and line wrapping removed."""
    return " ".join(result.output.replace("│", " ").split())


def _run(users: FakeOnvifUsers, args: list[str], input: str | None = None):
    with patch.object(DeviceContext, "open", return_value=FakeDevice(users)):
        return runner.invoke(app, ["onvif", *args, *HOST_ARGS], input=input)


class TestList:
    def test_table(self, no_config, users):
        result = _run(users, ["list"])

        assert result.exit_code == 0, result.output
        assert "onvif" in _text(result) and "Administrator" in _text(result)
        assert "vms" in _text(result) and "Operator" in _text(result)

    def test_json(self, no_config, users):
        result = _run(users, ["list", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert [(a["username"], a["level"]) for a in data["accounts"]] == [
            ("onvif", "Administrator"),
            ("vms", "Operator"),
        ]

    def test_empty_database(self, no_config):
        result = _run(FakeOnvifUsers([]), ["list"])
        assert result.exit_code == 0 and "none" in _text(result)


class TestWriteSafetyPattern:
    def test_dry_run_shows_the_plan_and_writes_nothing(self, no_config, users):
        result = _run(users, ["add", "nvr", "--level", "operator", "--dry-run"])

        assert result.exit_code == 0, result.output
        text = _text(result)
        assert "Planned change" in text
        assert "Create ONVIF user 'nvr' with level Operator" in text
        assert "2 ONVIF user(s)" in text and "Dry run" in text
        assert users.writes() == 0

    def test_declining_writes_nothing(self, no_config, users):
        result = _run(users, ["add", "nvr", "--level", "operator"], input="n\n")
        assert result.exit_code == 1 and users.writes() == 0

    def test_yes_with_password_stdin_creates(self, no_config, users):
        result = _run(
            users,
            ["add", "nvr", "--level", "operator", "--yes", "--password-stdin"],
            input="S3cret-pass\n",
        )

        assert result.exit_code == 0, result.output
        users.add.assert_awaited_once_with("nvr", "S3cret-pass", OnvifUserLevel.OPERATOR)
        assert "Created and verified" in _text(result)
        assert "S3cret-pass" not in result.output  # never echoed

    def test_password_is_prompted_after_confirmation(self, no_config, users):
        # confirm "y", then the hidden prompt twice (entry + confirmation)
        result = _run(
            users, ["add", "nvr", "--level", "user"], input="y\nS3cret-pass\nS3cret-pass\n"
        )

        assert result.exit_code == 0, result.output
        users.add.assert_awaited_once_with("nvr", "S3cret-pass", OnvifUserLevel.USER)

    def test_no_password_option_exists(self, no_config, users):
        result = _run(users, ["add", "nvr", "--level", "user", "--new-password", "x"])
        assert result.exit_code != 0 and users.writes() == 0

    def test_existing_user_is_refused_before_the_plan(self, no_config, users):
        result = _run(users, ["add", "vms", "--level", "user", "--yes"])
        assert result.exit_code == 1 and "already exists" in _text(result)
        assert users.writes() == 0


class TestSetPassword:
    def test_warns_about_clients_and_applies(self, no_config, users):
        result = _run(
            users, ["set-password", "vms", "--yes", "--password-stdin"], input="N3w-pass\n"
        )

        assert result.exit_code == 0, result.output
        users.set_password.assert_awaited_once_with("vms", "N3w-pass")
        text = _text(result)
        assert "every ONVIF client using this user" in text
        assert "ONVIF never returns passwords" in text

    def test_unknown_user(self, no_config, users):
        result = _run(
            users, ["set-password", "ghost", "--yes", "--password-stdin"], input="x-pass\n"
        )
        assert result.exit_code == 1 and "does not exist" in _text(result)


class TestSetLevel:
    def test_applies_and_prints_verified_result(self, no_config, users):
        result = _run(users, ["set-level", "vms", "--level", "user", "--yes"])

        assert result.exit_code == 0, result.output
        users.set_level.assert_awaited_once_with("vms", OnvifUserLevel.USER, allow_lockout=False)
        assert "Updated and verified: vms (User)" in _text(result)

    def test_warns_when_demoting_the_only_administrator(self, no_config, users):
        result = _run(users, ["set-level", "onvif", "--level", "operator", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "only ONVIF Administrator" in _text(result)
        assert "--allow-lockout" in _text(result)

    def test_library_lockout_refusal_surfaces(self, no_config, users):
        users.set_level = AsyncMock(
            side_effect=AxisLockoutError("refusing: only ONVIF Administrator")
        )
        result = _run(users, ["set-level", "onvif", "--level", "operator", "--yes"])
        assert result.exit_code == 1 and "only ONVIF Administrator" in _text(result)


class TestRemove:
    def test_removes_and_verifies(self, no_config, users):
        result = _run(users, ["remove", "vms", "--yes"])

        assert result.exit_code == 0, result.output
        users.remove.assert_awaited_once_with("vms", allow_lockout=False)
        assert "Removed and verified" in _text(result)

    def test_allow_lockout_is_passed_through(self, no_config, users):
        result = _run(users, ["remove", "onvif", "--yes", "--allow-lockout"])
        assert result.exit_code == 0, result.output
        users.remove.assert_awaited_once_with("onvif", allow_lockout=True)

    def test_device_fault_surfaces_with_its_meaning(self, no_config, users):
        users.remove = AsyncMock(
            side_effect=AxisSoapFault(
                "HTTP 400: the device does not allow changing or deleting that user — device said: "
                "fixed (ter:FixedUser)",
                code="SOAP-ENV:Sender",
                subcodes=["ter:InvalidArgVal", "ter:FixedUser"],
                reason="fixed",
            )
        )
        result = _run(users, ["remove", "vms", "--yes"])
        assert result.exit_code == 1 and "ter:FixedUser" in _text(result)

    def test_invalid_name_is_rejected_by_the_cli(self, no_config, users):
        result = _run(users, ["remove", "bad name", "--yes"])
        assert result.exit_code != 0 and users.writes() == 0
