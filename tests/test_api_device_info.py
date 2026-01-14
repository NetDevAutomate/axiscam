"""Tests for BasicDeviceInfo API module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from axis_cam.api.device_info import BasicDeviceInfoAPI
from axis_cam.models import BasicDeviceInfo, DeviceProperties


class TestBasicDeviceInfoAPI:
    """Tests for BasicDeviceInfoAPI class."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock VapixClient."""
        client = MagicMock()
        client.host = "192.168.1.10"
        return client

    @pytest.fixture
    def device_info_api(self, mock_client):
        """Create BasicDeviceInfoAPI instance with mock client."""
        return BasicDeviceInfoAPI(mock_client)

    def test_init(self, device_info_api):
        """Test BasicDeviceInfoAPI initialization."""
        assert device_info_api._client is not None

    @pytest.mark.asyncio
    async def test_get_info_rest_api_success(self, device_info_api):
        """Test get_info using REST API."""
        rest_response = {
            "data": {
                "SerialNumber": "ACCC12345678",
                "ProdNbr": "M3216-LVE",
                "Version": "11.5.64",
                "Brand": "AXIS",
            }
        }
        device_info_api._get = AsyncMock(return_value=rest_response)

        result = await device_info_api.get_info()

        assert result.serial_number == "ACCC12345678"
        assert result.product_number == "M3216-LVE"
        assert result.firmware_version == "11.5.64"

    @pytest.mark.asyncio
    async def test_get_info_rest_api_fallback_to_cgi(self, device_info_api):
        """Test get_info falls back to CGI when REST fails."""
        cgi_response = {
            "apiVersion": "1.3",
            "data": {
                "propertyList": {
                    "SerialNumber": "ACCC12345678",
                    "ProdNbr": "M3216-LVE",
                    "Version": "11.5.64",
                }
            },
        }

        async def mock_get(path, params=None):
            raise Exception("REST API not available")

        device_info_api._get = mock_get
        device_info_api._post = AsyncMock(return_value=cgi_response)

        result = await device_info_api.get_info()

        assert result.serial_number == "ACCC12345678"

    @pytest.mark.asyncio
    async def test_get_rest_info(self, device_info_api):
        """Test _get_rest_info method."""
        response = {"data": {"serialNumber": "TEST123"}}
        device_info_api._get = AsyncMock(return_value=response)

        result = await device_info_api._get_rest_info()

        assert result == {"serialNumber": "TEST123"}

    @pytest.mark.asyncio
    async def test_get_cgi_info(self, device_info_api):
        """Test _get_cgi_info method."""
        response = {
            "apiVersion": "1.3",
            "data": {
                "propertyList": {
                    "serialNumber": "TEST123",
                }
            },
        }
        device_info_api._post = AsyncMock(return_value=response)

        result = await device_info_api._get_cgi_info()

        assert result == {"serialNumber": "TEST123"}

    def test_normalize_cgi_response(self, device_info_api):
        """Test _normalize_cgi_response method with new format."""
        response = {
            "apiVersion": "1.3",
            "data": {
                "propertyList": {
                    "SerialNumber": "ACCC12345678",
                    "ProdNbr": "M3216-LVE",
                }
            },
        }

        result = device_info_api._normalize_cgi_response(response)

        assert result["SerialNumber"] == "ACCC12345678"
        assert result["ProdNbr"] == "M3216-LVE"

    def test_normalize_cgi_response_legacy_format(self, device_info_api):
        """Test _normalize_cgi_response method with legacy format."""
        response = {
            "propertyList": {
                "properties": [
                    {"name": "SerialNumber", "value": "ACCC12345678"},
                    {"name": "ProdNbr", "value": "M3216-LVE"},
                    {"name": "", "value": "empty name"},
                    {"name": "emptyValue", "value": ""},
                ]
            }
        }

        result = device_info_api._normalize_cgi_response(response)

        assert result["SerialNumber"] == "ACCC12345678"
        assert result["ProdNbr"] == "M3216-LVE"
        assert "" not in result  # Empty name skipped
        assert "emptyValue" not in result  # Empty value skipped

    def test_normalize_cgi_response_empty(self, device_info_api):
        """Test _normalize_cgi_response with empty response."""
        result = device_info_api._normalize_cgi_response({})
        assert result == {}

    def test_parse_rest_response(self, device_info_api):
        """Test _parse_rest_response method."""
        data = {
            "SerialNumber": "ACCC12345678",
            "ProdNbr": "M3216-LVE",
            "Version": "11.5.64",
        }

        result = device_info_api._parse_rest_response(data)

        assert isinstance(result, BasicDeviceInfo)
        assert result.serial_number == "ACCC12345678"

    def test_parse_cgi_response(self, device_info_api):
        """Test _parse_cgi_response method."""
        data = {
            "SerialNumber": "ACCC12345678",
            "ProdNbr": "M3216-LVE",
        }

        result = device_info_api._parse_cgi_response(data)

        assert isinstance(result, BasicDeviceInfo)
        assert result.serial_number == "ACCC12345678"

    @pytest.mark.asyncio
    async def test_get_property_existing(self, device_info_api):
        """Test get_property for existing property."""
        device_info_api.get_info = AsyncMock(
            return_value=BasicDeviceInfo(
                serial_number="ACCC12345678",
                product_number="M3216-LVE",
            )
        )

        result = await device_info_api.get_property("serial_number")

        assert result == "ACCC12345678"

    @pytest.mark.asyncio
    async def test_get_property_nonexistent(self, device_info_api):
        """Test get_property for nonexistent property."""
        device_info_api.get_info = AsyncMock(return_value=BasicDeviceInfo())

        result = await device_info_api.get_property("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_properties(self, device_info_api):
        """Test get_properties method."""
        response = {
            "root": {
                "Properties": {
                    "FriendlyName": "Front Door Camera",
                    "Location": "Main Entrance",
                }
            }
        }
        device_info_api._get = AsyncMock(return_value=response)

        result = await device_info_api.get_properties()

        assert isinstance(result, DeviceProperties)
        assert result.friendly_name == "Front Door Camera"
        assert result.location == "Main Entrance"

    @pytest.mark.asyncio
    async def test_get_properties_error(self, device_info_api):
        """Test get_properties handles errors."""
        device_info_api._get = AsyncMock(side_effect=Exception("API error"))

        result = await device_info_api.get_properties()

        assert isinstance(result, DeviceProperties)
        assert result.friendly_name == ""

    def test_parse_properties_response(self, device_info_api):
        """Test _parse_properties_response method."""
        response = {
            "root": {
                "Properties": {
                    "FriendlyName": "Test Camera",
                    "Location": "Lab",
                    "FirmwareBuildDate": "2024-01-15",
                    "WebURL": "http://192.168.1.10",
                }
            }
        }

        result = device_info_api._parse_properties_response(response)

        assert result.friendly_name == "Test Camera"
        assert result.location == "Lab"
        assert result.firmware_build_date == "2024-01-15"
        assert result.web_url == "http://192.168.1.10"

    def test_parse_properties_response_empty(self, device_info_api):
        """Test _parse_properties_response with empty response."""
        result = device_info_api._parse_properties_response({})

        assert result.friendly_name == ""
        assert result.location == ""

    @pytest.mark.asyncio
    async def test_is_axis_device_true(self, device_info_api):
        """Test is_axis_device returns True for AXIS device."""
        device_info_api.get_info = AsyncMock(return_value=BasicDeviceInfo(brand="AXIS"))

        result = await device_info_api.is_axis_device()

        assert result is True

    @pytest.mark.asyncio
    async def test_is_axis_device_false(self, device_info_api):
        """Test is_axis_device returns False for non-AXIS device."""
        device_info_api.get_info = AsyncMock(return_value=BasicDeviceInfo(brand="Other"))

        result = await device_info_api.is_axis_device()

        assert result is False

    @pytest.mark.asyncio
    async def test_is_axis_device_error(self, device_info_api):
        """Test is_axis_device handles errors."""
        device_info_api.get_info = AsyncMock(side_effect=Exception("Error"))

        result = await device_info_api.is_axis_device()

        assert result is False

    @pytest.mark.asyncio
    async def test_get_firmware_version(self, device_info_api):
        """Test get_firmware_version method."""
        device_info_api.get_info = AsyncMock(
            return_value=BasicDeviceInfo(firmware_version="11.5.64")
        )

        result = await device_info_api.get_firmware_version()

        assert result == "11.5.64"

    @pytest.mark.asyncio
    async def test_get_serial_number(self, device_info_api):
        """Test get_serial_number method."""
        device_info_api.get_info = AsyncMock(
            return_value=BasicDeviceInfo(serial_number="ACCC12345678")
        )

        result = await device_info_api.get_serial_number()

        assert result == "ACCC12345678"

    @pytest.mark.asyncio
    async def test_get_model(self, device_info_api):
        """Test get_model method."""
        device_info_api.get_info = AsyncMock(
            return_value=BasicDeviceInfo(product_number="M3216-LVE")
        )

        result = await device_info_api.get_model()

        assert result == "M3216-LVE"
