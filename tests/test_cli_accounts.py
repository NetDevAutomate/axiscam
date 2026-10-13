"""Tests for ``axiscam accounts`` and the write-safety pattern it establishes.

``DeviceContext.open`` is patched with a fake device whose ``users`` module
records calls, so each test can assert exactly which writes happened.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from axis_cam.cli import DeviceContext, app
from axis_cam.config import AppConfig
from axis_cam.exceptions import AxisLockoutError, AxisUserError
from axis_cam.models import UserAccount, UserAccounts, UserRole

runner = CliRunner()
HOST_ARGS = ["--host", "10.0.0.5", "-u", "root", "-p", "rootpw"]

ROOT = UserAccount(username="root", role=UserRole.ADMIN, ptz=True)
JOE = UserAccount(username="joe", role=UserRole.ADMIN, ptz=True)
FRANK = UserAccount(username="frank", role=UserRole.VIEWER)


class FakeUsers:
    def __init__(self, accounts: list[UserAccount]):
        self.list = AsyncMock(return_value=UserAccounts(accounts=accounts))
        self.add = AsyncMock(
            return_value=UserAccount(username="ops", role=UserRole.OPERATOR, ptz=False)
        )
        self.set_password = AsyncMock(return_value=None)
        self.set_role = AsyncMock(
            return_value=UserAccount(username="frank", role=UserRole.OPERATOR, ptz=True)
        )
        self.remove = AsyncMock(return_value=None)

    def writes(self) -> int:
        return sum(m.await_count for m in (self.add, self.set_password, self.set_role, self.remove))


class FakeDevice:
    def __init__(self, users: FakeUsers):
        self.host = "10.0.0.5"
        self.users = users

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
    return FakeUsers([ROOT, JOE, FRANK])


def _text(result) -> str:
    """Output with Rich panel borders and line wrapping removed."""
    return " ".join(result.output.replace("│", " ").split())


def _run(users: FakeUsers, args: list[str], input: str | None = None):
    with patch.object(DeviceContext, "open", return_value=FakeDevice(users)):
        return runner.invoke(app, ["accounts", *args, *HOST_ARGS], input=input)


class TestList:
    def test_table(self, no_config, users):
        result = _run(users, ["list"])

        assert result.exit_code == 0, result.output
        for name in ("root", "joe", "frank"):
            assert name in _text(result)
        assert "admin" in _text(result) and "viewer" in _text(result)

    def test_json(self, no_config, users):
        result = _run(users, ["list", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert [a["username"] for a in data["accounts"]] == ["root", "joe", "frank"]
        assert data["accounts"][0]["role"] == "admin"


class TestWriteSafetyPattern:
    """The contract every write command follows."""

    def test_dry_run_shows_the_plan_and_writes_nothing(self, no_config, users):
        result = _run(users, ["add", "ops", "--role", "operator", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "Planned change" in _text(result)
        assert "Create account 'ops' with role operator" in _text(result)
        assert "3 account(s)" in _text(result)
        assert "Dry run" in _text(result)
        assert users.writes() == 0

    def test_dry_run_does_not_prompt_for_a_password(self, no_config, users):
        # No input provided: a prompt would make CliRunner abort.
        result = _run(users, ["add", "ops", "--role", "operator", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "New password" not in _text(result)

    def test_declining_the_confirmation_writes_nothing_and_exits_1(self, no_config, users):
        result = _run(users, ["remove", "frank"], input="n\n")

        assert result.exit_code == 1
        assert "Apply this change?" in _text(result)
        assert "Aborted" in _text(result)
        assert users.writes() == 0

    def test_accepting_the_confirmation_writes(self, no_config, users):
        result = _run(users, ["remove", "frank"], input="y\n")

        assert result.exit_code == 0, result.output
        users.remove.assert_awaited_once_with("frank", allow_lockout=False)
        assert "Removed and verified" in _text(result)

    def test_yes_skips_the_prompt(self, no_config, users):
        result = _run(users, ["remove", "frank", "--yes"])

        assert result.exit_code == 0, result.output
        assert "Apply this change?" not in _text(result)
        users.remove.assert_awaited_once()

    def test_library_lockout_refusal_is_one_line_exit_1(self, no_config, users):
        users.remove.side_effect = AxisLockoutError("refusing to remove 'root': only administrator")

        result = _run(users, ["remove", "root", "--yes"])

        assert result.exit_code == 1
        assert "Error: refusing to remove 'root'" in _text(result)
        assert "Traceback" not in _text(result)

    def test_device_refusal_is_one_line_exit_1(self, no_config, users):
        users.set_password.side_effect = AxisUserError("could not change the password: policy")

        result = _run(users, ["set-password", "frank", "--yes"], input="Str0ng-pass\nStr0ng-pass\n")

        assert result.exit_code == 1
        assert "Error: could not change the password" in _text(result)


class TestAdd:
    def test_prompts_for_password_after_confirmation_and_never_in_argv(self, no_config, users):
        result = _run(
            users,
            ["add", "ops", "--role", "operator", "--comment", "Ops team"],
            input="y\nSup3r-secret\nSup3r-secret\n",
        )

        assert result.exit_code == 0, result.output
        users.add.assert_awaited_once_with(
            "ops",
            "Sup3r-secret",
            UserRole.OPERATOR,
            ptz=False,
            comment="Ops team",
            strict_password=True,
        )
        # The prompt hides input: the secret is never echoed.
        assert "Sup3r-secret" not in _text(result)
        assert "Created and verified" in _text(result)

    def test_password_stdin_for_automation(self, no_config, users):
        result = _run(
            users,
            ["add", "ops", "--role", "viewer", "--ptz", "--yes", "--password-stdin"],
            input="Fr0m-stdin\n",
        )

        assert result.exit_code == 0, result.output
        users.add.assert_awaited_once_with(
            "ops", "Fr0m-stdin", UserRole.VIEWER, ptz=True, comment="", strict_password=True
        )

    def test_empty_stdin_is_a_usage_error_before_any_request(self, no_config, users):
        result = _run(
            users, ["add", "ops", "--role", "viewer", "--yes", "--password-stdin"], input=""
        )

        assert result.exit_code != 0
        assert "standard input" in _text(result)
        users.list.assert_not_awaited()

    def test_invalid_username_is_rejected_by_typer(self, no_config, users):
        result = _run(users, ["add", "bad-name", "--role", "viewer", "--yes"])

        assert result.exit_code == 2
        assert "1-14 characters" in _text(result)
        users.list.assert_not_awaited()

    def test_existing_account_is_refused_before_the_plan(self, no_config, users):
        result = _run(users, ["add", "joe", "--role", "viewer", "--yes"])

        assert result.exit_code == 1
        assert "already exists" in _text(result)
        assert "Planned change" not in _text(result)
        assert users.writes() == 0

    def test_password_failing_local_validation_is_one_line(self, no_config, users):
        result = _run(
            users, ["add", "ops", "--role", "viewer", "--yes"], input="pässword\npässword\n"
        )

        assert result.exit_code == 1
        assert "printable ASCII" in _text(result)
        assert users.writes() == 0

    def test_no_strict_is_forwarded(self, no_config, users):
        result = _run(
            users,
            ["add", "ops", "--role", "viewer", "--yes", "--no-strict", "--password-stdin"],
            input="pässword\n",
        )

        assert result.exit_code == 0, result.output
        assert users.add.await_args.kwargs["strict_password"] is False


class TestSetPassword:
    def test_warns_when_rotating_your_own_credential(self, no_config, users):
        result = _run(users, ["set-password", "root", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "logged in as" in _text(result) and "config file" in _text(result)

    def test_rotates_with_stdin(self, no_config, users):
        result = _run(
            users, ["set-password", "frank", "--yes", "--password-stdin"], input="N3w-pass\n"
        )

        assert result.exit_code == 0, result.output
        users.set_password.assert_awaited_once_with("frank", "N3w-pass", strict_password=True)
        assert "cannot be verified by reading" in _text(result)

    def test_unknown_account(self, no_config, users):
        result = _run(users, ["set-password", "nobody", "--yes"])

        assert result.exit_code == 1 and "does not exist" in _text(result)
        assert users.writes() == 0


class TestSetRoleAndRemoveWarnings:
    def test_set_role_forwards_ptz_and_allow_lockout(self, no_config, users):
        result = _run(
            users, ["set-role", "frank", "--role", "operator", "--ptz", "--yes", "--allow-lockout"]
        )

        assert result.exit_code == 0, result.output
        users.set_role.assert_awaited_once_with(
            "frank", UserRole.OPERATOR, ptz=True, allow_lockout=True
        )
        assert "Updated and verified" in _text(result)

    def test_de_admin_self_warns_in_the_plan(self, no_config, users):
        result = _run(users, ["set-role", "root", "--role", "operator", "--dry-run"])

        assert "lose administrator access" in _text(result)
        assert "--allow-lockout" in _text(result)

    def test_last_admin_warns_in_the_plan(self, no_config):
        only_admin = FakeUsers([ROOT, FRANK])

        result = _run(only_admin, ["remove", "root", "--dry-run"])

        assert "only administrator" in _text(result)

    def test_remove_self_as_viewer_warns(self, no_config):
        users = FakeUsers([ROOT, FRANK])
        with patch.object(DeviceContext, "open", return_value=FakeDevice(users)):
            result = runner.invoke(
                app,
                [
                    "accounts",
                    "remove",
                    "frank",
                    "--dry-run",
                    "--host",
                    "10.0.0.5",
                    "-u",
                    "frank",
                    "-p",
                    "pw",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "logged in as" in _text(result) and "--allow-lockout" in _text(result)

    def test_non_admin_changing_own_role_has_no_lockout_warning(self, no_config):
        users = FakeUsers([ROOT, FRANK])
        with patch.object(DeviceContext, "open", return_value=FakeDevice(users)):
            result = runner.invoke(
                app,
                [
                    "accounts",
                    "set-role",
                    "frank",
                    "--role",
                    "operator",
                    "--dry-run",
                    "--host",
                    "10.0.0.5",
                    "-u",
                    "frank",
                    "-p",
                    "pw",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Warning" not in _text(result)

    def test_removing_another_admin_with_one_left_has_no_warning(self, no_config, users):
        result = _run(users, ["remove", "joe", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "Warning" not in _text(result)
