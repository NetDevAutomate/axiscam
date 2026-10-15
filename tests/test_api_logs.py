"""Tests for Logs API module."""

import base64
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from axis_cam.api.logs import (
    LOG_FILE_PATTERNS,
    LogsAPI,
    ServerReportMode,
    parse_log_content,
    parse_log_line,
)
from axis_cam.client import VapixClient
from axis_cam.exceptions import AxisAuthenticationError, AxisDeviceError, AxisEchoError
from axis_cam.models import LogEntry, LogLevel, LogType


class TestParseLogLine:
    """Tests for parse_log_line function."""

    def test_parse_empty_line(self):
        """Test parsing an empty line returns None."""
        assert parse_log_line("") is None
        assert parse_log_line("   ") is None

    def test_parse_axis_syslog_format(self):
        """Test parsing AXIS syslog format."""
        line = (
            "2024-01-15T12:00:00+00:00 axis-device [ INFO ] "
            "httpd[1234]: Connection from 192.168.1.1"
        )
        entry = parse_log_line(line)

        assert entry is not None
        assert entry.hostname == "axis-device"
        assert entry.level == LogLevel.INFO
        assert entry.process == "httpd"
        assert entry.pid == 1234
        assert "Connection from 192.168.1.1" in entry.message
        assert entry.raw == line

    def test_parse_axis_syslog_error_level(self):
        """Test parsing error level log."""
        line = "2024-01-15T12:00:00+00:00 axis-device [ ERR ] kernel: Out of memory"
        entry = parse_log_line(line)

        assert entry is not None
        assert entry.level == LogLevel.ERROR
        assert entry.process == "kernel"
        assert entry.pid is None

    def test_parse_axis_syslog_warning_level(self):
        """Test parsing warning level log."""
        line = "2024-01-15T12:00:00+00:00 axis-device [ WARNING ] watchdog[100]: Process restarted"
        entry = parse_log_line(line)

        assert entry is not None
        assert entry.level == LogLevel.WARNING
        assert entry.process == "watchdog"
        assert entry.pid == 100

    def test_parse_simple_format(self):
        """Test parsing simple log format."""
        line = "2024-01-15 12:00:00 Simple log message"
        entry = parse_log_line(line)

        assert entry is not None
        assert entry.level == LogLevel.INFO
        assert entry.message == "Simple log message"
        assert entry.hostname == "unknown"

    def test_parse_unparseable_line(self):
        """Test parsing an unparseable line."""
        line = "random text without timestamp"
        entry = parse_log_line(line)

        assert entry is not None
        assert entry.level == LogLevel.INFO
        assert entry.message == line
        assert entry.hostname == "unknown"

    def test_parse_with_milliseconds(self):
        """Test parsing timestamp with milliseconds."""
        line = "2024-01-15T12:00:00.123+00:00 axis-device [ DEBUG ] app: Test message"
        entry = parse_log_line(line)

        assert entry is not None
        assert entry.level == LogLevel.DEBUG

    def test_parse_no_pid(self):
        """Test parsing log line without PID."""
        line = "2024-01-15T12:00:00+00:00 axis-device [ NOTICE ] systemd: Service started"
        entry = parse_log_line(line)

        assert entry is not None
        assert entry.level == LogLevel.NOTICE
        assert entry.process == "systemd"
        assert entry.pid is None


class TestParseLogContent:
    """Tests for parse_log_content function."""

    def test_parse_empty_content(self):
        """Test parsing empty content."""
        result = parse_log_content("")
        assert result == []

    def test_parse_single_line(self):
        """Test parsing single line content."""
        content = "2024-01-15T12:00:00+00:00 axis-device [ INFO ] app: Test message"
        result = parse_log_content(content)
        assert len(result) == 1
        assert result[0].level == LogLevel.INFO

    def test_parse_multiple_lines(self):
        """Test parsing multiple lines."""
        content = """2024-01-15T12:00:00+00:00 axis-device [ INFO ] app: Message 1
2024-01-15T12:00:01+00:00 axis-device [ WARNING ] app: Message 2
2024-01-15T12:00:02+00:00 axis-device [ ERR ] app: Message 3"""
        result = parse_log_content(content)
        assert len(result) == 3
        assert result[0].level == LogLevel.INFO
        assert result[1].level == LogLevel.WARNING
        assert result[2].level == LogLevel.ERROR

    def test_parse_skips_empty_lines(self):
        """Test that empty lines are skipped."""
        content = """2024-01-15T12:00:00+00:00 axis-device [ INFO ] app: Message 1

2024-01-15T12:00:02+00:00 axis-device [ INFO ] app: Message 2"""
        result = parse_log_content(content)
        assert len(result) == 2


