"""The production resolver: config file entries -> names, summaries, connections."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from axis_cam.config import AppConfig, DeviceConfig
from axis_cam.devices import AxisSpeaker
from axis_cam.exceptions import AxisConfigError
from axis_cam.mcp_server.devices import ConfigResolver, DeviceSummary, device_enum
from tests.mcp_fakes import CANARY


def _config() -> AppConfig:
    return AppConfig(
        timeout=9.0,
        devices={
            "front": DeviceConfig(
                address="192.0.2.1",
                username="admin",
                password=SecretStr(CANARY),
                groups=["outdoor"],
            ),
            "chime": DeviceConfig(
                address="192.0.2.2",
                username="admin",
                password=SecretStr(CANARY),
                type="speaker",
            ),
        },
    )


def test_names_describe_and_select() -> None:
    resolver = ConfigResolver(_config)
    assert resolver.names() == ["front", "chime"]
    assert resolver.describe("chime") == DeviceSummary(
        name="chime", device_type="speaker", groups=[], host="192.0.2.2"
    )
    assert resolver.select("all") == ["front", "chime"]
    assert resolver.select("outdoor") == ["front"]
    assert resolver.select("speaker") == ["chime"]
    assert resolver.select("nothing") == []


def test_connection_and_open_carry_the_config() -> None:
    resolver = ConfigResolver(_config)
    conn = resolver.connection("chime")
    assert (conn.host, conn.port, conn.https, conn.timeout) == ("192.0.2.2", 443, True, 9.0)
    assert CANARY not in repr(conn)
    assert isinstance(resolver.open("chime"), AxisSpeaker)


def test_summary_never_carries_credentials() -> None:
    summary = ConfigResolver(_config).describe("front").model_dump_json()
    assert CANARY not in summary and "admin" not in summary


def test_device_enum_refuses_an_empty_config() -> None:
    with pytest.raises(AxisConfigError):
        device_enum([])
    assert [m.value for m in device_enum(["a", "b"])] == ["a", "b"]
