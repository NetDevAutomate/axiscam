"""AXIS VAPIX API modules.

This package contains modular API implementations for the various
AXIS VAPIX REST APIs. Each module encapsulates a specific API domain.

API Modules:
    - device_info: Basic device information retrieval
    - param: Parameter reading and management
    - time: Time and timezone configuration
    - network: Network settings (extended)
    - logs: Log retrieval and server reports
    - lldp: LLDP neighbor discovery
    - firewall: Firewall configuration
    - ssh: SSH configuration
    - snmp: SNMP configuration
    - cert: Certificate management
    - ntp: NTP configuration
    - action: Action rules configuration
    - mqtt: MQTT event bridge configuration
    - recording: Recording group configuration
    - storage: Remote object storage configuration
    - geolocation: Device geolocation configuration
    - analytics: Video analytics configuration
    - snapshot: Best snapshot configuration
    - analytics_mqtt: Analytics MQTT publishing
    - audio_multicast: Audio multicast control
    - serverreport: Server report and debug archive downloads
    - oidc: OpenID Connect (OIDC) setup
    - oauth: OAuth 2.0 Client Credentials Grant
    - virtualhost: Virtual host configuration
    - crypto_policy: Cryptographic policy settings
    - networkpairing: Network pairing
    - stream: Stream diagnostics (RTSP, RTP, profiles)
"""

from axis_cam.api.action import ActionAPI
from axis_cam.api.analytics import VideoAnalyticsAPI
from axis_cam.api.analytics_mqtt import AnalyticsMqttAPI
from axis_cam.api.audio_multicast import AudioMulticastAPI
from axis_cam.api.cert import CertAPI
from axis_cam.api.crypto_policy import CryptoPolicyAPI
from axis_cam.api.device_info import BasicDeviceInfoAPI
from axis_cam.api.firewall import FirewallAPI
from axis_cam.api.geolocation import GeolocationAPI
from axis_cam.api.lldp import LldpAPI
from axis_cam.api.logs import LogsAPI
from axis_cam.api.mqtt import MqttBridgeAPI
from axis_cam.api.network import NetworkSettingsAPI
from axis_cam.api.networkpairing import NetworkPairingAPI
from axis_cam.api.ntp import NtpAPI
from axis_cam.api.oauth import OAuthAPI
from axis_cam.api.oidc import OidcAPI
from axis_cam.api.param import ParamAPI
from axis_cam.api.recording import RecordingAPI
from axis_cam.api.serverreport import ServerReportAPI
from axis_cam.api.snapshot import BestSnapshotAPI
from axis_cam.api.snmp import SnmpAPI
from axis_cam.api.ssh import SshAPI
from axis_cam.api.storage import RemoteStorageAPI
from axis_cam.api.stream import StreamAPI
from axis_cam.api.time import TimeAPI
from axis_cam.api.virtualhost import VirtualHostAPI

__all__ = [
    "ActionAPI",
    "AnalyticsMqttAPI",
    "AudioMulticastAPI",
    "BasicDeviceInfoAPI",
    "BestSnapshotAPI",
    "CertAPI",
    "CryptoPolicyAPI",
    "FirewallAPI",
    "GeolocationAPI",
    "LldpAPI",
    "LogsAPI",
    "MqttBridgeAPI",
    "NetworkPairingAPI",
    "NetworkSettingsAPI",
    "NtpAPI",
    "OAuthAPI",
    "OidcAPI",
    "ParamAPI",
    "RecordingAPI",
    "RemoteStorageAPI",
    "ServerReportAPI",
    "SnmpAPI",
    "SshAPI",
    "StreamAPI",
    "TimeAPI",
    "VideoAnalyticsAPI",
    "VirtualHostAPI",
]
