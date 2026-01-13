"""Basic Device Info API module.

This module provides access to basic device information via the VAPIX
basic-device-info API and the legacy basicdeviceinfo.cgi endpoint.

API Endpoints:
    - /config/rest/basic-device-info/v2beta (REST API)
    - /axis-cgi/basicdeviceinfo.cgi (Legacy CGI)

The module automatically falls back to legacy endpoints if the REST API
is not available on older firmware versions.
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import BasicDeviceInfo, DeviceProperties


class BasicDeviceInfoAPI(BaseAPI):
    """API module for retrieving basic device information.

    This module provides methods to retrieve device information including:
    - Product name and model number
    - Serial number and hardware ID
    - Firmware version
    - Architecture and SoC information

    The module supports both the REST API (AXIS OS 11.x+) and the legacy
    CGI endpoint for backward compatibility.

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     info = await camera.device_info.get_info()
        ...     print(f"Model: {info.product_number}")
        ...     print(f"Serial: {info.serial_number}")
        ...     print(f"Firmware: {info.firmware_version}")
    """

    # Legacy CGI endpoint
    CGI_PATH = "/axis-cgi/basicdeviceinfo.cgi"

    # REST API endpoint (AXIS OS 11.x+)
    REST_PATH = "/config/rest/basic-device-info/v2beta"

    async def get_info(self) -> BasicDeviceInfo:
        """Get basic device information.

        Attempts the REST API first, then falls back to the legacy CGI
        endpoint if the REST API is not available.

        Returns:
            BasicDeviceInfo model with device details.

        Raises:
            AxisConnectionError: If connection fails.
            AxisDeviceError: If device returns an error.
        """
        # Try REST API first
        try:
            data = await self._get_rest_info()
            # Verify REST response contains actual device info
            if data and self._has_device_info_fields(data):
                return self._parse_rest_response(data)
        except Exception:
            pass

        # Fall back to legacy CGI
        data = await self._get_cgi_info()
        return self._parse_cgi_response(data)

    def _has_device_info_fields(self, data: dict[str, Any]) -> bool:
        """Check if the data contains expected device info fields.

        Args:
            data: Response data to check.

        Returns:
            True if data contains device info, False otherwise.
        """
        # Check for any of the expected device info fields
        expected_fields = {
            "SerialNumber", "ProdNbr", "Version", "Brand",
            "serialNumber", "prodNbr", "version", "brand",
        }
        return bool(expected_fields & set(data.keys()))

    async def _get_rest_info(self) -> dict[str, Any]:
        """Get device info via REST API.

        Returns:
            Raw REST API response data.
        """
        response = await self._get(self.REST_PATH)
        return response.get("data", {})

    async def _get_cgi_info(self) -> dict[str, Any]:
        """Get device info via legacy CGI endpoint.

        The CGI endpoint requires a POST request with JSON body and returns
        data in a different format that needs to be normalized.

        Returns:
            Normalized device info dictionary.
        """
        json_data = {"apiVersion": "1.0", "method": "getAllProperties"}
        response = await self._post(self.CGI_PATH, json_data=json_data)
        return self._normalize_cgi_response(response)

    def _normalize_cgi_response(self, response: dict[str, Any]) -> dict[str, Any]:
        """Normalize CGI response to match REST API structure.

        The CGI endpoint returns data under "data.propertyList" as a flat
        dictionary. The response format is:
        {"apiVersion": "1.3", "data": {"propertyList": {"ProdNbr": "M3216-LVE", ...}}}

        Args:
            response: Raw CGI response.

        Returns:
            Normalized dictionary with device info.
        """
        # New format: data.propertyList is a flat dict
        data = response.get("data", {})
        property_list = data.get("propertyList", {})

        if isinstance(property_list, dict) and property_list:
            return property_list

        # Legacy format: propertyList.properties is an array
        props = response.get("propertyList", {}).get("properties", [])
        result: dict[str, Any] = {}

        for prop in props:
            name = prop.get("name", "")
            value = prop.get("value", "")
            if name and value:
                result[name] = value

        return result

    def _parse_rest_response(self, data: dict[str, Any]) -> BasicDeviceInfo:
        """Parse REST API response into BasicDeviceInfo model.

        Args:
            data: REST API response data.

        Returns:
            BasicDeviceInfo model instance.
        """
        return BasicDeviceInfo.model_validate(data)

    def _parse_cgi_response(self, data: dict[str, Any]) -> BasicDeviceInfo:
        """Parse CGI response into BasicDeviceInfo model.

        Args:
            data: Normalized CGI response data.

        Returns:
            BasicDeviceInfo model instance.
        """
        return BasicDeviceInfo.model_validate(data)

    async def get_property(self, property_name: str) -> str | None:
        """Get a specific device property by name.

        Args:
            property_name: Name of the property (e.g., "SerialNumber").

        Returns:
            Property value or None if not found.
        """
        info = await self.get_info()
        return getattr(info, property_name.lower().replace("-", "_"), None)

    async def get_properties(self) -> DeviceProperties:
        """Get extended device properties.

        This method retrieves additional properties not included in
        the basic device info, such as friendly name and location.

        Returns:
            DeviceProperties model with extended info.

        Note:
            This requires the Param API to be available.
        """
        # Extended properties come from param.cgi
        params = {
            "action": "list",
            "group": "root.Properties",
        }
        try:
            response = await self._get("/axis-cgi/param.cgi", params)
            return self._parse_properties_response(response)
        except Exception:
            return DeviceProperties()

    def _parse_properties_response(
        self, response: dict[str, Any]
    ) -> DeviceProperties:
        """Parse properties response.

        Args:
            response: Raw properties response.

        Returns:
            DeviceProperties model instance.
        """
        # Extract relevant properties from param.cgi response
        props = response.get("root", {}).get("Properties", {})

        return DeviceProperties(
            friendly_name=props.get("FriendlyName", ""),
            location=props.get("Location", ""),
            firmware_build_date=props.get("FirmwareBuildDate", ""),
            web_url=props.get("WebURL", ""),
        )

    async def is_axis_device(self) -> bool:
        """Check if this is a genuine AXIS device.

        Returns:
            True if device identifies as AXIS brand.
        """
        try:
            info = await self.get_info()
            return info.brand.upper() == "AXIS"
        except Exception:
            return False

    async def get_firmware_version(self) -> str:
        """Get the firmware version string.

        Returns:
            Firmware version string.
        """
        info = await self.get_info()
        return info.firmware_version

    async def get_serial_number(self) -> str:
        """Get the device serial number.

        Returns:
            Device serial number.
        """
        info = await self.get_info()
        return info.serial_number

    async def get_model(self) -> str:
        """Get the device model number.

        Returns:
            Device model number (e.g., "M3216-LVE").
        """
        info = await self.get_info()
        return info.product_number
