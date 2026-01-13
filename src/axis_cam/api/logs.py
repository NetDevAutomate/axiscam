"""Logs API module.

This module provides access to device logs via the VAPIX log API
and the server report CGI endpoint.

API Endpoints:
    - /config/rest/log/v1beta (REST API)
    - /axis-cgi/serverreport.cgi (Legacy CGI for full reports)

The module supports retrieving system logs, parsing log entries,
and streaming log content.
"""

import io
import re
import tarfile
from collections.abc import AsyncIterator
from datetime import datetime
from enum import Enum
from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import LogEntry, LogLevel, LogReport, LogType


class ServerReportMode(str, Enum):
    """Server report output modes."""

    TEXT = "text"
    TAR_ALL = "tar_all"
    ZIP = "zip"
    ZIP_WITH_IMAGE = "zip_with_image"


# Log file patterns in the server report tarball
LOG_FILE_PATTERNS = {
    LogType.SYSTEM: ["syslog", "messages", "kern.log"],
    LogType.ACCESS: ["access.log", "httpd/access"],
    LogType.AUDIT: ["audit.log", "audit/audit"],
}

# Regex pattern for parsing AXIS syslog format
SYSLOG_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2})?)\s+"
    r"(?P<hostname>\S+)\s+"
    r"\[\s*(?P<level>\w+)\s*\]\s+"
    r"(?:(?P<process>[\w\-]+)(?:\[(?P<pid>\d+)\])?:\s*)?"
    r"(?P<message>.*)$"
)

# Alternative pattern for simpler log formats
SIMPLE_LOG_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"(?P<message>.*)$"
)


