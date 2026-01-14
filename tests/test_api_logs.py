"""Tests for Logs API module."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from axis_cam.api.logs import (
    LOG_FILE_PATTERNS,
    LogsAPI,
    ServerReportMode,
    parse_log_content,
    parse_log_line,
)
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

        logs_api.get_log_files = AsyncMock(return_value={"syslog": log_content})

        result = await logs_api.get_logs(LogType.SYSTEM)

        assert result.device_name == "test-device"
        assert result.device_address == "192.168.1.10"
        assert result.log_type == LogType.SYSTEM
        assert len(result.entries) == 2

    @pytest.mark.asyncio
    async def test_get_logs_with_max_entries(self, logs_api, mock_client):
        """Test getting logs with max_entries limit."""
        log_content = """2024-01-15T12:00:00+00:00 axis-device [ INFO ] app: Message 1
2024-01-15T12:00:01+00:00 axis-device [ INFO ] app: Message 2
2024-01-15T12:00:02+00:00 axis-device [ INFO ] app: Message 3"""

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
        logs_api._get = AsyncMock(side_effect=Exception("API error"))

        result = await logs_api.get_persistent_logging_enabled()

        assert result is False