class TestServerReportMode:
    """Tests for ServerReportMode enum."""

    def test_mode_values(self):
        """Test ServerReportMode enum values."""
        assert ServerReportMode.TEXT.value == "text"
        assert ServerReportMode.TAR_ALL.value == "tar_all"
        assert ServerReportMode.ZIP.value == "zip"
        assert ServerReportMode.ZIP_WITH_IMAGE.value == "zip_with_image"


class TestLogFilePatterns:
    """Tests for LOG_FILE_PATTERNS constant."""

    def test_system_patterns(self):
        """Test system log file patterns."""
        patterns = LOG_FILE_PATTERNS[LogType.SYSTEM]
        assert "syslog" in patterns
        assert "messages" in patterns

    def test_access_patterns(self):
        """Test access log file patterns."""
        patterns = LOG_FILE_PATTERNS[LogType.ACCESS]
        assert "access.log" in patterns

    def test_audit_patterns(self):
        """Test audit log file patterns."""
        patterns = LOG_FILE_PATTERNS[LogType.AUDIT]
        assert "audit.log" in patterns


class TestLogsAPI:
    """Tests for LogsAPI class."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock VapixClient."""
        client = MagicMock()
        client.host = "192.168.1.10"
        return client

    @pytest.fixture
    def logs_api(self, mock_client):
        """Create LogsAPI instance with mock client."""
        return LogsAPI(mock_client, device_name="test-device")

    def test_init(self, logs_api):
        """Test LogsAPI initialization."""
        assert logs_api._device_name == "test-device"

    def test_find_log_content_all(self, logs_api):
        """Test finding all log content."""
        log_files = {
            "syslog": "system logs",
            "access.log": "access logs",
            "audit.log": "audit logs",
        }
        result = logs_api._find_log_content(log_files, LogType.ALL)
        assert "system logs" in result
        assert "access logs" in result
        assert "audit logs" in result

    def test_find_log_content_system(self, logs_api):
        """Test finding system log content."""
        log_files = {
            "syslog": "system logs",
            "access.log": "access logs",
        }
        result = logs_api._find_log_content(log_files, LogType.SYSTEM)
        assert "system logs" in result
        assert "access logs" not in result

    def test_find_log_content_access(self, logs_api):
        """Test finding access log content."""
        log_files = {
            "syslog": "system logs",
            "access.log": "access logs",
        }
        result = logs_api._find_log_content(log_files, LogType.ACCESS)
        assert "access logs" in result
        assert "system logs" not in result

    def test_find_log_content_no_match(self, logs_api):
        """Test finding log content with no matching files."""
        log_files = {
            "other.log": "other logs",
        }
        result = logs_api._find_log_content(log_files, LogType.SYSTEM)
        assert result == ""

    @pytest.mark.asyncio
    async def test_get_server_report_text_mode(self, logs_api, mock_client):
        """Test getting server report in text mode."""
        logs_api._get_raw = AsyncMock(return_value=b"log content")

        result = await logs_api.get_server_report(ServerReportMode.TEXT)

        assert result == b"log content"
        logs_api._get_raw.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_server_report_tar_mode(self, logs_api, mock_client):
        """Test getting server report in tar mode."""
        logs_api._get_raw = AsyncMock(return_value=b"tar content")

        result = await logs_api.get_server_report(ServerReportMode.TAR_ALL)

        assert result == b"tar content"
        logs_api._get_raw.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_logs(self, logs_api, mock_client):
        """Test getting logs."""
        log_content = """2024-01-15T12:00:00+00:00 axis-device [ INFO ] app: Message 1
2024-01-15T12:00:01+00:00 axis-device [ WARNING ] app: Message 2"""

        logs_api._get_text = AsyncMock(side_effect=AxisDeviceError("404"))  # no systemlog.cgi
        logs_api.get_log_files = AsyncMock(return_value={"syslog": log_content})

        result = await logs_api.get_logs(LogType.SYSTEM)

        assert result.device_name == "test-device"
        assert result.device_address == "192.168.1.10"
        assert result.log_type == LogType.SYSTEM
        assert len(result.entries) == 2
        assert result.source == LogsAPI.TARBALL_SOURCE

    @pytest.mark.asyncio
    async def test_get_logs_with_max_entries(self, logs_api, mock_client):
        """Test getting logs with max_entries limit."""
        log_content = """2024-01-15T12:00:00+00:00 axis-device [ INFO ] app: Message 1
2024-01-15T12:00:01+00:00 axis-device [ INFO ] app: Message 2
2024-01-15T12:00:02+00:00 axis-device [ INFO ] app: Message 3"""

        logs_api._get_text = AsyncMock(side_effect=AxisDeviceError("404"))
        logs_api.get_log_files = AsyncMock(return_value={"syslog": log_content})

        result = await logs_api.get_logs(LogType.SYSTEM, max_entries=2)

        assert len(result.entries) == 2

    @pytest.mark.asyncio
    async def test_get_system_logs(self, logs_api):
        """Test get_system_logs convenience method."""
        logs_api.get_logs = AsyncMock()

        await logs_api.get_system_logs(max_entries=10)

        logs_api.get_logs.assert_called_once_with(LogType.SYSTEM, 10)

    @pytest.mark.asyncio
    async def test_get_access_logs(self, logs_api):
        """Test get_access_logs convenience method."""
        logs_api.get_logs = AsyncMock()

        await logs_api.get_access_logs(max_entries=10)

        logs_api.get_logs.assert_called_once_with(LogType.ACCESS, 10)

    @pytest.mark.asyncio
    async def test_get_audit_logs(self, logs_api):
        """Test get_audit_logs convenience method."""
        logs_api.get_logs = AsyncMock()

        await logs_api.get_audit_logs(max_entries=10)

        logs_api.get_logs.assert_called_once_with(LogType.AUDIT, 10)

    @pytest.mark.asyncio
    async def test_get_all_logs(self, logs_api):
        """Test get_all_logs convenience method."""
        logs_api.get_logs = AsyncMock()

        await logs_api.get_all_logs(max_entries=10)

        logs_api.get_logs.assert_called_once_with(LogType.ALL, 10)

    @pytest.mark.asyncio
    async def test_search_logs(self, logs_api):
        """Test searching logs."""
        from axis_cam.models import LogReport

        entries = [
            LogEntry(timestamp=datetime.now(), message="Error occurred in auth"),
            LogEntry(timestamp=datetime.now(), message="Info: Connection established"),
            LogEntry(timestamp=datetime.now(), message="Warning: Auth failed"),
        ]
        mock_report = LogReport(
            device_name="test-device",
            device_address="192.168.1.10",
            log_type=LogType.SYSTEM,
            entries=entries,
        )
        logs_api.get_logs = AsyncMock(return_value=mock_report)

        result = await logs_api.search_logs("auth", LogType.SYSTEM)

        assert len(result.entries) == 2  # "auth" appears in 2 messages

    @pytest.mark.asyncio
    async def test_search_logs_case_insensitive(self, logs_api):
        """Test that log search is case insensitive."""
        from axis_cam.models import LogReport

        entries = [
            LogEntry(timestamp=datetime.now(), message="ERROR occurred"),
            LogEntry(timestamp=datetime.now(), message="error occurred"),
            LogEntry(timestamp=datetime.now(), message="Error occurred"),
        ]
        mock_report = LogReport(
            device_name="test-device",
            device_address="192.168.1.10",
            log_type=LogType.SYSTEM,
            entries=entries,
        )
        logs_api.get_logs = AsyncMock(return_value=mock_report)

        result = await logs_api.search_logs("error", LogType.SYSTEM)

        assert len(result.entries) == 3

    @pytest.mark.asyncio
    async def test_search_logs_with_max_entries(self, logs_api):
        """Test search logs with max_entries limit."""
        from axis_cam.models import LogReport

        entries = [
            LogEntry(timestamp=datetime.now(), message="Error 1"),
            LogEntry(timestamp=datetime.now(), message="Error 2"),
            LogEntry(timestamp=datetime.now(), message="Error 3"),
        ]
        mock_report = LogReport(
            device_name="test-device",
            device_address="192.168.1.10",
            log_type=LogType.SYSTEM,
            entries=entries,
        )
        logs_api.get_logs = AsyncMock(return_value=mock_report)

        result = await logs_api.search_logs("Error", LogType.SYSTEM, max_entries=2)

        assert len(result.entries) == 2

    @pytest.mark.asyncio
    async def test_get_log_summary(self, logs_api):
        """Test getting log summary."""
        from axis_cam.models import LogReport

        entries = [
            LogEntry(timestamp=datetime.now(), message="Info 1", level=LogLevel.INFO),
            LogEntry(timestamp=datetime.now(), message="Info 2", level=LogLevel.INFO),
            LogEntry(timestamp=datetime.now(), message="Error 1", level=LogLevel.ERROR),
            LogEntry(timestamp=datetime.now(), message="Warning 1", level=LogLevel.WARNING),
        ]
        mock_report = LogReport(
            device_name="test-device",
            device_address="192.168.1.10",
            log_type=LogType.SYSTEM,
            entries=entries,
        )
        logs_api.get_logs = AsyncMock(return_value=mock_report)

        result = await logs_api.get_log_summary(LogType.SYSTEM)

        assert result["info"] == 2
        assert result["error"] == 1
        assert result["warning"] == 1

    @pytest.mark.asyncio
    async def test_stream_logs(self, logs_api):
        """Test streaming logs."""
        log_content = """2024-01-15T12:00:00+00:00 axis-device [ INFO ] app: Message 1
2024-01-15T12:00:01+00:00 axis-device [ INFO ] app: Message 2"""

        logs_api._get_text = AsyncMock(side_effect=AxisDeviceError("404"))
        logs_api.get_log_files = AsyncMock(return_value={"syslog": log_content})

        entries = []
        async for entry in logs_api.stream_logs(LogType.SYSTEM):
            entries.append(entry)

        assert len(entries) == 2

    @pytest.mark.asyncio
    async def test_get_persistent_logging_enabled(self, logs_api):
        """Test checking persistent logging status."""
        logs_api._get = AsyncMock(return_value={"data": {"enabled": True}})

        result = await logs_api.get_persistent_logging_enabled()

        assert result is True

    @pytest.mark.asyncio
    async def test_get_persistent_logging_enabled_error(self, logs_api):
        """Test persistent logging check on error."""
        logs_api._get = AsyncMock(side_effect=AxisDeviceError("API error"))

        result = await logs_api.get_persistent_logging_enabled()

        assert result is False


