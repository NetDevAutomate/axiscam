"""Tests for device classes."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from axis_cam.devices import (
    AxisCamera,
    AxisIntercom,
    AxisRecorder,
    AxisSpeaker,
)
from axis_cam.models import (
    BasicDeviceInfo,
    DeviceStatus,
    DeviceType,
    LogReport,
    LogType,
    TimeInfo,
)


class TestAxisDevice:
    """Tests for AxisDevice base class."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock VapixClient."""
        with patch("axis_cam.devices.base.VapixClient") as mock:
            client = MagicMock()
            client.host = "192.168.1.10"
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.check_connectivity = AsyncMock(return_value=True)
            client.discover_apis = AsyncMock(return_value={})
            mock.return_value = client
            yield client

    def test_camera_device_type(self):
        """Test that AxisCamera has correct device type."""
        assert AxisCamera.device_type == DeviceType.CAMERA

    def test_recorder_device_type(self):
        """Test that AxisRecorder has correct device type."""
        assert AxisRecorder.device_type == DeviceType.RECORDER

    def test_intercom_device_type(self):
        """Test that AxisIntercom has correct device type."""
        assert AxisIntercom.device_type == DeviceType.INTERCOM

    def test_speaker_device_type(self):
        """Test that AxisSpeaker has correct device type."""
        assert AxisSpeaker.device_type == DeviceType.SPEAKER

    def test_host_property(self, mock_client):
        """Test host property."""
        camera = AxisCamera("192.168.1.10", "admin", "password")
        assert camera.host == "192.168.1.10"

    def test_client_property(self, mock_client):
        """Test client property."""
        camera = AxisCamera("192.168.1.10", "admin", "password")
        assert camera.client is not None

    def test_repr(self, mock_client):
        """Test __repr__ method."""
        camera = AxisCamera("192.168.1.10", "admin", "password")
        assert "AxisCamera" in repr(camera)
        assert "192.168.1.10" in repr(camera)

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_client):
        """Test async context manager."""
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            assert camera is not None
            mock_client.__aenter__.assert_called_once()

        mock_client.__aexit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_connectivity(self, mock_client):
        """Test check_connectivity method."""
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            result = await camera.check_connectivity()
            assert result is True
            mock_client.check_connectivity.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect(self, mock_client):
        """Test connect method."""
        mock_client.connect = AsyncMock()
        camera = AxisCamera("192.168.1.10", "admin", "password")
        await camera.connect()
        mock_client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect(self, mock_client):
        """Test disconnect method."""
        mock_client.disconnect = AsyncMock()
        camera = AxisCamera("192.168.1.10", "admin", "password")
        await camera.disconnect()
        mock_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_status(self, mock_client):
        """Test get_status method."""

        # Setup responses for device info and time API calls
        def mock_get_json(path, params=None):
            if "basic-device-info" in path:
                # REST API format: data contains device info fields directly
                return {
                    "apiVersion": "1.0",
                    "data": {
                        "ProdNbr": "AXIS M3216-LVE",
                        "SerialNumber": "ACCC12345678",
                        "Version": "11.8.64",
                    },
                }
            elif "time/v2/time" in path:
                return {"data": {"dateTime": "2024-01-15T10:30:00Z"}}
            elif "time/v2/timeZone" in path:
                return {"data": {"timezone": "UTC", "source": "manual"}}
            elif "time/v2" in path:
                return {"data": {}}
            return {}

        mock_client.get_json = AsyncMock(side_effect=mock_get_json)
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            status = await camera.get_status()
            assert isinstance(status, DeviceStatus)
            assert status.host == "192.168.1.10"
            assert status.reachable is True
            assert status.device_type == DeviceType.CAMERA

    @pytest.mark.asyncio
    async def test_get_time_info(self, mock_client):
        """Test get_time_info method."""

        def mock_get_json(path, params=None):
            if "time/v2/time" in path:
                return {"data": {"dateTime": "2024-01-15T10:30:00Z"}}
            elif "time/v2/timeZone" in path:
                return {"data": {"timezone": "UTC", "source": "manual"}}
            elif "time/v2" in path:
                return {"data": {}}
            return {}

        mock_client.get_json = AsyncMock(side_effect=mock_get_json)
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            time_info = await camera.get_time_info()
            assert isinstance(time_info, TimeInfo)

    @pytest.mark.asyncio
    async def test_get_logs(self, mock_client):
        """Test get_logs method."""
        mock_client.get_text = AsyncMock(return_value="Jan 15 10:30:00 axis syslog: Test message")
        mock_client.get_raw = AsyncMock(return_value=b"Jan 15 10:30:00 axis syslog: Test message")
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            logs = await camera.get_logs(LogType.SYSTEM, max_entries=10)
            assert isinstance(logs, LogReport)

    @pytest.mark.asyncio
    async def test_get_friendly_name(self, mock_client):
        """Test get_friendly_name method."""
        mock_client.get_json = AsyncMock(
            return_value={"root": {"Properties": {"FriendlyName": "Front Door Camera"}}}
        )
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            name = await camera.get_friendly_name()
            assert name == "Front Door Camera"

    @pytest.mark.asyncio
    async def test_get_location(self, mock_client):
        """Test get_location method."""
        mock_client.get_json = AsyncMock(
            return_value={"root": {"Properties": {"Location": "Building A, Entrance"}}}
        )
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            location = await camera.get_location()
            assert location == "Building A, Entrance"


