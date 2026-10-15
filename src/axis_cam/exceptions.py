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


class AxisEchoError(AxisConnectionError):
    """A reply quoted the credentials its request sent: the device did not answer as sent.

    No Axis device echoes request headers, so such a reply comes from a proxy,
    WAF, captive portal or hostile peer that echoes requests. It is a
    connection-class error on purpose: the module methods that turn an
    ``AxisDeviceError`` into "this API is absent" must not swallow it, and the
    audit, the fleet runner and the MCP tools treat the device as unusable
    through this path. The message never quotes the reply.
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


class AxisPermissionError(AxisAuthenticationError):
    """Raised when the device answers 403: this account may not use this API.

    Distinct from a 401 (credentials rejected): the session is authenticated
    but a specific API refuses the account. Seen on AXIS OS 12.11, where an
    administrator still gets 403 on ``/config/rest/oauth-ccgrant``. Report and
    backup record it per module and carry on; a 401 aborts the run.
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


class AxisSoapFault(AxisDeviceError):
    """A SOAP service answered with a ``Fault`` (HTTP 400 or 500 on Axis devices).

    Attributes:
        code: ``Code/Value`` (``env:Sender`` or ``env:Receiver``).
        subcodes: Nested ``Subcode/Value`` entries, outermost first
            (``["ter:InvalidArgVal", "ter:UsernameMissing"]``).
        reason: ``Reason/Text`` as the device wrote it.
    """

    def __init__(self, message: str, *, code: str, subcodes: list[str], reason: str) -> None:
        super().__init__(message)
        self.code = code
        self.subcodes = subcodes
        self.reason = reason


class AxisUserError(AxisDeviceError):
    """Raised when the device rejects an account operation.

    ``pwdgrp.cgi`` reports failures with HTTP 200 and a body starting
    ``Error:`` (invalid password, bad user name, unknown action), so the
    HTTP layer cannot see them; the users module raises this instead.

    Example:
        >>> try:
        ...     await camera.users.add("joe", "weak", UserRole.VIEWER)
        ... except AxisUserError as e:
        ...     print(f"Device refused: {e}")
    """

    pass


class AxisLockoutError(AxisConfigError):
    """Raised when an account change would lock the caller out of the device.

    Removing or de-admining the account the client is authenticated as, or
    removing the last administrator, is refused unless the caller passes
    ``allow_lockout=True`` explicitly.
    """

    pass