class TestTimestampNormalisation:
    """Every entry gets a timezone-aware timestamp so sorting cannot raise.

    AXIS emits offsets (``+00:00``), which parse aware; unparseable lines used
    to get naive ``datetime.now()``. Mixing the two made ``get_logs`` raise
    ``TypeError: can't compare offset-naive and offset-aware datetimes``.
    """

    AWARE = "2025-07-22T15:38:25.307+00:00 axis-abc [ INFO    ] fwmgr[4518]: Upgrade completed"
    SIMPLE = "2025-07-22 15:40:00 Simple message"
    CONTINUATION = "    at some.stack.Frame(Frame.java:42)"

    def test_syslog_timestamp_is_aware(self):
        entry = parse_log_line(self.AWARE)
        assert entry is not None
        assert entry.timestamp.tzinfo is not None
        assert entry.timestamp.utcoffset().total_seconds() == 0

    def test_simple_timestamp_is_made_aware_as_utc(self):
        entry = parse_log_line(self.SIMPLE)
        assert entry is not None
        assert entry.timestamp.tzinfo is not None

    def test_unparseable_line_timestamp_is_aware(self):
        entry = parse_log_line("random text without timestamp")
        assert entry is not None
        assert entry.timestamp.tzinfo is not None

    def test_unparseable_line_inherits_fallback_timestamp(self):
        parent = parse_log_line(self.AWARE)
        assert parent is not None
        child = parse_log_line(self.CONTINUATION, fallback_timestamp=parent.timestamp)
        assert child is not None
        assert child.timestamp == parent.timestamp

    def test_parse_log_content_anchors_continuation_lines(self):
        entries = parse_log_content("\n".join([self.AWARE, self.CONTINUATION, self.SIMPLE]))
        assert entries[0].timestamp == entries[1].timestamp
        assert all(e.timestamp.tzinfo is not None for e in entries)

    @pytest.mark.asyncio
    async def test_get_logs_sorts_mixed_formats_without_error(self):
        """Regression: the mix that used to raise TypeError in get_logs."""
        import io
        import tarfile

        content = "\n".join([self.SIMPLE, self.AWARE, self.CONTINUATION]).encode()
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name="var/log/syslog")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))

        client = MagicMock()
        client.host = "192.168.1.10"
        api = LogsAPI(client, device_name="test-device")
        api._get_text = AsyncMock(side_effect=AxisDeviceError("404"))  # force the tarball path
        api._get_raw = AsyncMock(return_value=buf.getvalue())

        report = await api.get_logs(LogType.SYSTEM)

        assert len(report.entries) == 3
        timestamps = [e.timestamp for e in report.entries]
        assert timestamps == sorted(timestamps, reverse=True)
        # Newest first: the simple-format line (15:40) precedes the syslog line (15:38),
        # and the continuation line stays directly after its parent.
        assert report.entries[0].raw == self.SIMPLE
        assert report.entries[1].raw == self.AWARE
        assert report.entries[2].raw == self.CONTINUATION.strip()


