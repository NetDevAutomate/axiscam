"""Custom exceptions for AXIS Camera Manager.

This module defines the exception hierarchy for the axis_cam package.
All custom exceptions inherit from AxisError to allow for broad
exception handling when needed.

Exception Hierarchy:
    AxisError (base)
    ├── AxisConnectionError - Network/connectivity issues
    ├── AxisAuthenticationError - Authentication failures
    ├── AxisDeviceError - Device-specific errors
    └── AxisConfigError - Configuration issues
"""


class AxisError(Exception):
    """Base exception for all AXIS-related errors.

    All custom exceptions in this package inherit from AxisError,
    allowing callers to catch all AXIS errors with a single handler.

    Example:
        >>> try:
        ...     await device.get_info()
        ... except AxisError as e:
        ...     print(f"AXIS error: {e}")
    """

    pass


class AxisConnectionError(AxisError):
    """Raised when connection to device fails.

    This includes network unreachable, connection refused,
    timeouts, and DNS resolution failures.

    Example:
        >>> try:
        ...     await device.connect()
        ... except AxisConnectionError as e:
        ...     print(f"Cannot reach device: {e}")
    """

    pass


class AxisAuthenticationError(AxisError):
    """Raised when authentication fails.

    This includes invalid credentials (401), insufficient
    permissions (403), and expired credentials.

    Example:
        >>> try:
        ...     await device.get_info()
        ... except AxisAuthenticationError as e:
        ...     print(f"Auth failed: {e}")
    """

    pass


class AxisDeviceError(AxisError):
    """Raised when device returns an error.

    This includes HTTP 4xx/5xx errors (except auth),
    invalid API responses, and device-side failures.

    Example:
        >>> try:
        ...     await device.reboot()
        ... except AxisDeviceError as e:
        ...     print(f"Device error: {e}")
    """

    pass


class AxisConfigError(AxisError):
    """Raised when configuration is invalid.

    This includes missing config files, invalid YAML,
    missing required fields, and validation errors.

    Example:
        >>> try:
        ...     config = load_config()
        ... except AxisConfigError as e:
        ...     print(f"Config error: {e}")
    """

    pass


class AxisApiNotSupportedError(AxisError):
    """Raised when a requested API is not supported by the device.

    Some APIs are only available on certain device types or
    firmware versions. This exception indicates the requested
    functionality is not available.

    Example:
        >>> try:
        ...     await camera.ptz.move()
        ... except AxisApiNotSupportedError as e:
        ...     print(f"PTZ not supported: {e}")
    """

    pass
