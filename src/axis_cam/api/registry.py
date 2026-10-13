"""Registry of API modules and the ``ResourceModule`` protocol.

``AxisDevice`` builds its API modules from this registry instead of naming each
class by hand, and generic services (report, backup, security audit) iterate the
registered *resources*: modules that can read their state into one model.

Registering is explicit (``@register`` on the class) so a module cannot appear
by accident; ``tests/test_registry.py`` asserts that every ``BaseAPI`` subclass
in ``axis_cam.api`` is registered so one cannot be forgotten either.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

from axis_cam.api.base import BaseAPI

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pydantic import BaseModel

    from axis_cam.client import VapixClient


@runtime_checkable
class ResourceModule(Protocol):
    """An API module whose state can be read into a single Pydantic model.

    Structural: a module is a resource by having these members, not by
    inheriting anything. Modules that only download or stream (logs, server
    reports) are registered modules but not resources.

    Attributes:
        name: Attribute name on ``AxisDevice`` and key in reports/backups.
        api_id: Identifier advertised in ``/config/discover/apis``, or
            ``None`` for modules that do not depend on a discoverable REST API.
    """

    name: ClassVar[str]
    api_id: ClassVar[str | None]

    async def read(self) -> BaseModel:
        """Read the module's current state from the device."""
        ...


_MODULES: dict[str, type[BaseAPI]] = {}


def register[ModuleClass: type[BaseAPI]](cls: ModuleClass) -> ModuleClass:
    """Class decorator that adds an API module to the registry.

    Args:
        cls: A ``BaseAPI`` subclass with a non-empty ``name``.

    Returns:
        The class, unchanged.

    Raises:
        TypeError: If the class has no ``name``, or the name is already taken by
            a different class.
    """
    name = cls.__dict__.get("name")
    if not isinstance(name, str) or not name:
        raise TypeError(f"{cls.__name__} must define a non-empty class attribute 'name'")
    if not name.isidentifier():
        raise TypeError(f"{cls.__name__}.name {name!r} must be a valid attribute name")
    existing = _MODULES.get(name)
    if existing is not None and existing is not cls:
        raise TypeError(
            f"module name {name!r} is already registered by {existing.__name__}; "
            f"cannot register {cls.__name__}"
        )
    _MODULES[name] = cls
    return cls


def registered_modules() -> Mapping[str, type[BaseAPI]]:
    """Return a read-only view of the registered module classes, keyed by name."""
    return MappingProxyType(_MODULES)


def build_modules(client: VapixClient) -> dict[str, BaseAPI]:
    """Instantiate every registered module against one client.

    Args:
        client: The device's VAPIX client.

    Returns:
        Module instances keyed by ``name``, in registration order.
    """
    return {name: cls(client) for name, cls in _MODULES.items()}
