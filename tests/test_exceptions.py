"""Tests for custom exceptions."""

import pytest

from axis_cam.exceptions import (
    AxisApiNotSupportedError,
    AxisAuthenticationError,
    AxisConfigError,
    AxisConnectionError,
    AxisDeviceError,
    AxisError,
)


class TestAxisError:
    """Tests for base AxisError exception."""

    def test_is_exception(self):
        """Test that AxisError is an Exception."""
        assert issubclass(AxisError, Exception)

    def test_can_raise_and_catch(self):
        """Test raising and catching AxisError."""
        with pytest.raises(AxisError) as exc_info:
            raise AxisError("test error")
        assert str(exc_info.value) == "test error"

    def test_catches_all_axis_errors(self):
        """Test that AxisError catches all subclasses."""
        with pytest.raises(AxisError):
            raise AxisConnectionError("connection failed")

        with pytest.raises(AxisError):
            raise AxisAuthenticationError("auth failed")

        with pytest.raises(AxisError):
            raise AxisDeviceError("device error")

        with pytest.raises(AxisError):
            raise AxisConfigError("config error")


class TestAxisConnectionError:
    """Tests for AxisConnectionError exception."""

    def test_inheritance(self):
        """Test that AxisConnectionError inherits from AxisError."""
        assert issubclass(AxisConnectionError, AxisError)

    def test_can_raise(self):
        """Test raising AxisConnectionError."""
        with pytest.raises(AxisConnectionError) as exc_info:
            raise AxisConnectionError("Failed to connect to 192.168.1.10")
        assert "192.168.1.10" in str(exc_info.value)


class TestAxisAuthenticationError:
    """Tests for AxisAuthenticationError exception."""

    def test_inheritance(self):
        """Test that AxisAuthenticationError inherits from AxisError."""
        assert issubclass(AxisAuthenticationError, AxisError)

    def test_can_raise(self):
        """Test raising AxisAuthenticationError."""
        with pytest.raises(AxisAuthenticationError) as exc_info:
            raise AxisAuthenticationError("Invalid credentials")
        assert "Invalid credentials" in str(exc_info.value)


class TestAxisDeviceError:
    """Tests for AxisDeviceError exception."""

    def test_inheritance(self):
        """Test that AxisDeviceError inherits from AxisError."""
        assert issubclass(AxisDeviceError, AxisError)

    def test_can_raise(self):
        """Test raising AxisDeviceError."""
        with pytest.raises(AxisDeviceError) as exc_info:
            raise AxisDeviceError("Device returned error 500")
        assert "500" in str(exc_info.value)


class TestAxisConfigError:
    """Tests for AxisConfigError exception."""

    def test_inheritance(self):
        """Test that AxisConfigError inherits from AxisError."""
        assert issubclass(AxisConfigError, AxisError)

    def test_can_raise(self):
        """Test raising AxisConfigError."""
        with pytest.raises(AxisConfigError) as exc_info:
            raise AxisConfigError("Invalid YAML syntax")
        assert "YAML" in str(exc_info.value)


class TestAxisApiNotSupportedError:
    """Tests for AxisApiNotSupportedError exception."""

    def test_inheritance(self):
        """Test that AxisApiNotSupportedError inherits from AxisError."""
        assert issubclass(AxisApiNotSupportedError, AxisError)

    def test_can_raise(self):
        """Test raising AxisApiNotSupportedError."""
        with pytest.raises(AxisApiNotSupportedError) as exc_info:
            raise AxisApiNotSupportedError("PTZ API not available on this device")
        assert "PTZ" in str(exc_info.value)
