"""Server Report API module.

This module provides functionality to download server reports from AXIS devices
via the VAPIX serverreport.cgi endpoint.

API Endpoints:
    - /axis-cgi/serverreport.cgi (CGI endpoint for server reports)

Report Modes:
    - zip_with_image: Full server report as ZIP with snapshot image
    - zip: Server report as ZIP without image
    - text: Plain text server report
"""

from pathlib import Path

from axis_cam.api.base import BaseAPI
from axis_cam.models import ServerReport, ServerReportFormat


class ServerReportAPI(BaseAPI):
    """API module for server report retrieval.

    This module provides methods to download server reports from AXIS devices:
    - Full diagnostic reports (ZIP with images)
    - Debug logs (debug.tgz)
    - Server configuration reports

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     # Download full server report
        ...     report = await camera.serverreport.download_report()
        ...     with open("report.zip", "wb") as f:
        ...         f.write(report.content)
        ...
        ...     # Save report to file
        ...     await camera.serverreport.save_report("/tmp/device_report.zip")
    """

    CGI_PATH = "/axis-cgi/serverreport.cgi"

    async def download_report(
        self,
        format: ServerReportFormat = ServerReportFormat.ZIP_WITH_IMAGE,
        timeout: float | None = None,
    ) -> ServerReport:
        """Download a server report from the device.

        Args:
            format: Report format (zip_with_image, zip, text).
            timeout: Optional custom timeout for download (default: 60s).

        Returns:
            ServerReport model with report content and metadata.
        """
        params = {"mode": format.value}

        # Server reports can take a while to generate
        effective_timeout = timeout or 60.0

        try:
            # Use the client's GET method to download binary content
            content = await self._client.get_binary(
                self.CGI_PATH,
                params=params,
                timeout=effective_timeout,
            )

            return ServerReport(
                content=content,
                format=format,
                size_bytes=len(content),
                filename=self._get_filename(format),
            )
        except Exception as e:
            # Return empty report with error
            return ServerReport(
                content=b"",
                format=format,
                size_bytes=0,
                filename="",
                error=str(e),
            )

    async def save_report(
        self,
        path: str | Path,
        format: ServerReportFormat = ServerReportFormat.ZIP_WITH_IMAGE,
        timeout: float | None = None,
    ) -> bool:
        """Download and save a server report to a file.

        Args:
            path: File path to save the report.
            format: Report format (zip_with_image, zip, text).
            timeout: Optional custom timeout for download.

        Returns:
            True if report was saved successfully, False otherwise.
        """
        report = await self.download_report(format=format, timeout=timeout)

        if report.error or not report.content:
            return False

        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("wb") as f:
            f.write(report.content)

        return True

    async def get_debug_archive(
        self,
        timeout: float | None = None,
    ) -> ServerReport:
        """Download the debug archive (debug.tgz) from the device.

        This retrieves a comprehensive debug archive that includes
        system logs, configuration, and diagnostic information.

        Args:
            timeout: Optional custom timeout for download (default: 120s).

        Returns:
            ServerReport model with debug archive content.
        """
        # Debug archives are served from a different endpoint
        debug_path = "/axis-cgi/debug/debug.tgz"
        effective_timeout = timeout or 120.0

        try:
            content = await self._client.get_binary(
                debug_path,
                timeout=effective_timeout,
            )

            return ServerReport(
                content=content,
                format=ServerReportFormat.DEBUG_TGZ,
                size_bytes=len(content),
                filename="debug.tgz",
            )
        except Exception as e:
            return ServerReport(
                content=b"",
                format=ServerReportFormat.DEBUG_TGZ,
                size_bytes=0,
                filename="debug.tgz",
                error=str(e),
            )

    async def save_debug_archive(
        self,
        path: str | Path,
        timeout: float | None = None,
    ) -> bool:
        """Download and save the debug archive to a file.

        Args:
            path: File path to save the debug archive.
            timeout: Optional custom timeout for download.

        Returns:
            True if archive was saved successfully, False otherwise.
        """
        report = await self.get_debug_archive(timeout=timeout)

        if report.error or not report.content:
            return False

        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("wb") as f:
            f.write(report.content)

        return True

    def _get_filename(self, format: ServerReportFormat) -> str:
        """Generate a filename for the given report format.

        Args:
            format: Report format.

        Returns:
            Suggested filename for the report.
        """
        if format == ServerReportFormat.ZIP_WITH_IMAGE or format == ServerReportFormat.ZIP:
            return "serverreport.zip"
        elif format == ServerReportFormat.TEXT:
            return "serverreport.txt"
        elif format == ServerReportFormat.DEBUG_TGZ:
            return "debug.tgz"
        else:
            return "serverreport"