class TestAxisCamera:
    """Tests for AxisCamera class."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock VapixClient."""
        with patch("axis_cam.devices.base.VapixClient") as mock:
            client = MagicMock()
            client.host = "192.168.1.10"
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.check_connectivity = AsyncMock(return_value=True)
            client.discover_apis = AsyncMock(
                return_value={
                    "basic-device-info": {"v2": {"state": "beta"}},
                    "ptz": {"v1": {"state": "released"}},
                }
            )
            client.get_raw = AsyncMock(return_value=b"fake image data")
            client.get_json = AsyncMock(return_value={})
            mock.return_value = client
            yield client

    @pytest.fixture
    def mock_device_info(self):
        """Create mock BasicDeviceInfo."""
        return BasicDeviceInfo(
            serial_number="ACCC12345678",
            product_number="M3216-LVE",
            firmware_version="11.5.64",
        )

    @pytest.fixture
    def mock_time_info(self):
        """Create mock TimeInfo."""
        return TimeInfo(
            utc_time=datetime(2024, 1, 15, 12, 0, 0),
            timezone="Europe/Stockholm",
        )

    @pytest.mark.asyncio
    async def test_get_snapshot_url_without_resolution(self, mock_client):
        """Test get_snapshot_url without resolution."""
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            url = await camera.get_snapshot_url()
            assert url == "https://192.168.1.10/axis-cgi/jpg/image.cgi"

    @pytest.mark.asyncio
    async def test_get_snapshot_url_with_resolution(self, mock_client):
        """Test get_snapshot_url with resolution."""
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            url = await camera.get_snapshot_url(resolution="1920x1080")
            assert "resolution=1920x1080" in url

    @pytest.mark.asyncio
    async def test_get_snapshot(self, mock_client):
        """Test get_snapshot returns bytes."""
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            result = await camera.get_snapshot()
            assert result == b"fake image data"

    @pytest.mark.asyncio
    async def test_get_snapshot_with_resolution(self, mock_client):
        """Test get_snapshot with resolution parameter."""
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            await camera.get_snapshot(resolution="1280x720")
            mock_client.get_raw.assert_called_with(
                "/axis-cgi/jpg/image.cgi", {"resolution": "1280x720"}
            )

    @pytest.mark.asyncio
    async def test_get_video_stream_url_default(self, mock_client):
        """Test get_video_stream_url with defaults."""
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            url = await camera.get_video_stream_url()
            assert "rtsp://192.168.1.10" in url
            assert "videocodec=h264" in url

    @pytest.mark.asyncio
    async def test_get_video_stream_url_with_profile(self, mock_client):
        """Test get_video_stream_url with profile."""
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            url = await camera.get_video_stream_url(profile="Quality")
            assert "streamprofile=Quality" in url

    @pytest.mark.asyncio
    async def test_get_video_stream_url_with_codec(self, mock_client):
        """Test get_video_stream_url with codec."""
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            url = await camera.get_video_stream_url(codec="h265")
            assert "videocodec=h265" in url

    @pytest.mark.asyncio
    async def test_has_ptz_true(self, mock_client):
        """Test has_ptz returns True when PTZ supported."""
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            result = await camera.has_ptz()
            assert result is True

    @pytest.mark.asyncio
    async def test_has_ptz_false(self, mock_client):
        """Test has_ptz returns False when PTZ not supported."""
        mock_client.discover_apis = AsyncMock(return_value={})
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            result = await camera.has_ptz()
            assert result is False

    @pytest.mark.asyncio
    async def test_has_audio(self, mock_client):
        """Test has_audio method."""
        mock_client.discover_apis = AsyncMock(
            return_value={
                "audio-device-ctrl": {"v1": {}},
            }
        )
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            result = await camera.has_audio()
            assert result is True

    @pytest.mark.asyncio
    async def test_has_analytics(self, mock_client):
        """Test has_analytics method."""
        mock_client.discover_apis = AsyncMock(
            return_value={
                "analytics-metadata": {"v1": {}},
            }
        )
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            result = await camera.has_analytics()
            assert result is True

    @pytest.mark.asyncio
    async def test_get_video_sources(self, mock_client):
        """Test get_video_sources method."""
        mock_client.get_json = AsyncMock(
            return_value={
                "videoSources": [{"id": "1", "name": "Camera 1"}],
            }
        )
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            result = await camera.get_video_sources()
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_video_sources_error(self, mock_client):
        """Test get_video_sources handles errors."""
        mock_client.get_json = AsyncMock(side_effect=Exception("API error"))
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            result = await camera.get_video_sources()
            assert result == []

    @pytest.mark.asyncio
    async def test_get_stream_profiles(self, mock_client):
        """Test get_stream_profiles method."""
        mock_client.get_json = AsyncMock(
            return_value={
                "streamProfile": [{"name": "Quality", "description": "High quality"}],
            }
        )
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            result = await camera.get_stream_profiles()
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_stream_profiles_error(self, mock_client):
        """Test get_stream_profiles handles errors."""
        mock_client.get_json = AsyncMock(side_effect=Exception("API error"))
        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            result = await camera.get_stream_profiles()
            assert result == []