class TestDedicatedLogEndpoints:
    """System, access and audit logs come from their own CGIs; the server
    report tarball is the fallback and the source for LogType.ALL."""

    SYSLOG = "2024-01-15T12:00:00+00:00 axis-device [ INFO ] app: Message 1"

    def _api(self, *, text=None, text_error=None):
        client = MagicMock()
        client.host = "192.168.1.10"
        api = LogsAPI(client, device_name="test-device")
        if text_error is not None:
            api._get_text = AsyncMock(side_effect=text_error)
        else:
            api._get_text = AsyncMock(return_value=text if text is not None else self.SYSLOG)
        api.get_log_files = AsyncMock(
            return_value={"var/log/syslog": "tarball line", "var/log/audit/audit.log": "audit line"}
        )
        return api

    @pytest.mark.asyncio
    async def test_system_logs_use_systemlog_cgi(self):
        api = self._api()

        report = await api.get_logs(LogType.SYSTEM)

        api._get_text.assert_awaited_once_with("/axis-cgi/systemlog.cgi", None)
        api.get_log_files.assert_not_awaited()
        assert report.source == "systemlog.cgi"
        assert [e.raw for e in report.entries] == [self.SYSLOG]

    @pytest.mark.asyncio
    async def test_access_logs_use_accesslog_cgi(self):
        api = self._api()

        report = await api.get_logs(LogType.ACCESS)

        api._get_text.assert_awaited_once_with("/axis-cgi/accesslog.cgi", None)
        assert report.source == "accesslog.cgi"

    @pytest.mark.asyncio
    async def test_audit_logs_pass_max_entries_as_tail(self):
        api = self._api()

        report = await api.get_logs(LogType.AUDIT, max_entries=50)

        api._get_text.assert_awaited_once_with("/axis-cgi/auditlog.cgi", {"tail": "50"})
        assert report.source == "auditlog.cgi"

    @pytest.mark.asyncio
    async def test_audit_logs_without_limit_fetch_everything(self):
        api = self._api()

        await api.get_logs(LogType.AUDIT)

        api._get_text.assert_awaited_once_with("/axis-cgi/auditlog.cgi", None)

    @pytest.mark.asyncio
    async def test_missing_cgi_falls_back_to_the_tarball(self):
        api = self._api(text_error=AxisDeviceError("Device error 404"))

        report = await api.get_logs(LogType.AUDIT)

        api.get_log_files.assert_awaited_once()
        assert report.source == LogsAPI.TARBALL_SOURCE
        assert [e.raw for e in report.entries] == ["audit line"]  # the audit file, not syslog

    @pytest.mark.asyncio
    async def test_auth_error_on_the_cgi_propagates_instead_of_falling_back(self):
        api = self._api(text_error=AxisAuthenticationError("401"))

        with pytest.raises(AxisAuthenticationError):
            await api.get_logs(LogType.SYSTEM)
        api.get_log_files.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_all_logs_use_only_the_tarball(self):
        api = self._api()

        report = await api.get_logs(LogType.ALL)

        api._get_text.assert_not_awaited()
        api.get_log_files.assert_awaited_once()
        assert report.source == LogsAPI.TARBALL_SOURCE

    @pytest.mark.asyncio
    async def test_stream_logs_uses_the_dedicated_cgi(self):
        api = self._api(text="\n".join([self.SYSLOG, "    continuation"]))

        entries = [entry async for entry in api.stream_logs(LogType.SYSTEM)]

        api._get_text.assert_awaited_once_with("/axis-cgi/systemlog.cgi", None)
        assert len(entries) == 2
        assert entries[1].timestamp == entries[0].timestamp  # continuation inherits

    @pytest.mark.asyncio
    async def test_search_uses_the_dedicated_cgi(self):
        api = self._api(
            text="\n".join([self.SYSLOG, self.SYSLOG.replace("Message 1", "auth failed")])
        )

        report = await api.search_logs("AUTH", LogType.SYSTEM)

        assert len(report.entries) == 1 and "auth failed" in report.entries[0].raw
        assert report.source == "systemlog.cgi"


