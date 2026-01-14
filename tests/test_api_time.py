"""Tests for Time API module."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from axis_cam.api.time import TimeAPI
from axis_cam.models import NtpStatus, TimeInfo, TimeZoneSource


class TestTimeAPI:
    """Tests for TimeAPI class."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock VapixClient."""
        client = MagicMock()
        client.host = "192.168.1.10"
        return client

    @pytest.fixture
    def time_api(self, mock_client):
        """Create TimeAPI instance with mock client."""
        return TimeAPI(mock_client)

    def test_init(self, time_api):
        """Test TimeAPI initialization."""
        assert time_api._client is not None

    @pytest.mark.asyncio
    async def test_get_info_rest_api(self, time_api):
        """Test get_info using REST API."""
        main_response = {"data": {}}
        time_response = {
            "data": {
                "dateTime": "2024-01-15T12:00:00Z",
                "localDateTime": "2024-01-15T13:00:00+01:00",
                "maxSupportedYear": 2037,
            }
        }
        tz_response = {
            "data": {
                "activeTimeZone": "Europe/Stockholm",
                "iana": {"timeZone": "Europe/Stockholm"},
                "posix": {"timeZone": "CET-1CEST", "dstEnabled": True},
                "dhcp": {"enabled": False},
            }
        }

        call_count = 0

        async def mock_get(path, params=None):
            nonlocal call_count
            call_count += 1
            if "timeZone" in path:
                return tz_response
            elif "/time" in path:
                return time_response
            return main_response

        time_api._get = mock_get

        result = await time_api.get_info()

        assert isinstance(result, TimeInfo)
        assert result.timezone == "Europe/Stockholm"

    @pytest.mark.asyncio
    async def test_get_info_fallback_to_cgi(self, time_api):
        """Test get_info falls back to CGI when REST fails."""
        cgi_response = {
            "utcDateTime": "2024-01-15T12:00:00Z",
            "localDateTime": "2024-01-15T13:00:00",
            "timeZone": "Europe/Stockholm",
            "posixTimeZone": "CET-1CEST",
            "dstEnabled": "yes",
        }

        call_count = 0

        async def mock_get(path, params=None):
            nonlocal call_count
            call_count += 1
            if "rest" in path:
                raise Exception("REST API not available")
            return cgi_response

        time_api._get = mock_get

        result = await time_api.get_info()

        assert isinstance(result, TimeInfo)

    @pytest.mark.asyncio
    async def test_get_rest_time_info(self, time_api):
        """Test _get_rest_time_info method."""
        main_response = {"data": {}}
        time_response = {
            "data": {
                "dateTime": "2024-01-15T12:00:00Z",
            }
        }
        tz_response = {"data": {"activeTimeZone": "UTC", "iana": {}, "posix": {}, "dhcp": {}}}

        async def mock_get(path, params=None):
            if "timeZone" in path:
                return tz_response
            elif "/time" in path:
                return time_response
            return main_response

        time_api._get = mock_get

        result = await time_api._get_rest_time_info()

        assert isinstance(result, TimeInfo)

    @pytest.mark.asyncio
    async def test_get_cgi_time_info(self, time_api):
        """Test _get_cgi_time_info method."""
        response = {
            "utcDateTime": "2024-01-15T12:00:00Z",
            "localDateTime": "2024-01-15T13:00:00",
            "timeZone": "Europe/Stockholm",
            "dstEnabled": "yes",
        }
        time_api._get = AsyncMock(return_value=response)

        result = await time_api._get_cgi_time_info()

        assert isinstance(result, TimeInfo)
        assert result.timezone == "Europe/Stockholm"
        assert result.dst_enabled is True

    def test_parse_rest_response(self, time_api):
        """Test _parse_rest_response method."""
        data = {}
        time_data = {
            "dateTime": "2024-01-15T12:00:00Z",
            "localDateTime": "2024-01-15T13:00:00",
            "maxSupportedYear": 2037,
        }
        tz_data = {
            "activeTimeZone": "Europe/Stockholm",
            "iana": {"timeZone": "Europe/Stockholm"},
            "posix": {"timeZone": "CET-1CEST", "dstEnabled": True},
            "dhcp": {"enabled": False},
        }

        result = time_api._parse_rest_response(data, time_data, tz_data)

        assert isinstance(result, TimeInfo)
        assert result.timezone == "Europe/Stockholm"
        assert result.posix_timezone == "CET-1CEST"
        assert result.dst_enabled is True
        assert result.max_supported_year == 2037

    def test_parse_rest_response_dhcp_timezone(self, time_api):
        """Test _parse_rest_response with DHCP timezone source."""
        data = {}
        time_data = {"dateTime": "2024-01-15T12:00:00Z"}
        tz_data = {
            "activeTimeZone": "America/New_York",
            "iana": {},
            "posix": {},
            "dhcp": {"enabled": True},
        }

        result = time_api._parse_rest_response(data, time_data, tz_data)

        assert result.timezone_source == TimeZoneSource.DHCP

    def test_parse_rest_response_posix_timezone(self, time_api):
        """Test _parse_rest_response with POSIX timezone source."""
        data = {}
        time_data = {"dateTime": "2024-01-15T12:00:00Z"}
        tz_data = {
            "activeTimeZone": "",
            "iana": {},
            "posix": {"timeZone": "EST5EDT"},
            "dhcp": {"enabled": False},
        }

        result = time_api._parse_rest_response(data, time_data, tz_data)

        assert result.timezone_source == TimeZoneSource.POSIX

    def test_parse_cgi_response(self, time_api):
        """Test _parse_cgi_response method."""
        response = {
            "utcDateTime": "2024-01-15T12:00:00Z",
            "localDateTime": "2024-01-15T13:00:00",
            "timeZone": "Europe/Stockholm",
            "posixTimeZone": "CET-1CEST",
            "dstEnabled": "yes",
        }

        result = time_api._parse_cgi_response(response)

        assert isinstance(result, TimeInfo)
        assert result.timezone == "Europe/Stockholm"
        assert result.posix_timezone == "CET-1CEST"
        assert result.dst_enabled is True

    def test_parse_cgi_response_dst_disabled(self, time_api):
        """Test _parse_cgi_response with DST disabled."""
        response = {"utcDateTime": "2024-01-15T12:00:00Z", "timeZone": "UTC", "dstEnabled": "no"}

        result = time_api._parse_cgi_response(response)

        assert result.dst_enabled is False

    def test_parse_datetime_iso8601_with_z(self, time_api):
        """Test _parse_datetime with ISO 8601 Z suffix."""
        result = time_api._parse_datetime("2024-01-15T12:00:00Z")

        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_parse_datetime_iso8601_with_offset(self, time_api):
        """Test _parse_datetime with ISO 8601 offset."""
        result = time_api._parse_datetime("2024-01-15T13:00:00+01:00")

        assert isinstance(result, datetime)

    def test_parse_datetime_without_timezone(self, time_api):
        """Test _parse_datetime without timezone."""
        result = time_api._parse_datetime("2024-01-15T12:00:00")

        assert isinstance(result, datetime)

    def test_parse_datetime_empty_string(self, time_api):
        """Test _parse_datetime with empty string."""
        result = time_api._parse_datetime("")

        assert result is None

    def test_parse_datetime_invalid_format(self, time_api):
        """Test _parse_datetime with invalid format."""
        result = time_api._parse_datetime("not-a-date")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_utc_time(self, time_api):
        """Test get_utc_time convenience method."""
        cgi_response = {"utcDateTime": "2024-01-15T12:00:00Z", "timeZone": "UTC"}

        async def mock_get(path, params=None):
            if "rest" in path:
                raise Exception("REST not available")
            return cgi_response

        time_api._get = mock_get

        result = await time_api.get_utc_time()

        assert isinstance(result, datetime)

    @pytest.mark.asyncio
    async def test_get_local_time(self, time_api):
        """Test get_local_time convenience method."""
        cgi_response = {
            "utcDateTime": "2024-01-15T12:00:00Z",
            "localDateTime": "2024-01-15T13:00:00",
            "timeZone": "Europe/Stockholm",
        }

        async def mock_get(path, params=None):
            if "rest" in path:
                raise Exception("REST not available")
            return cgi_response

        time_api._get = mock_get

        result = await time_api.get_local_time()

        assert isinstance(result, datetime)

    @pytest.mark.asyncio
    async def test_get_local_time_none(self, time_api):
        """Test get_local_time returns None when not available."""
        cgi_response = {"utcDateTime": "2024-01-15T12:00:00Z", "timeZone": "UTC"}

        async def mock_get(path, params=None):
            if "rest" in path:
                raise Exception("REST not available")
            return cgi_response

        time_api._get = mock_get

        result = await time_api.get_local_time()

        assert result is None

    @pytest.mark.asyncio
    async def test_get_timezone(self, time_api):
        """Test get_timezone convenience method."""
        cgi_response = {"utcDateTime": "2024-01-15T12:00:00Z", "timeZone": "America/New_York"}

        async def mock_get(path, params=None):
            if "rest" in path:
                raise Exception("REST not available")
            return cgi_response

        time_api._get = mock_get

        result = await time_api.get_timezone()

        assert result == "America/New_York"

    @pytest.mark.asyncio
    async def test_get_ntp_status_rest_api(self, time_api):
        """Test get_ntp_status using REST API."""
        response = {"data": {"enabled": True, "server": "pool.ntp.org", "synchronized": True}}
        time_api._get = AsyncMock(return_value=response)

        result = await time_api.get_ntp_status()

        assert isinstance(result, NtpStatus)
        assert result.enabled is True
        assert result.server == "pool.ntp.org"
        assert result.synchronized is True

    @pytest.mark.asyncio
    async def test_get_ntp_status_fallback_to_params(self, time_api):
        """Test get_ntp_status falls back to param.cgi."""
        param_response = {"root": {"Time": {"NTP": {"Enabled": "yes", "Server": "time.nist.gov"}}}}

        async def mock_get(path, params=None):
            if "network-time-sync" in path:
                raise Exception("REST not available")
            return param_response

        time_api._get = mock_get

        result = await time_api.get_ntp_status()

        assert isinstance(result, NtpStatus)
        assert result.enabled is True
        assert result.server == "time.nist.gov"
        assert result.synchronized is False  # Not available via param.cgi

    @pytest.mark.asyncio
    async def test_get_ntp_from_params(self, time_api):
        """Test _get_ntp_from_params method."""
        response = {"root": {"Time": {"NTP": {"Enabled": "yes", "Server": "ntp.example.com"}}}}
        time_api._get = AsyncMock(return_value=response)

        result = await time_api._get_ntp_from_params()

        assert result.enabled is True
        assert result.server == "ntp.example.com"

    @pytest.mark.asyncio
    async def test_get_ntp_from_params_disabled(self, time_api):
        """Test _get_ntp_from_params with NTP disabled."""
        response = {"root": {"Time": {"NTP": {"Enabled": "no", "Server": ""}}}}
        time_api._get = AsyncMock(return_value=response)

        result = await time_api._get_ntp_from_params()

        assert result.enabled is False

    @pytest.mark.asyncio
    async def test_get_ntp_from_params_exception(self, time_api):
        """Test _get_ntp_from_params returns default on exception."""
        time_api._get = AsyncMock(side_effect=Exception("API error"))

        result = await time_api._get_ntp_from_params()

        assert isinstance(result, NtpStatus)
        assert result.enabled is False

    @pytest.mark.asyncio
    async def test_get_available_timezones(self, time_api):
        """Test get_available_timezones method."""
        response = {
            "data": {"timeZones": ["UTC", "America/New_York", "Europe/Stockholm", "Asia/Tokyo"]}
        }
        time_api._post = AsyncMock(return_value=response)

        result = await time_api.get_available_timezones()

        assert isinstance(result, list)
        assert "UTC" in result
        assert "Europe/Stockholm" in result

    @pytest.mark.asyncio
    async def test_get_available_timezones_exception(self, time_api):
        """Test get_available_timezones returns empty list on exception."""
        time_api._post = AsyncMock(side_effect=Exception("API error"))

        result = await time_api.get_available_timezones()

        assert result == []
