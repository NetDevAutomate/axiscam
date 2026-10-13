"""Tests for the API module registry and registry-built devices."""

import importlib
import inspect
import json
import pkgutil
import typing
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import axis_cam.api as api_pkg
from axis_cam.api.base import BaseAPI
from axis_cam.api.logs import LogsAPI
from axis_cam.api.registry import ResourceModule, build_modules, register, registered_modules
from axis_cam.api.ssh import SshAPI
from axis_cam.devices.base import AxisDevice
from axis_cam.devices.camera import AxisCamera

SPECS_DIR = Path(__file__).resolve().parent.parent / "src" / "specs"
EXPECTED_MODULE_COUNT = 27
NON_RESOURCES = {"params", "logs", "serverreport"}


def _api_module_classes() -> set[type[BaseAPI]]:
    """Every BaseAPI subclass defined in a module of the axis_cam.api package."""
    found: set[type[BaseAPI]] = set()
    for info in pkgutil.iter_modules(api_pkg.__path__):
        module = importlib.import_module(f"{api_pkg.__name__}.{info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BaseAPI)
                and obj is not BaseAPI
                and obj.__module__ == module.__name__
            ):
                found.add(obj)
    return found


def _discovery(spec_name: str) -> dict:
    return json.loads((SPECS_DIR / f"{spec_name}.json").read_text())


@pytest.fixture
def mock_client():
    """Patch VapixClient so devices can be built without a network."""
    with patch("axis_cam.devices.base.VapixClient") as mock:
        instance = MagicMock()
        instance.host = "192.168.1.10"
        mock.return_value = instance
        yield instance


class TestRegistryContents:
    """What is registered, and that nothing is forgotten or duplicated."""

    def test_every_api_module_class_is_registered(self):
        registered = set(registered_modules().values())
        defined = _api_module_classes()
        assert defined == registered, {
            "unregistered": {c.__name__ for c in defined - registered},
            "unknown": {c.__name__ for c in registered - defined},
        }
        assert len(registered) == EXPECTED_MODULE_COUNT

    def test_names_match_the_class_attribute_and_are_identifiers(self):
        for name, cls in registered_modules().items():
            assert cls.name == name
            assert name.isidentifier()
            assert "api_id" in cls.__dict__, f"{cls.__name__} must declare api_id explicitly"

    def test_axis_device_declares_exactly_the_registered_modules(self):
        hints = typing.get_type_hints(AxisDevice)
        declared = {
            attr: cls
            for attr, cls in hints.items()
            if inspect.isclass(cls) and issubclass(cls, BaseAPI)
        }
        assert declared == dict(registered_modules())

    def test_registered_names_do_not_shadow_device_members(self):
        reserved = {attr for attr in dir(AxisDevice) if not attr.startswith("_")} - set(
            registered_modules()
        )
        assert not (set(registered_modules()) & reserved)
        assert "modules" not in registered_modules()
        assert "resources" not in registered_modules()

    def test_api_ids_are_ids_a_real_device_advertises(self):
        advertised: set[str] = set()
        for spec in SPECS_DIR.glob("*.json"):
            advertised |= set(json.loads(spec.read_text()))
        assert advertised, "no device captures found in src/specs"
        declared = {cls.api_id for cls in registered_modules().values() if cls.api_id is not None}
        assert declared <= advertised, declared - advertised

    def test_cgi_capable_modules_are_not_gated(self):
        # These work on firmware whose discovery omits the REST id (c1410 lists
        # neither `time` nor `param`), so they must never be filtered out.
        modules = registered_modules()
        for name in ("device_info", "time", "params", "logs", "serverreport"):
            assert modules[name].api_id is None, name


class TestRegisterDecorator:
    """Error handling of @register; none of these cases mutate the registry."""

    def test_reregistering_the_same_class_is_idempotent(self):
        before = dict(registered_modules())
        assert register(SshAPI) is SshAPI
        assert dict(registered_modules()) == before

    def test_duplicate_name_with_a_different_class_is_rejected(self):
        class Impostor(BaseAPI):
            name = "ssh"
            api_id = None

        with pytest.raises(TypeError, match="already registered by SshAPI"):
            register(Impostor)
        assert registered_modules()["ssh"] is SshAPI

    def test_missing_name_is_rejected(self):
        class Anonymous(BaseAPI):
            api_id = None

        with pytest.raises(TypeError, match="non-empty class attribute 'name'"):
            register(Anonymous)

    def test_inherited_name_is_not_enough(self):
        # A subclass must declare its own name, or it would silently clash.
        class SshSubclass(SshAPI):
            pass

        with pytest.raises(TypeError, match="non-empty class attribute 'name'"):
            register(SshSubclass)

    def test_non_identifier_name_is_rejected(self):
        class Dashed(BaseAPI):
            name = "crypto-policy"
            api_id = None

        with pytest.raises(TypeError, match="valid attribute name"):
            register(Dashed)


class TestBuildModules:
    def test_builds_one_instance_per_registered_module_on_the_client(self):
        client = MagicMock()
        client.host = "cam.example"
        modules = build_modules(client)
        assert set(modules) == set(registered_modules())
        assert all(m._client is client for m in modules.values())

    def test_logs_module_takes_device_name_from_client(self):
        client = MagicMock()
        client.host = "cam.example"
        logs = build_modules(client)["logs"]
        assert isinstance(logs, LogsAPI)
        assert logs._device_name == "cam.example"


class TestDeviceModules:
    """AxisDevice exposes the registry-built modules under their names."""

    def test_modules_are_attributes(self, mock_client):
        device = AxisCamera("192.168.1.10", "admin", "pass")
        for name, module in device.modules.items():
            assert getattr(device, name) is module
            assert isinstance(module, registered_modules()[name])

    def test_resources_are_exactly_the_modules_with_read(self, mock_client):
        device = AxisCamera("192.168.1.10", "admin", "pass")
        assert set(device.resources) == set(registered_modules()) - NON_RESOURCES
        for module in device.resources.values():
            assert isinstance(module, ResourceModule)
        for name in NON_RESOURCES:
            assert not isinstance(device.modules[name], ResourceModule)

    async def test_available_resources_filters_by_discovered_api_ids(self, mock_client):
        device = AxisCamera("192.168.1.10", "admin", "pass")
        mock_client.discover_apis = AsyncMock(return_value=_discovery("c1410"))

        available = await device.available_resources()

        # Advertised REST APIs are kept, unadvertised ones are dropped.
        assert {"ssh", "firewall", "snmp", "cert", "lldp", "virtualhost"} <= set(available)
        assert {"ntp", "network", "stream", "crypto_policy", "geolocation"}.isdisjoint(available)
        # CGI-capable modules are never gated.
        assert {"device_info", "time"} <= set(available)

    async def test_available_resources_when_discovery_is_empty_keeps_everything(self, mock_client):
        device = AxisCamera("192.168.1.10", "admin", "pass")
        mock_client.discover_apis = AsyncMock(return_value={})

        available = await device.available_resources()

        assert available == device.resources

    @pytest.mark.parametrize("spec", ["m3216-lve", "i8016-lve", "s3008", "c1410"])
    async def test_available_resources_against_each_capture(self, mock_client, spec):
        device = AxisCamera("192.168.1.10", "admin", "pass")
        advertised = _discovery(spec)
        mock_client.discover_apis = AsyncMock(return_value=advertised)

        available = await device.available_resources()

        for name, module in device.resources.items():
            expected = module.api_id is None or module.api_id in advertised
            assert (name in available) == expected, (spec, name, module.api_id)