class TestServerReportEcho:
    """The server-report fallback decodes a binary download: it is checked once decoded."""

    PASSWORD = "Logs-Echo~T3st?"  # pragma: allowlist secret

    @respx.mock
    async def test_a_server_report_that_quotes_the_credentials_is_refused(self):
        token = base64.b64encode(f"root:{self.PASSWORD}".encode()).decode()
        respx.get("https://192.0.2.10:443/axis-cgi/serverreport.cgi").mock(
            return_value=httpx.Response(
                200,
                content=f"2026-10-15 kernel: authorization: Basic {token}\n".encode(),
                headers={"Content-Type": "application/octet-stream"},  # not scanned as text
            )
        )
        async with VapixClient(
            "192.0.2.10", "root", self.PASSWORD, port=443, use_https=True, auth_mode="basic"
        ) as client:
            with pytest.raises(AxisEchoError):
                await LogsAPI(client).get_log_files()


class TestServerReportDigestEcho:
    """The decoded tarball is checked against what the request sent, Digest included."""

    PASSWORD = "Logs-Digest~T3st?"  # pragma: allowlist secret
    CHALLENGE = 'Digest realm="probe", nonce="abc123", algorithm=MD5, qop="auth"'

    @respx.mock
    async def test_a_digest_server_report_that_quotes_the_request_is_refused(self):
        import io
        import tarfile

        def device(request: httpx.Request) -> httpx.Response:
            authorization = request.headers.get("Authorization", "")
            if not authorization.startswith("Digest "):
                return httpx.Response(401, headers={"WWW-Authenticate": self.CHALLENGE})
            payload = f"2026-10-15 httpd: authorization: {authorization}\n".encode()
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode="w") as tar:
                info = tarfile.TarInfo("var/log/messages")
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
            return httpx.Response(
                200,
                content=archive.getvalue(),
                headers={"Content-Type": "application/octet-stream"},  # not scanned as text
            )

        respx.get("http://192.0.2.10:80/axis-cgi/serverreport.cgi").mock(side_effect=device)
        async with VapixClient("192.0.2.10", "root", self.PASSWORD, auth_mode="digest") as client:
            with pytest.raises(AxisEchoError):
                await LogsAPI(client).get_log_files()