class TestAxisRecorder:
    """Tests for AxisRecorder class."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock VapixClient."""
        with patch("axis_cam.devices.base.VapixClient") as mock:
            client = MagicMock()
            client.host = "192.168.1.100"
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.check_connectivity = AsyncMock(return_value=True)
            client.discover_apis = AsyncMock(return_value={})
            client.get_json = AsyncMock(return_value={})
            mock.return_value = client
            yield client

    def test_device_type(self):
        """Test device type is RECORDER."""
        assert AxisRecorder.device_type == DeviceType.RECORDER

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_client):
        """Test async context manager."""
        async with AxisRecorder("192.168.1.100", "admin", "password") as recorder:
            assert recorder is not None

    @pytest.mark.asyncio
    async def test_get_device_specific_info(self, mock_client):
        """Test get_device_specific_info method."""
        mock_client.discover_apis = AsyncMock(
            return_value={
                "recording-group": {"v2": {}},
            }
        )
        mock_client.get_json = AsyncMock(return_value={"total": "1000GB", "free": "500GB"})

        async with AxisRecorder("192.168.1.100", "admin", "password") as recorder:
            recorder.device_info.get_info = AsyncMock(
                return_value=BasicDeviceInfo(
                    serial_number="ACCC87654321",
                    product_number="S3008",
                    firmware_version="10.12.1",
                )
            )
            result = await recorder.get_device_specific_info()

            assert result["device_type"] == "recorder"
            assert result["model"] == "S3008"
            assert result["serial_number"] == "ACCC87654321"

    @pytest.mark.asyncio
    async def test_get_recording_groups(self, mock_client):
        """Test get_recording_groups method."""
        mock_client.get_json = AsyncMock(
            return_value={
                "data": {
                    "recordingGroups": [
                        {"id": "1", "name": "Group1"},
                        {"id": "2", "name": "Group2"},
                    ]
                }
            }
        )

        async with AxisRecorder("192.168.1.100", "admin", "password") as recorder:
            result = await recorder.get_recording_groups()

            assert len(result) == 2
            assert result[0]["name"] == "Group1"

    @pytest.mark.asyncio
    async def test_get_recording_groups_error(self, mock_client):
        """Test get_recording_groups handles errors."""
        mock_client.get_json = AsyncMock(side_effect=Exception("API error"))

        async with AxisRecorder("192.168.1.100", "admin", "password") as recorder:
            result = await recorder.get_recording_groups()

            assert result == []

    @pytest.mark.asyncio
    async def test_get_recording_group(self, mock_client):
        """Test get_recording_group method."""
        mock_client.get_json = AsyncMock(
            return_value={"data": {"id": "1", "name": "Group1", "cameras": []}}
        )

        async with AxisRecorder("192.168.1.100", "admin", "password") as recorder:
            result = await recorder.get_recording_group("1")

            assert result is not None
            assert result["id"] == "1"
            assert result["name"] == "Group1"

    @pytest.mark.asyncio
    async def test_get_recording_group_not_found(self, mock_client):
        """Test get_recording_group returns None on error."""
        mock_client.get_json = AsyncMock(side_effect=Exception("Not found"))

        async with AxisRecorder("192.168.1.100", "admin", "password") as recorder:
            result = await recorder.get_recording_group("invalid")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_storage_info(self, mock_client):
        """Test get_storage_info method."""
        mock_client.get_json = AsyncMock(
            return_value={
                "total": "1000GB",
                "free": "500GB",
                "used": "500GB",
            }
        )

        async with AxisRecorder("192.168.1.100", "admin", "password") as recorder:
            result = await recorder.get_storage_info()

            assert result["total"] == "1000GB"
            assert result["free"] == "500GB"

    @pytest.mark.asyncio
    async def test_get_storage_info_error(self, mock_client):
        """Test get_storage_info handles errors."""
        mock_client.get_json = AsyncMock(side_effect=Exception("API error"))

        async with AxisRecorder("192.168.1.100", "admin", "password") as recorder:
            result = await recorder.get_storage_info()

            assert result == {}

    @pytest.mark.asyncio
    async def test_get_disk_status(self, mock_client):
        """Test get_disk_status method."""
        mock_client.get_json = AsyncMock(
            return_value={
                "disks": [
                    {"id": "disk1", "status": "healthy", "size": "500GB"},
                    {"id": "disk2", "status": "healthy", "size": "500GB"},
                ]
            }
        )

        async with AxisRecorder("192.168.1.100", "admin", "password") as recorder:
            result = await recorder.get_disk_status()

            assert len(result) == 2
            assert result[0]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_get_disk_status_error(self, mock_client):
        """Test get_disk_status handles errors."""
        mock_client.get_json = AsyncMock(side_effect=Exception("API error"))

        async with AxisRecorder("192.168.1.100", "admin", "password") as recorder:
            result = await recorder.get_disk_status()

            assert result == []

    @pytest.mark.asyncio
    async def test_get_remote_storage_config(self, mock_client):
        """Test get_remote_storage_config method."""
        mock_client.get_json = AsyncMock(
            return_value={"data": {"enabled": True, "endpoint": "s3://bucket"}}
        )

        async with AxisRecorder("192.168.1.100", "admin", "password") as recorder:
            result = await recorder.get_remote_storage_config()

            assert result is not None
            assert result["enabled"] is True
            assert result["endpoint"] == "s3://bucket"

    @pytest.mark.asyncio
    async def test_get_remote_storage_config_not_available(self, mock_client):
        """Test get_remote_storage_config returns None on error."""
        mock_client.get_json = AsyncMock(side_effect=Exception("Not available"))

        async with AxisRecorder("192.168.1.100", "admin", "password") as recorder:
            result = await recorder.get_remote_storage_config()

            assert result is None

    @pytest.mark.asyncio
    async def test_get_connected_cameras(self, mock_client):
        """Test get_connected_cameras method."""
        mock_client.get_json = AsyncMock(
            return_value={
                "root": {
                    "Network": {
                        "AxisDevices": [
                            {"ip": "192.168.1.10", "model": "M3216-LVE"},
                            {"ip": "192.168.1.11", "model": "P1448-LE"},
                        ]
                    }
                }
            }
        )

        async with AxisRecorder("192.168.1.100", "admin", "password") as recorder:
            result = await recorder.get_connected_cameras()

            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_connected_cameras_error(self, mock_client):
        """Test get_connected_cameras handles errors."""
        mock_client.get_json = AsyncMock(side_effect=Exception("API error"))

        async with AxisRecorder("192.168.1.100", "admin", "password") as recorder:
            result = await recorder.get_connected_cameras()

            assert result == []

    @pytest.mark.asyncio
    async def test_has_remote_storage_true(self, mock_client):
        """Test has_remote_storage returns True when supported."""
        mock_client.discover_apis = AsyncMock(
            return_value={
                "remote-object-storage": {"v1": {}},
            }
        )

        async with AxisRecorder("192.168.1.100", "admin", "password") as recorder:
            result = await recorder.has_remote_storage()

            assert result is True

    @pytest.mark.asyncio
    async def test_has_remote_storage_false(self, mock_client):
        """Test has_remote_storage returns False when not supported."""
        mock_client.discover_apis = AsyncMock(return_value={})

        async with AxisRecorder("192.168.1.100", "admin", "password") as recorder:
            result = await recorder.has_remote_storage()

            assert result is False