def parse_log_line(line: str) -> LogEntry | None:
    """Parse a single log line into a LogEntry.

    Args:
        line: Raw log line string.

    Returns:
        LogEntry if parsing successful, None otherwise.
    """
    line = line.strip()
    if not line:
        return None

    # Try AXIS syslog format first
    match = SYSLOG_PATTERN.match(line)
    if match:
        groups = match.groupdict()
        try:
            timestamp = datetime.fromisoformat(groups["timestamp"])
        except ValueError:
            timestamp = datetime.now()

        return LogEntry(
            timestamp=timestamp,
            hostname=groups["hostname"],
            level=groups["level"],
            process=groups.get("process") or "",
            pid=int(groups["pid"]) if groups.get("pid") else None,
            message=groups["message"],
            raw=line,
        )

    # Try simple format
    match = SIMPLE_LOG_PATTERN.match(line)
    if match:
        groups = match.groupdict()
        try:
            timestamp = datetime.strptime(groups["timestamp"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            timestamp = datetime.now()

        return LogEntry(
            timestamp=timestamp,
            hostname="unknown",
            level=LogLevel.INFO,
            message=groups["message"],
            raw=line,
        )

    # Return as unparsed entry
    return LogEntry(
        timestamp=datetime.now(),
        hostname="unknown",
        level=LogLevel.INFO,
        message=line,
        raw=line,
    )


def parse_log_content(content: str, log_type: LogType = LogType.SYSTEM) -> list[LogEntry]:
    """Parse log content into a list of LogEntry objects.

    Args:
        content: Raw log content string.
        log_type: Type of log being parsed.

    Returns:
        List of parsed LogEntry objects.
    """
    entries: list[LogEntry] = []
    for line in content.splitlines():
        entry = parse_log_line(line)
        if entry:
            entries.append(entry)
    return entries


class LogsAPI(BaseAPI):
    """API module for retrieving device logs.

    This module provides methods to retrieve various log types:
    - System logs (syslog)
    - Access logs (HTTP access)
    - Audit logs (security events)

    The module uses the server report CGI for comprehensive log retrieval.

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     # Get system logs
        ...     logs = await camera.logs.get_system_logs(max_entries=100)
        ...     for entry in logs.entries[:5]:
        ...         print(f"{entry.timestamp}: {entry.message}")
        ...
        ...     # Stream logs
        ...     async for entry in camera.logs.stream_logs():
        ...         print(entry.message)
    """

    # Server report CGI endpoint
    CGI_PATH = "/axis-cgi/serverreport.cgi"

    # REST API endpoint (AXIS OS 11.x+)
    REST_PATH = "/config/rest/log/v1beta"

    def __init__(self, client: Any, device_name: str = "unknown") -> None:
        """Initialize the logs API.

        Args:
            client: VapixClient instance.
            device_name: Device name for report metadata.
        """
        super().__init__(client)
        self._device_name = device_name

    async def get_server_report(
        self,
        mode: ServerReportMode = ServerReportMode.TEXT,
    ) -> bytes:
        """Get the server report from the device.

        Args:
            mode: Output format for the report.

        Returns:
            Raw server report content.
        """
        params = {}
        if mode != ServerReportMode.TEXT:
            params["mode"] = mode.value

        return await self._get_raw(self.CGI_PATH, params)

    async def get_log_files(self) -> dict[str, str]:
        """Get all log files from the server report tarball.

        Returns:
            Dictionary mapping log file names to their content.
        """
        content = await self.get_server_report(ServerReportMode.TAR_ALL)

        log_files: dict[str, str] = {}

        try:
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:*") as tar:
                for member in tar.getmembers():
                    if member.isfile():
                        file_obj = tar.extractfile(member)
                        if file_obj:
                            try:
                                file_content = file_obj.read().decode(
                                    "utf-8", errors="replace"
                                )
                                log_files[member.name] = file_content
                            except Exception:
                                pass
        except tarfile.TarError:
            # If not a valid tar, try to parse as plain text
            log_files["serverreport.txt"] = content.decode("utf-8", errors="replace")

        return log_files

    def _find_log_content(
        self,
        log_files: dict[str, str],
        log_type: LogType,
    ) -> str:
        """Find log content for a specific log type.

        Args:
            log_files: Dictionary of log file names to content.
            log_type: Type of log to find.

        Returns:
            Combined log content for the requested type.
        """
        if log_type == LogType.ALL:
            return "\n".join(log_files.values())

        patterns = LOG_FILE_PATTERNS.get(log_type, [])
        matching_content: list[str] = []

        for filename, content in log_files.items():
            filename_lower = filename.lower()
            for pattern in patterns:
                if pattern.lower() in filename_lower:
                    matching_content.append(content)
                    break

        return "\n".join(matching_content)

    async def get_logs(
        self,
        log_type: LogType = LogType.SYSTEM,
        max_entries: int | None = None,
    ) -> LogReport:
        """Get logs from the device.

        Args:
            log_type: Type of logs to retrieve.
            max_entries: Maximum number of entries to return.

        Returns:
            LogReport containing parsed log entries.
        """
        log_files = await self.get_log_files()
        content = self._find_log_content(log_files, log_type)
        entries = parse_log_content(content, log_type)

        # Sort by timestamp, newest first
        entries.sort(key=lambda e: e.timestamp, reverse=True)

        if max_entries:
            entries = entries[:max_entries]

        return LogReport(
            device_name=self._device_name,
            device_address=self._client.host,
            log_type=log_type,
            entries=entries,
        )

    async def get_system_logs(self, max_entries: int | None = None) -> LogReport:
        """Get system logs from the device.

        Args:
            max_entries: Maximum number of entries to return.

        Returns:
            LogReport containing system log entries.
        """
        return await self.get_logs(LogType.SYSTEM, max_entries)

    async def get_access_logs(self, max_entries: int | None = None) -> LogReport:
        """Get access/request logs from the device.

        Args:
            max_entries: Maximum number of entries to return.

        Returns:
            LogReport containing access log entries.
        """
        return await self.get_logs(LogType.ACCESS, max_entries)

    async def get_audit_logs(self, max_entries: int | None = None) -> LogReport:
        """Get audit logs from the device.

        Args:
            max_entries: Maximum number of entries to return.

        Returns:
            LogReport containing audit log entries.
        """
        return await self.get_logs(LogType.AUDIT, max_entries)

    async def get_all_logs(self, max_entries: int | None = None) -> LogReport:
        """Get all logs from the device.

        Args:
            max_entries: Maximum number of entries to return.

        Returns:
            LogReport containing all log entries.
        """
        return await self.get_logs(LogType.ALL, max_entries)

    async def stream_logs(
        self,
        log_type: LogType = LogType.SYSTEM,
    ) -> AsyncIterator[LogEntry]:
        """Stream log entries as they are parsed.

        Args:
            log_type: Type of logs to retrieve.

        Yields:
            LogEntry objects as they are parsed.
        """
        log_files = await self.get_log_files()
        content = self._find_log_content(log_files, log_type)

        for line in content.splitlines():
            entry = parse_log_line(line)
            if entry:
                yield entry

    async def get_persistent_logging_enabled(self) -> bool:
        """Check if persistent logging is enabled.

        Returns:
            True if persistent logging is enabled.
        """
        try:
            response = await self._get(f"{self.REST_PATH}/persistent/enabled")
            return response.get("data", {}).get("enabled", False)
        except Exception:
            return False

    async def search_logs(
        self,
        pattern: str,
        log_type: LogType = LogType.SYSTEM,
        max_entries: int | None = None,
    ) -> LogReport:
        """Search logs for entries matching a pattern.

        Args:
            pattern: Search pattern (case-insensitive substring).
            log_type: Type of logs to search.
            max_entries: Maximum number of matching entries.

        Returns:
            LogReport with matching entries.
        """
        logs = await self.get_logs(log_type, max_entries=None)
        pattern_lower = pattern.lower()

        matching = [
            entry
            for entry in logs.entries
            if pattern_lower in entry.message.lower()
            or pattern_lower in entry.raw.lower()
        ]

        if max_entries:
            matching = matching[:max_entries]

        return LogReport(
            device_name=logs.device_name,
            device_address=logs.device_address,
            log_type=log_type,
            entries=matching,
        )

    async def get_log_summary(
        self,
        log_type: LogType = LogType.SYSTEM,
    ) -> dict[str, int]:
        """Get summary of log entries by level.

        Args:
            log_type: Type of logs to summarize.

        Returns:
            Dictionary mapping log levels to entry counts.
        """
        logs = await self.get_logs(log_type, max_entries=None)

        summary: dict[str, int] = {}
        for entry in logs.entries:
            level = entry.level.value
            summary[level] = summary.get(level, 0) + 1

        return summary
