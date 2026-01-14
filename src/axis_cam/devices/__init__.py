"""AXIS device type implementations.

This package contains device-specific implementations for various
AXIS product types including cameras, recorders, intercoms, and speakers.

Each device type inherits from the base AxisDevice class and may add
device-specific capabilities through API module composition.

Device Types:
    - AxisDevice: Base class for all AXIS devices
    - AxisCamera: Network cameras with video/imaging capabilities
    - AxisRecorder: S-series recorders and NVRs
    - AxisIntercom: Network intercoms and door stations
    - AxisSpeaker: Network speakers and audio devices
"""

from axis_cam.devices.base import AxisDevice
from axis_cam.devices.camera import AxisCamera
from axis_cam.devices.intercom import AxisIntercom
from axis_cam.devices.recorder import AxisRecorder
from axis_cam.devices.speaker import AxisSpeaker

__all__ = [
    "AxisCamera",
    "AxisDevice",
    "AxisIntercom",
    "AxisRecorder",
    "AxisSpeaker",
]