class TestAxisIntercom:
    """Tests for AxisIntercom class."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock VapixClient."""
        with patch("axis_cam.devices.base.VapixClient") as mock:
            client = MagicMock()
            client.host = "192.168.1.11"
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.check_connectivity = AsyncMock(return_value=True)
            client.discover_apis = AsyncMock(return_value={})
            client.get_json = AsyncMock(return_value={})
            client.get_raw = AsyncMock(return_value=b"fake image data")
            mock.return_value = client
            yield client

    def test_device_type(self):
        """Test device type is INTERCOM."""
        assert AxisIntercom.device_type == DeviceType.INTERCOM

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_client):
        """Test async context manager."""
        async with AxisIntercom("192.168.1.11", "admin", "password") as intercom:
            assert intercom is not None

    @pytest.mark.asyncio
    async def test_get_device_specific_info(self, mock_client):
        """Test get_device_specific_info method."""
        mock_client.discover_apis = AsyncMock(
            return_value={
                "video-analytics": {"v1": {}},
                "audio-device-ctrl": {"v1": {}},
            }
        )

        async with AxisIntercom("192.168.1.11", "admin", "password") as intercom:
            intercom.device_info.get_info = AsyncMock(
                return_value=BasicDeviceInfo(
                    serial_number="ACCC11111111",
                    product_number="I8016-LVE",
                    firmware_version="10.11.0",
                )
            )
            result = await intercom.get_device_specific_info()

            assert result["device_type"] == "intercom"
            assert result["model"] == "I8016-LVE"
            assert result["video_supported"] is True
            assert result["audio_supported"] is True

    @pytest.mark.asyncio
    async def test_get_audio_status(self, mock_client):
        """Test get_audio_status method."""
        mock_client.get_json = AsyncMock(
            return_value={
                "status": "active",
                "channels": 2,
            }
        )

        async with AxisIntercom("192.168.1.11", "admin", "password") as intercom:
            result = await intercom.get_audio_status()

            assert result["status"] == "active"
            assert result["channels"] == 2

    @pytest.mark.asyncio
    async def test_get_audio_status_error(self, mock_client):
        """Test get_audio_status handles errors."""
        mock_client.get_json = AsyncMock(side_effect=Exception("API error"))

        async with AxisIntercom("192.168.1.11", "admin", "password") as intercom:
            result = await intercom.get_audio_status()

            assert result == {}

    @pytest.mark.asyncio
    async def test_get_audio_device_info(self, mock_client):
        """Test get_audio_device_info method."""
        mock_client.get_json = AsyncMock(
            return_value={
                "devices": [{"id": "1", "type": "speaker"}],
            }
        )

        async with AxisIntercom("192.168.1.11", "admin", "password") as intercom:
            result = await intercom.get_audio_device_info()

            assert "devices" in result

    @pytest.mark.asyncio
    async def test_get_audio_device_info_error(self, mock_client):
        """Test get_audio_device_info handles errors."""
        mock_client.get_json = AsyncMock(side_effect=Exception("API error"))

        async with AxisIntercom("192.168.1.11", "admin", "password") as intercom:
            result = await intercom.get_audio_device_info()

            assert result == {}

    @pytest.mark.asyncio
    async def test_get_audio_multicast_config(self, mock_client):
        """Test get_audio_multicast_config method returns AudioMulticastConfig."""
        from axis_cam.models import AudioMulticastConfig

        async with AxisIntercom("192.168.1.11", "admin", "password") as intercom:
            result = await intercom.get_audio_multicast_config()

            # Returns AudioMulticastConfig model
            assert isinstance(result, AudioMulticastConfig)

    @pytest.mark.asyncio
    async def test_get_sip_config(self, mock_client):
        """Test get_sip_config method."""
        mock_client.get_json = AsyncMock(
            return_value={
                "root": {
                    "SIP": {
                        "Enabled": "yes",
                        "Server": "sip.example.com",
                    }
                }
            }
        )

        async with AxisIntercom("192.168.1.11", "admin", "password") as intercom:
            result = await intercom.get_sip_config()

            assert result["Enabled"] == "yes"
            assert result["Server"] == "sip.example.com"

    @pytest.mark.asyncio
    async def test_get_sip_config_error(self, mock_client):
        """Test get_sip_config handles errors."""
        mock_client.get_json = AsyncMock(side_effect=Exception("API error"))

        async with AxisIntercom("192.168.1.11", "admin", "password") as intercom:
            result = await intercom.get_sip_config()

            assert result == {}

    @pytest.mark.asyncio
    async def test_has_video_true(self, mock_client):
        """Test has_video returns True when video supported."""
        mock_client.discover_apis = AsyncMock(
            return_value={
                "video-analytics": {"v1": {}},
            }
        )

        async with AxisIntercom("192.168.1.11", "admin", "password") as intercom:
            result = await intercom.has_video()

            assert result is True

    @pytest.mark.asyncio
    async def test_has_video_false(self, mock_client):
        """Test has_video returns False when video not supported."""
        mock_client.discover_apis = AsyncMock(return_value={})

        async with AxisIntercom("192.168.1.11", "admin", "password") as intercom:
            result = await intercom.has_video()

            assert result is False

    @pytest.mark.asyncio
    async def test_has_sip_true(self, mock_client):
        """Test has_sip returns True when SIP configured."""
        mock_client.get_json = AsyncMock(return_value={"root": {"SIP": {"Enabled": "yes"}}})

        async with AxisIntercom("192.168.1.11", "admin", "password") as intercom:
            result = await intercom.has_sip()

            assert result is True

    @pytest.mark.asyncio
    async def test_has_sip_false(self, mock_client):
        """Test has_sip returns False when SIP not configured."""
        mock_client.get_json = AsyncMock(side_effect=Exception("Not available"))

        async with AxisIntercom("192.168.1.11", "admin", "password") as intercom:
            result = await intercom.has_sip()

            assert result is False

    @pytest.mark.asyncio
    async def test_get_snapshot_url_without_resolution(self, mock_client):
        """Test get_snapshot_url without resolution."""
        async with AxisIntercom("192.168.1.11", "admin", "password") as intercom:
            url = await intercom.get_snapshot_url()

            assert url == "https://192.168.1.11/axis-cgi/jpg/image.cgi"

    @pytest.mark.asyncio
    async def test_get_snapshot_url_with_resolution(self, mock_client):
        """Test get_snapshot_url with resolution."""
        async with AxisIntercom("192.168.1.11", "admin", "password") as intercom:
            url = await intercom.get_snapshot_url(resolution="1280x720")

            assert "resolution=1280x720" in url

    @pytest.mark.asyncio
    async def test_get_snapshot(self, mock_client):
        """Test get_snapshot returns bytes."""
        async with AxisIntercom("192.168.1.11", "admin", "password") as intercom:
            result = await intercom.get_snapshot()

            assert result == b"fake image data"

    @pytest.mark.asyncio
    async def test_get_snapshot_with_resolution(self, mock_client):
        """Test get_snapshot with resolution parameter."""
        async with AxisIntercom("192.168.1.11", "admin", "password") as intercom:
            await intercom.get_snapshot(resolution="1920x1080")

            mock_client.get_raw.assert_called_with(
                "/axis-cgi/jpg/image.cgi", {"resolution": "1920x1080"}
            )


