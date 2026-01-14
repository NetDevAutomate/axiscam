"""Parameter API module.

This module provides access to device parameters via the VAPIX param API.
Parameters are organized in groups and control various device settings.

API Endpoints:
    - /config/rest/param/v2beta (REST API)
    - /axis-cgi/param.cgi (Legacy CGI)

Parameters are read-only in this implementation for safety. Write operations
would require explicit confirmation due to potential device impact.
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import DeviceParameter, ParameterGroup


class ParamAPI(BaseAPI):
    """API module for reading device parameters.

    Device parameters control various settings organized in groups like:
    - Audio: Audio settings
    - Image: Image/video settings
    - Network: Network configuration
    - PTZ: Pan-tilt-zoom settings
    - System: System configuration

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     # Get all parameters
        ...     params = await camera.params.get_all()
        ...     for group in params:
        ...         print(f"Group: {group.name}")
        ...
        ...     # Get specific parameter
        ...     value = await camera.params.get("root.Network.eth0.IPAddress")
        ...     print(f"IP Address: {value}")
    """

    # Legacy CGI endpoint
    CGI_PATH = "/axis-cgi/param.cgi"

    # REST API endpoint (AXIS OS 11.x+)
    REST_PATH = "/config/rest/param/v2beta"

    async def get(self, param_name: str) -> str | None:
        """Get a single parameter value.

        Args:
            param_name: Full parameter name (e.g., "root.Network.eth0.IPAddress").

        Returns:
            Parameter value as string, or None if not found.

        Example:
            >>> value = await camera.params.get("root.Properties.FriendlyName")
            >>> print(f"Device name: {value}")
        """
        # Use legacy CGI for single parameter lookup
        params = {"action": "list", "group": param_name}

        try:
            response = await self._get(self.CGI_PATH, params)
            return self._extract_param_value(response, param_name)
        except Exception:
            return None

    async def get_group(self, group_name: str) -> ParameterGroup:
        """Get all parameters in a group.

        Args:
            group_name: Group name (e.g., "root.Network" or "Network").

        Returns:
            ParameterGroup with all parameters in the group.

        Example:
            >>> network_params = await camera.params.get_group("Network")
            >>> for param in network_params.parameters:
            ...     print(f"{param.name}: {param.value}")
        """
        # Normalize group name
        if not group_name.startswith("root."):
            group_name = f"root.{group_name}"

        params = {"action": "list", "group": group_name}

        try:
            response = await self._get(self.CGI_PATH, params)
            return self._parse_group_response(group_name, response)
        except Exception:
            return ParameterGroup(name=group_name.replace("root.", ""))

    async def get_all(self) -> list[ParameterGroup]:
        """Get all device parameters organized by group.

        Returns:
            List of ParameterGroup objects containing all parameters.

        Warning:
            This can return a large amount of data on complex devices.
        """
        params = {"action": "list"}

        try:
            response = await self._get(self.CGI_PATH, params)
            return self._parse_all_params(response)
        except Exception:
            return []

    async def get_many(self, param_names: list[str]) -> dict[str, str | None]:
        """Get multiple parameter values.

        Args:
            param_names: List of parameter names to retrieve.

        Returns:
            Dictionary mapping parameter names to values.

        Example:
            >>> values = await camera.params.get_many([
            ...     "root.Properties.FriendlyName",
            ...     "root.Network.eth0.IPAddress",
            ... ])
            >>> print(values)
        """
        results: dict[str, str | None] = {}

        for name in param_names:
            results[name] = await self.get(name)

        return results

    async def search(self, pattern: str) -> list[DeviceParameter]:
        """Search parameters by name pattern.

        Args:
            pattern: Search pattern (case-insensitive substring match).

        Returns:
            List of matching DeviceParameter objects.

        Example:
            >>> network_params = await camera.params.search("Network")
            >>> print(f"Found {len(network_params)} network parameters")
        """
        all_params = await self.get_all()
        pattern_lower = pattern.lower()
        results: list[DeviceParameter] = []

        for group in all_params:
            for param in group.parameters:
                if pattern_lower in param.name.lower():
                    results.append(param)

        return results

    async def export(self) -> dict[str, Any]:
        """Export all writable parameters.

        Uses the REST API export endpoint to get all parameters
        that can be imported on another device.

        Returns:
            Dictionary of exportable parameters.
        """
        try:
            response = await self._get(f"{self.REST_PATH}/$export")
            return response.get("data", {})
        except Exception:
            # Fall back to getting all params
            params = await self.get_all()
            return {group.name: {p.name: p.value for p in group.parameters} for group in params}

    def _extract_param_value(self, response: dict[str, Any], param_name: str) -> str | None:
        """Extract a single parameter value from response.

        Args:
            response: Raw API response.
            param_name: Parameter name to extract.

        Returns:
            Parameter value or None.
        """
        # The response format varies - handle different structures
        if isinstance(response, dict):
            # Check for direct value
            parts = param_name.split(".")
            current = response

            for part in parts:
                if isinstance(current, dict):
                    current = current.get(part)
                else:
                    return None

            if isinstance(current, str):
                return current

        return None

    def _parse_group_response(self, group_name: str, response: dict[str, Any]) -> ParameterGroup:
        """Parse group response into ParameterGroup model.

        Args:
            group_name: Name of the parameter group.
            response: Raw API response.

        Returns:
            ParameterGroup with parsed parameters.
        """
        parameters: list[DeviceParameter] = []
        clean_name = group_name.replace("root.", "")

        self._extract_params_recursive(response, "", parameters)

        return ParameterGroup(name=clean_name, parameters=parameters)

    def _parse_all_params(self, response: dict[str, Any]) -> list[ParameterGroup]:
        """Parse response containing all parameters.

        Args:
            response: Raw API response.

        Returns:
            List of ParameterGroup objects.
        """
        groups: dict[str, list[DeviceParameter]] = {}
        parameters: list[DeviceParameter] = []

        self._extract_params_recursive(response, "root", parameters)

        # Organize parameters by top-level group
        for param in parameters:
            parts = param.name.split(".")
            group_name = parts[1] if len(parts) >= 2 else "Other"

            if group_name not in groups:
                groups[group_name] = []
            groups[group_name].append(param)

        return [
            ParameterGroup(name=name, parameters=params) for name, params in sorted(groups.items())
        ]

    def _extract_params_recursive(
        self,
        data: Any,
        prefix: str,
        results: list[DeviceParameter],
    ) -> None:
        """Recursively extract parameters from nested response.

        Args:
            data: Current data level.
            prefix: Current parameter name prefix.
            results: List to append found parameters.
        """
        if isinstance(data, dict):
            for key, value in data.items():
                new_prefix = f"{prefix}.{key}" if prefix else key
                self._extract_params_recursive(value, new_prefix, results)
        elif isinstance(data, str) and prefix:
            results.append(
                DeviceParameter(
                    name=prefix,
                    value=data,
                    group=prefix.split(".")[1] if "." in prefix else "",
                )
            )

    # Convenience methods for common parameters

    async def get_friendly_name(self) -> str:
        """Get the device's friendly name.

        Returns:
            User-assigned device name or empty string.
        """
        return await self.get("root.Properties.FriendlyName") or ""

    async def get_location(self) -> str:
        """Get the device's location description.

        Returns:
            Device location or empty string.
        """
        return await self.get("root.Properties.Location") or ""

    async def get_ip_address(self) -> str:
        """Get the device's primary IP address from parameters.

        Returns:
            IP address string or empty string.
        """
        # Try IPv4 first
        ip = await self.get("root.Network.eth0.IPAddress")
        if ip:
            return ip

        # Try alternative parameter names
        for param_name in [
            "root.Network.VolatileHostName.IPv4Address",
            "root.Network.IPv4.Address",
        ]:
            ip = await self.get(param_name)
            if ip:
                return ip

        return ""

    async def get_mac_address(self) -> str:
        """Get the device's MAC address.

        Returns:
            MAC address string or empty string.
        """
        return await self.get("root.Network.eth0.MACAddress") or ""
