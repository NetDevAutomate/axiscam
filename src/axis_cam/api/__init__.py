"""AXIS VAPIX API modules.

This package contains modular API implementations for the various
AXIS VAPIX REST APIs. Each module encapsulates a specific API domain.

API Modules:
    - device_info: Basic device information retrieval
    - param: Parameter reading and management
    - time: Time and timezone configuration
    - network: Network settings
    - logs: Log retrieval and server reports
    - lldp: LLDP neighbor discovery
"""

from axis_cam.api.device_info import BasicDeviceInfoAPI
from axis_cam.api.lldp import LldpAPI
from axis_cam.api.logs import LogsAPI
from axis_cam.api.param import ParamAPI
from axis_cam.api.time import TimeAPI

__all__ = [
    "BasicDeviceInfoAPI",
    "LldpAPI",
    "LogsAPI",
    "ParamAPI",
    "TimeAPI",
]