class TestAxisSpeaker:
    """Tests for AxisSpeaker class."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock VapixClient."""
        with patch("axis_cam.devices.base.VapixClient") as mock:
            client = MagicMock()
            client.host = "192.168.125.45"
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.check_connectivity = AsyncMock(return_value=True)
            client.discover_apis = AsyncMock(return_value={})
            client.get_json = AsyncMock(return_value={})
            mock.return_value = client
            yield client

    def test_device_type(self):
        """Test device type is SPEAKER."""
        assert AxisSpeaker.device_type == DeviceType.SPEAKER

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_client):
        """Test async context manager."""
        async with AxisSpeaker("192.168.125.45", "admin", "password") as speaker:
            assert speaker is not None

    @pytest.mark.asyncio
    async def test_get_device_specific_info(self, mock_client):
        """Test get_device_specific_info method."""
        mock_client.discover_apis = AsyncMock(
            return_value={
                "audio-multicast-ctrl": {"v1beta": {}},
            }
        )

        async with AxisSpeaker("192.168.125.45", "admin", "password") as speaker:
            speaker.device_info.get_info = AsyncMock(
                return_value=BasicDeviceInfo(
                    serial_number="ACCC22222222",
                    product_number="C1410",
                    firmware_version="10.12.5",
                )
            )
            result = await speaker.get_device_specific_info()

            assert result["device_type"] == "speaker"
            assert result["model"] == "C1410"
            assert result["audio_multicast_supported"] is True

    @pytest.mark.asyncio
    async def test_get_audio_config(self, mock_client):
        """Test get_audio_config method."""
        mock_client.get_json = AsyncMock(
            return_value={
                "root": {
                    "Audio": {
                        "OutputGain": "75",
                        "InputGain": "50",
                    }
                }
            }
        )

        async with AxisSpeaker("192.168.125.45", "admin", "password") as speaker:
            result = await speaker.get_audio_config()

            assert result["OutputGain"] == "75"
            assert result["InputGain"] == "50"

    @pytest.mark.asyncio
    async def test_get_audio_config_error(self, mock_client):
        """Test get_audio_config handles errors."""
        mock_client.get_json = AsyncMock(side_effect=Exception("API error"))

        async with AxisSpeaker("192.168.125.45", "admin", "password") as speaker:
            result = await speaker.get_audio_config()

            assert result == {}

    @pytest.mark.asyncio
    async def test_get_audio_multicast_config(self, mock_client):
        """Test get_audio_multicast_config method returns AudioMulticastConfig."""
        from axis_cam.models import AudioMulticastConfig

        async with AxisSpeaker("192.168.125.45", "admin", "password") as speaker:
            result = await speaker.get_audio_multicast_config()

            # Returns AudioMulticastConfig model
            assert isinstance(result, AudioMulticastConfig)

    @pytest.mark.asyncio
    async def test_get_audio_multicast_config_error(self, mock_client):
        """Test get_audio_multicast_config returns default on error."""
        from axis_cam.models import AudioMulticastConfig

        mock_client.get_json = AsyncMock(side_effect=Exception("API error"))

        async with AxisSpeaker("192.168.125.45", "admin", "password") as speaker:
            result = await speaker.get_audio_multicast_config()

            # Returns default AudioMulticastConfig on error
            assert isinstance(result, AudioMulticastConfig)

    @pytest.mark.asyncio
    async def test_get_audio_status(self, mock_client):
        """Test get_audio_status method."""
        mock_client.get_json = AsyncMock(
            return_value={
                "status": "playing",
                "volume": 80,
            }
        )

        async with AxisSpeaker("192.168.125.45", "admin", "password") as speaker:
            result = await speaker.get_audio_status()

            assert result["status"] == "playing"
            assert result["volume"] == 80

    @pytest.mark.asyncio
    async def test_get_audio_status_error(self, mock_client):
        """Test get_audio_status handles errors."""
        mock_client.get_json = AsyncMock(side_effect=Exception("API error"))

        async with AxisSpeaker("192.168.125.45", "admin", "password") as speaker:
            result = await speaker.get_audio_status()

            assert result == {}

    @pytest.mark.asyncio
    async def test_get_audio_device_info(self, mock_client):
        """Test get_audio_device_info method."""
        mock_client.get_json = AsyncMock(
            return_value={
                "audioDevices": [{"type": "speaker", "channels": 1}],
            }
        )

        async with AxisSpeaker("192.168.125.45", "admin", "password") as speaker:
            result = await speaker.get_audio_device_info()

            assert "audioDevices" in result

    @pytest.mark.asyncio
    async def test_get_audio_device_info_error(self, mock_client):
        """Test get_audio_device_info handles errors."""
        mock_client.get_json = AsyncMock(side_effect=Exception("API error"))

        async with AxisSpeaker("192.168.125.45", "admin", "password") as speaker:
            result = await speaker.get_audio_device_info()

            assert result == {}

    @pytest.mark.asyncio
    async def test_get_volume(self, mock_client):
        """Test get_volume method returns volume level."""
        mock_client.get_json = AsyncMock(return_value={"root": {"Audio": {"OutputGain": "75"}}})

        async with AxisSpeaker("192.168.125.45", "admin", "password") as speaker:
            result = await speaker.get_volume()

            assert result == 75

    @pytest.mark.asyncio
    async def test_get_volume_not_available(self, mock_client):
        """Test get_volume returns None when not available."""
        mock_client.get_json = AsyncMock(return_value={"root": {"Audio": {}}})

        async with AxisSpeaker("192.168.125.45", "admin", "password") as speaker:
            result = await speaker.get_volume()

            assert result is None

    @pytest.mark.asyncio
    async def test_get_volume_invalid_value(self, mock_client):
        """Test get_volume handles invalid value."""
        mock_client.get_json = AsyncMock(
            return_value={"root": {"Audio": {"OutputGain": "invalid"}}}
        )

        async with AxisSpeaker("192.168.125.45", "admin", "password") as speaker:
            result = await speaker.get_volume()

            assert result is None

    @pytest.mark.asyncio
    async def test_has_multicast_true(self, mock_client):
        """Test has_multicast returns True when supported."""
        mock_client.discover_apis = AsyncMock(
            return_value={
                "audio-multicast-ctrl": {"v1beta": {}},
            }
        )

        async with AxisSpeaker("192.168.125.45", "admin", "password") as speaker:
            result = await speaker.has_multicast()

            assert result is True

    @pytest.mark.asyncio
    async def test_has_multicast_false(self, mock_client):
        """Test has_multicast returns False when not supported."""
        mock_client.discover_apis = AsyncMock(return_value={})

        async with AxisSpeaker("192.168.125.45", "admin", "password") as speaker:
            result = await speaker.has_multicast()

            assert result is False

    @pytest.mark.asyncio
    async def test_get_audio_clips(self, mock_client):
        """Test get_audio_clips method."""
        mock_client.get_json = AsyncMock(
            return_value={
                "clips": [
                    {"id": "1", "name": "doorbell.wav"},
                    {"id": "2", "name": "alarm.wav"},
                ]
            }
        )

        async with AxisSpeaker("192.168.125.45", "admin", "password") as speaker:
            result = await speaker.get_audio_clips()

            assert len(result) == 2
            assert result[0]["name"] == "doorbell.wav"

    @pytest.mark.asyncio
    async def test_get_audio_clips_error(self, mock_client):
        """Test get_audio_clips handles errors."""
        mock_client.get_json = AsyncMock(side_effect=Exception("API error"))

        async with AxisSpeaker("192.168.125.45", "admin", "password") as speaker:
            result = await speaker.get_audio_clips()

            assert result == []


