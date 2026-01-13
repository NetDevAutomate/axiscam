"""AXIS Camera Manager - CLI tool for managing AXIS devices via VAPIX API.

This package provides a comprehensive CLI tool for interacting with AXIS cameras,
recorders, intercoms, and speakers using the VAPIX REST API.

Example:
    >>> from axis_cam import AxisCamera
    >>> async with AxisCamera("192.168.1.10", "admin", "password") as camera:
    ...     info = await camera.device_info.get_info()
    ...     print(f"Model: {info.model}")
"""

from axis_cam.client import VapixClient
from axis_cam.devices import AxisCamera, AxisDevice, AxisIntercom, AxisRecorder, AxisSpeaker

__version__ = "0.1.0"
__all__ = [
    "VapixClient",
    "AxisDevice",
    "AxisCamera",
    "AxisRecorder",
    "AxisIntercom",
    "AxisSpeaker",
]
