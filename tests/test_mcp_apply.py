"""Phase B: apply_plan, the one tool that writes to a device.

Every test drives the real tool through the SDK client. The confirmation is a
real elicitation round trip: the test's callback plays the human. A client
without an elicitation callback declares no elicitation capability -- that is
what kiro-cli 2.30.0 does today -- and must get an error and no write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal
from unittest.mock import AsyncMock

import mcp.types as t
from mcp import Client

from axis_cam.mcp_server.plans import PlanStore
from axis_cam.mcp_server.server import build_server
from axis_cam.models import UserAccount, UserAccounts, UserRole
from tests.mcp_fakes import ACCOUNTS, CANARY, PARAMS, FakeResolver, two_cameras

if TYPE_CHECKING:
    from pathlib import Path


def _text(result: Any) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


class Human:
    """An elicitation callback that records what it was shown and answers."""

    def __init__(
        self, action: Literal["accept", "decline", "cancel"] = "accept", approve: bool = True
    ) -> None:
        self.action: Literal["accept", "decline", "cancel"] = action
        self.approve = approve
        self.seen: list[str] = []

    async def __call__(self, context: Any, params: Any) -> t.ElicitResult:
        self.seen.append(params.message)
        if self.action == "accept":
            return t.ElicitResult(action="accept", content={"approve": self.approve})
        return t.ElicitResult(action=self.action)


def _writable(resolver: FakeResolver, name: str = "back_of_house") -> Any:
    """Make the fake's params writable: set() updates state, get() reads it."""
    dev = resolver.device(name)
    state = dict(dev.params.export.return_value)

    async def fake_set(param: str, value: str) -> None:
        state[param] = value

    async def fake_get(param: str) -> str | None:
        return state.get(param)

    dev.params.set = AsyncMock(side_effect=fake_set)
    dev.params.get = AsyncMock(side_effect=fake_get)
    dev.params.export = AsyncMock(side_effect=lambda: dict(state))
    return dev, state


async def _restore_plan(client: Client, dev: Any, state: dict[str, str]) -> dict[str, Any]:
    backup_id = (
        await client.call_tool("backup_create", {"device": "back_of_house"})
    ).structured_content["backup_id"]
    state["root.Image.I0.Name"] = "Changed"  # the device drifts after the backup
    return (
        await client.call_tool("plan_restore", {"device": "back_of_house", "backup_id": backup_id})
    ).structured_content


class TestFailClosed:
    async def test_host_without_elicitation_gets_an_error_and_nothing_is_written(
        self, tmp_path: Path
    ) -> None:
        resolver = two_cameras()
        dev, state = _writable(resolver)
        store = PlanStore()
        async with Client(build_server(resolver, backup_root=tmp_path, plans=store)) as client:
            plan = await _restore_plan(client, dev, state)
            result = await client.call_tool("apply_plan", {"plan_id": plan["plan_id"]})
        assert result.is_error is True
        assert "cannot show a confirmation" in _text(result)
        dev.params.set.assert_not_awaited()
        assert store.get(plan["plan_id"]) is not None  # the plan is untouched
        assert state["root.Image.I0.Name"] == "Changed"

    async def test_unknown_plan(self) -> None:
        async with Client(build_server(two_cameras()), elicitation_callback=Human()) as client:
            result = await client.call_tool("apply_plan", {"plan_id": "nope"})
        assert result.is_error is True and "unknown or expired" in _text(result)