class TestDeviceInfo:
    """Tests for get_info and related methods."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock VapixClient."""
        with patch("axis_cam.devices.base.VapixClient") as mock:
            client = MagicMock()
            client.host = "192.168.1.10"
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            mock.return_value = client
            yield client

    @pytest.mark.asyncio
    async def test_get_info_caches_result(self, mock_client):
        """Test that get_info caches the result."""
        mock_info = BasicDeviceInfo(serial_number="TEST123")

        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            camera.device_info.get_info = AsyncMock(return_value=mock_info)

            # First call
            result1 = await camera.get_info()
            # Second call should use cache
            result2 = await camera.get_info()

            assert result1 == result2
            assert camera.device_info.get_info.call_count == 1


class TestDeviceCapabilities:
    """Tests for get_capabilities method."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock VapixClient."""
        with patch("axis_cam.devices.base.VapixClient") as mock:
            client = MagicMock()
            client.host = "192.168.1.10"
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            mock.return_value = client
            yield client

    @pytest.mark.asyncio
    async def test_get_capabilities_discovers_apis(self, mock_client):
        """Test that get_capabilities calls discover_apis."""
        mock_client.discover_apis = AsyncMock(
            return_value={
                "ptz": {"v1": {}},
                "audio-device-ctrl": {"v1": {}},
            }
        )

        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            caps = await camera.get_capabilities()

            assert caps.has_ptz is True
            assert caps.has_audio is True
            mock_client.discover_apis.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_capabilities_caches_result(self, mock_client):
        """Test that get_capabilities caches the result."""
        mock_client.discover_apis = AsyncMock(return_value={})

        async with AxisCamera("192.168.1.10", "admin", "password") as camera:
            await camera.get_capabilities()
            await camera.get_capabilities()

            # Should only be called once due to caching
            assert mock_client.discover_apis.call_count == 1
