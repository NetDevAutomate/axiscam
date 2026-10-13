"""Documentation must describe the code that exists.

On 2026-10-13 ``docs/api-modules.md`` documented 66 methods across 22 classes
that had never been implemented (``SshAPI.enable()``, ``CertAPI.install_certificate()``,
...). This test cross-checks every documented method against the real class.
"""

import inspect
import re
from pathlib import Path

import pytest

import axis_cam.api as api
from axis_cam.api.registry import registered_modules

DOCS = Path(__file__).resolve().parent.parent / "docs"
API_MODULES_MD = DOCS / "api-modules.md"
DEVICE_CLASSES_MD = DOCS / "device-classes.md"


def _documented_api_sections() -> dict[str, str]:
    text = API_MODULES_MD.read_text()
    parts = re.split(r"^### (\w+API)\s*$", text, flags=re.M)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}


@pytest.mark.parametrize("class_name", sorted(_documented_api_sections()))
def test_documented_api_methods_exist(class_name):
    cls = getattr(api, class_name, None)
    assert cls is not None, f"{class_name} is documented but not exported by axis_cam.api"
    real = {name for name, _ in inspect.getmembers(cls) if not name.startswith("_")}
    documented = re.findall(r"^\| `(\w+)\(", _documented_api_sections()[class_name], flags=re.M)
    phantom = [m for m in documented if m not in real]
    assert not phantom, f"{class_name} documents methods that do not exist: {phantom}"


def test_every_registered_module_has_an_api_modules_section():
    documented = set(_documented_api_sections())
    registered = {cls.__name__ for cls in registered_modules().values()}
    assert registered <= documented, registered - documented


def test_device_classes_table_lists_every_registered_module():
    text = DEVICE_CLASSES_MD.read_text()
    listed = set(re.findall(r"^\| `device\.(\w+)` \|", text, flags=re.M))
    assert set(registered_modules()) <= listed, set(registered_modules()) - listed