class TestRestore:
    async def test_accepted_plan_is_applied_verified_and_single_use(self, tmp_path: Path) -> None:
        resolver = two_cameras()
        dev, state = _writable(resolver)
        human = Human()
        server = build_server(resolver, backup_root=tmp_path)
        async with Client(server, elicitation_callback=human) as client:
            plan = await _restore_plan(client, dev, state)
            first = await client.call_tool("apply_plan", {"plan_id": plan["plan_id"]})
            second = await client.call_tool("apply_plan", {"plan_id": plan["plan_id"]})

        assert first.is_error is False, _text(first)
        body = first.structured_content
        assert body["status"] == "applied"
        assert body["results"] == [{"name": "root.Image.I0.Name", "ok": True, "detail": "verified"}]
        dev.params.set.assert_awaited_once_with("root.Image.I0.Name", "View Area 1")
        assert state["root.Image.I0.Name"] == "View Area 1"
        # the human saw the stored plan, rendered by the server
        assert len(human.seen) == 1
        assert "back_of_house" in human.seen[0] and "ACCC8E000001" in human.seen[0]
        assert "root.Image.I0.Name: 'Changed' -> 'View Area 1'" in human.seen[0]
        assert CANARY not in human.seen[0]
        # and the handle cannot be replayed
        assert second.is_error is True

    async def test_declined_writes_nothing_and_keeps_the_plan(self, tmp_path: Path) -> None:
        for human in (Human(action="decline"), Human(action="cancel"), Human(approve=False)):
            resolver = two_cameras()
            dev, state = _writable(resolver)
            store = PlanStore()
            server = build_server(resolver, backup_root=tmp_path / str(id(human)), plans=store)
            async with Client(server, elicitation_callback=human) as client:
                plan = await _restore_plan(client, dev, state)
                result = await client.call_tool("apply_plan", {"plan_id": plan["plan_id"]})
            assert result.is_error is False, _text(result)
            assert result.structured_content["status"] == "declined"
            dev.params.set.assert_not_awaited()
            assert store.get(plan["plan_id"]) is not None

    async def test_drift_since_the_plan_is_refused(self, tmp_path: Path) -> None:
        resolver = two_cameras()
        dev, state = _writable(resolver)
        async with Client(
            build_server(resolver, backup_root=tmp_path), elicitation_callback=Human()
        ) as client:
            plan = await _restore_plan(client, dev, state)
            state["root.Image.I0.Name"] = "Someone else changed it"
            result = await client.call_tool("apply_plan", {"plan_id": plan["plan_id"]})
        body = result.structured_content
        assert body["status"] == "refused" and "root.Image.I0.Name" in body["reason"]
        dev.params.set.assert_not_awaited()

    async def test_another_device_behind_the_same_name_is_refused(self, tmp_path: Path) -> None:
        resolver = two_cameras()
        dev, state = _writable(resolver)
        async with Client(
            build_server(resolver, backup_root=tmp_path), elicitation_callback=Human()
        ) as client:
            plan = await _restore_plan(client, dev, state)
            dev._info = dev._info.model_copy(update={"serial_number": "ACCC8E999999"})
            result = await client.call_tool("apply_plan", {"plan_id": plan["plan_id"]})
        body = result.structured_content
        assert body["status"] == "refused" and "ACCC8E999999" in body["reason"]
        dev.params.set.assert_not_awaited()


class TestAccounts:
    async def test_role_change_is_applied(self) -> None:
        resolver = two_cameras()
        dev = resolver.device("back_of_house")
        dev.users.set_role = AsyncMock()
        async with Client(build_server(resolver), elicitation_callback=Human()) as client:
            plan = (
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
            result = await client.call_tool("apply_plan", {"plan_id": plan["plan_id"]})
        assert result.structured_content["status"] == "applied", _text(result)
        dev.users.set_role.assert_awaited_once_with("second", UserRole.OPERATOR)

    async def test_plan_the_guard_refuses_is_never_attempted(self) -> None:
        resolver = two_cameras()
        dev = resolver.device("back_of_house")
        dev.users.remove = AsyncMock()
        async with Client(build_server(resolver), elicitation_callback=Human()) as client:
            plan = (
                await client.call_tool(
                    "plan_account_change",
                    {"device": "back_of_house", "account": "admin", "action": "remove"},
                )
            ).structured_content
            result = await client.call_tool("apply_plan", {"plan_id": plan["plan_id"]})
        assert result.structured_content["status"] == "refused"
        dev.users.remove.assert_not_awaited()

    async def test_account_changed_since_the_plan_is_refused(self) -> None:
        resolver = two_cameras()
        dev = resolver.device("back_of_house")
        dev.users.set_role = AsyncMock()
        async with Client(build_server(resolver), elicitation_callback=Human()) as client:
            plan = (
                await client.call_tool(
                    "plan_account_change",
                    {
                        "device": "back_of_house",
                        "account": "second",
                        "action": "set_role",
                        "role": "viewer",
                    },
                )
            ).structured_content
            changed = UserAccounts(
                accounts=[
                    a
                    if a.username != "second"
                    else UserAccount(username="second", role=UserRole.OPERATOR)
                    for a in ACCOUNTS.accounts
                ]
            )
            dev.users.list.return_value = changed
            result = await client.call_tool("apply_plan", {"plan_id": plan["plan_id"]})
        assert result.structured_content["status"] == "refused"
        dev.users.set_role.assert_not_awaited()


def test_params_fixture_has_the_label() -> None:
    assert PARAMS["root.Image.I0.Name"] == "View Area 1"
