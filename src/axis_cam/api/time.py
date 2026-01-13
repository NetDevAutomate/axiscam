"""Time API module.

This module provides access to device time and timezone settings
via the VAPIX time API.

API Endpoints:
    - /config/rest/time/v2 (REST API)
    - /axis-cgi/date.cgi (Legacy CGI)

The module supports reading time settings. Write operations
are not implemented for safety.
"""

from datetime import datetime
from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import NtpStatus, TimeInfo, TimeZoneSource


class TimeAPI(BaseAPI):
    """API module for device time and timezone settings.

    This module provides methods to retrieve:
    - Current UTC and local time
    - Timezone configuration
    - NTP synchronization status

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     time_info = await camera.time.get_info()
        ...     print(f"UTC: {time_info.utc_time}")
        ...     print(f"Local: {time_info.local_time}")
        ...     print(f"Timezone: {time_info.timezone}")
    """

    # REST API endpoint (AXIS OS 11.x+)
    REST_PATH = "/config/rest/time/v2"

    # Legacy CGI endpoint
    CGI_PATH = "/axis-cgi/date.cgi"

    async def get_info(self) -> TimeInfo:
        """Get complete time information.

        Retrieves UTC time, local time, timezone, and other
        time-related settings from the device.

        Returns:
            TimeInfo model with all time settings.
        """
        try:
            # Try REST API first
            return await self._get_rest_time_info()
        except Exception:
            # Fall back to legacy CGI
            return await self._get_cgi_time_info()

    async def _get_rest_time_info(self) -> TimeInfo:
        """Get time info via REST API.

        Returns:
            TimeInfo model from REST API response.
        """
        # Get main time entity
        response = await self._get(self.REST_PATH)
        data = response.get("data", {})

        # Check if combined response (some devices return time+timezone together)
        if "time" in data and "timeZone" in data:
            time_data = data.get("time", {})
            tz_data = data.get("timeZone", {})
        else:
            # Get time settings separately
            time_response = await self._get(f"{self.REST_PATH}/time")
            time_data = time_response.get("data", {})

            # Get timezone settings separately
            tz_response = await self._get(f"{self.REST_PATH}/timeZone")
            tz_data = tz_response.get("data", {})

        return self._parse_rest_response(data, time_data, tz_data)

    async def _get_cgi_time_info(self) -> TimeInfo:
        """Get time info via legacy CGI endpoint.

        Returns:
            TimeInfo model from CGI response.
        """
        params = {"action": "get"}
        response = await self._get(self.CGI_PATH, params)
        return self._parse_cgi_response(response)

    def _parse_rest_response(
        self,
        data: dict[str, Any],
        time_data: dict[str, Any],
        tz_data: dict[str, Any],
    ) -> TimeInfo:
        """Parse REST API response into TimeInfo model.

        Args:
            data: Main time entity response.
            time_data: Time settings response.
            tz_data: Timezone settings response.

        Returns:
            TimeInfo model instance.
        """
        # Parse UTC time
        utc_str = time_data.get("dateTime", "")
        utc_time = self._parse_datetime(utc_str) or datetime.now()

        # Parse local time
        local_str = time_data.get("localDateTime", "")
        local_time = self._parse_datetime(local_str)

        # Parse timezone
        active_tz = tz_data.get("activeTimeZone", "")
        tz_source = TimeZoneSource.IANA

        # Check timezone source
        dhcp_data = tz_data.get("dhcp") or {}
        iana_data = tz_data.get("iana") or {}
        posix_data = tz_data.get("posix") or {}

        if dhcp_data.get("enabled", False):
            tz_source = TimeZoneSource.DHCP
        elif posix_data.get("timeZone"):
            tz_source = TimeZoneSource.POSIX

        # Handle None values from device responses
        posix_tz = posix_data.get("timeZone") or ""
        dst_enabled = posix_data.get("dstEnabled", True)
        max_year = time_data.get("maxSupportedYear", 2037)
        timezone = active_tz or iana_data.get("timeZone") or ""

        return TimeInfo(
            utc_time=utc_time,
            local_time=local_time,
            timezone=timezone,
            timezone_source=tz_source,
            posix_timezone=posix_tz,
            dst_enabled=dst_enabled,
            max_supported_year=max_year,
        )

    def _parse_cgi_response(self, response: dict[str, Any]) -> TimeInfo:
        """Parse CGI response into TimeInfo model.

        Args:
            response: Raw CGI response.

        Returns:
            TimeInfo model instance.
        """
        # CGI returns simpler format
        utc_str = response.get("utcDateTime", "")
        local_str = response.get("localDateTime", "")
        timezone = response.get("timeZone", "")
        posix_tz = response.get("posixTimeZone", "")
        dst = response.get("dstEnabled", "yes") == "yes"

        utc_time = self._parse_datetime(utc_str) or datetime.now()
        local_time = self._parse_datetime(local_str)

        return TimeInfo(
            utc_time=utc_time,
            local_time=local_time,
            timezone=timezone,
            timezone_source=TimeZoneSource.IANA,
            posix_timezone=posix_tz,
            dst_enabled=dst,
        )

    def _parse_datetime(self, dt_str: str) -> datetime | None:
        """Parse ISO 8601 datetime string.

        Args:
            dt_str: ISO 8601 formatted datetime string.

        Returns:
            Parsed datetime or None if parsing fails.
        """
        if not dt_str:
            return None

        try:
            # Handle various ISO 8601 formats
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except ValueError:
            try:
                # Try without timezone
                return datetime.fromisoformat(dt_str)
            except ValueError:
                return None

    async def get_utc_time(self) -> datetime:
        """Get current UTC time from device.

        Returns:
            Current UTC datetime.
        """
        info = await self.get_info()
        return info.utc_time

    async def get_local_time(self) -> datetime | None:
        """Get current local time from device.

        Returns:
            Current local datetime or None if not available.
        """
        info = await self.get_info()
        return info.local_time

    async def get_timezone(self) -> str:
        """Get the configured timezone.

        Returns:
            Timezone identifier (e.g., "Europe/Stockholm").
        """
        info = await self.get_info()
        return info.timezone

    async def get_ntp_status(self) -> NtpStatus:
        """Get NTP synchronization status.

        Returns:
            NtpStatus with NTP configuration and sync state.
        """
        try:
            # Try REST API for network time sync
            response = await self._get("/config/rest/network-time-sync/v1beta")
            data = response.get("data", {})

            return NtpStatus(
                enabled=data.get("enabled", False),
                server=data.get("server", ""),
                synchronized=data.get("synchronized", False),
            )
        except Exception:
            # Fall back to param.cgi
            return await self._get_ntp_from_params()

    async def _get_ntp_from_params(self) -> NtpStatus:
        """Get NTP status from param.cgi.

        Returns:
            NtpStatus from parameter values.
        """
        try:
            params = {"action": "list", "group": "root.Time.NTP"}
            response = await self._get("/axis-cgi/param.cgi", params)

            ntp_data = response.get("root", {}).get("Time", {}).get("NTP", {})

            return NtpStatus(
                enabled=ntp_data.get("Enabled", "no") == "yes",
                server=ntp_data.get("Server", ""),
                synchronized=False,  # Not available via param.cgi
            )
        except Exception:
            return NtpStatus()

    async def get_available_timezones(self) -> list[str]:
        """Get list of available IANA timezones.

        Returns:
            List of timezone identifiers supported by the device.
        """
        try:
            response = await self._post(
                f"{self.REST_PATH}/timeZone/iana/getTimeZoneList",
                json_data={},
            )
            return response.get("data", {}).get("timeZones", [])
        except Exception:
            return []
