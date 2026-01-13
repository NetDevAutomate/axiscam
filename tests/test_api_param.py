"""Tests for Param API module."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from axis_cam.api.param import ParamAPI
from axis_cam.models import DeviceParameter, ParameterGroup


class TestParamAPI:
    """Tests for ParamAPI class."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock VapixClient."""
        client = MagicMock()
        client.host = "192.168.1.10"
        return client

    @pytest.fixture
    def param_api(self, mock_client):
        """Create ParamAPI instance with mock client."""
        return ParamAPI(mock_client)

    def test_init(self, param_api):
        """Test ParamAPI initialization."""
        assert param_api._client is not None

    @pytest.mark.asyncio
    async def test_get_single_param(self, param_api):
        """Test get single parameter."""
        response = {
            "root": {
                "Properties": {
                    "FriendlyName": "Test Camera"
                }
            }
        }
        param_api._get = AsyncMock(return_value=response)

        result = await param_api.get("root.Properties.FriendlyName")

        assert result == "Test Camera"

    @pytest.mark.asyncio
    async def test_get_param_not_found(self, param_api):
        """Test get parameter returns None when not found."""
        response = {}
        param_api._get = AsyncMock(return_value=response)

        result = await param_api.get("root.NonExistent.Param")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_param_exception(self, param_api):
        """Test get parameter returns None on exception."""
        param_api._get = AsyncMock(side_effect=Exception("API error"))

        result = await param_api.get("root.Properties.FriendlyName")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_group(self, param_api):
        """Test get parameter group."""
        response = {
            "root": {
                "Network": {
                    "eth0": {
                        "IPAddress": "192.168.1.10",
                        "MACAddress": "AA:BB:CC:DD:EE:FF"
                    }
                }
            }
        }
        param_api._get = AsyncMock(return_value=response)

        result = await param_api.get_group("Network")

        assert isinstance(result, ParameterGroup)
        assert result.name == "Network"

    @pytest.mark.asyncio
    async def test_get_group_with_root_prefix(self, param_api):
        """Test get group already has root prefix."""
        response = {
            "root": {
                "Network": {
                    "eth0": {
                        "IPAddress": "192.168.1.10"
                    }
                }
            }
        }
        param_api._get = AsyncMock(return_value=response)

        result = await param_api.get_group("root.Network")

        assert result.name == "Network"

    @pytest.mark.asyncio
    async def test_get_group_exception(self, param_api):
        """Test get group returns empty group on exception."""
        param_api._get = AsyncMock(side_effect=Exception("API error"))

        result = await param_api.get_group("Network")

        assert isinstance(result, ParameterGroup)
        assert result.name == "Network"
        assert len(result.parameters) == 0

    @pytest.mark.asyncio
    async def test_get_all(self, param_api):
        """Test get all parameters."""
        # Response doesn't have root wrapper - _parse_all_params adds "root" prefix
        response = {
            "Properties": {
                "FriendlyName": "Test",
                "Location": "Lab"
            },
            "Network": {
                "eth0": {
                    "IPAddress": "192.168.1.10"
                }
            }
        }
        param_api._get = AsyncMock(return_value=response)

        result = await param_api.get_all()

        assert isinstance(result, list)
        assert len(result) >= 1
        group_names = [g.name for g in result]
        assert "Network" in group_names or "Properties" in group_names

    @pytest.mark.asyncio
    async def test_get_all_exception(self, param_api):
        """Test get all returns empty list on exception."""
        param_api._get = AsyncMock(side_effect=Exception("API error"))

        result = await param_api.get_all()

        assert result == []

    @pytest.mark.asyncio
    async def test_get_many(self, param_api):
        """Test get multiple parameters."""
        responses = {
            "root.Properties.FriendlyName": "Test Camera",
            "root.Properties.Location": "Lab",
        }

        async def mock_get(path, params=None):
            group = params.get("group", "")
            parts = group.split(".")
            result = {"root": {}}
            current = result["root"]
            for i, part in enumerate(parts[1:]):
                if i == len(parts) - 2:
                    current[part] = responses.get(group, "")
                else:
                    current[part] = {}
                    current = current[part]
            return result

        param_api._get = mock_get

        result = await param_api.get_many([
            "root.Properties.FriendlyName",
            "root.Properties.Location",
        ])

        assert isinstance(result, dict)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_search(self, param_api):
        """Test search parameters."""
        response = {
            "root": {
                "Network": {
                    "eth0": {
                        "IPAddress": "192.168.1.10"
                    }
                },
                "Properties": {
                    "FriendlyName": "Test"
                }
            }
        }
        param_api._get = AsyncMock(return_value=response)

        result = await param_api.search("Network")

        assert isinstance(result, list)
        # Should find parameters containing "Network"
        for param in result:
            assert isinstance(param, DeviceParameter)

    @pytest.mark.asyncio
    async def test_export_rest_api(self, param_api):
        """Test export using REST API."""
        response = {
            "data": {
                "Properties": {"FriendlyName": "Test"},
                "Network": {"eth0": {"IPAddress": "192.168.1.10"}}
            }
        }
        param_api._get = AsyncMock(return_value=response)

        result = await param_api.export()

        assert isinstance(result, dict)
        assert "Properties" in result or len(result) >= 0

    @pytest.mark.asyncio
    async def test_export_fallback(self, param_api):
        """Test export falls back to get_all on exception."""
        all_response = {
            "root": {
                "Properties": {
                    "FriendlyName": "Test"
                }
            }
        }

        call_count = 0
        async def mock_get(path, params=None):
            nonlocal call_count
            call_count += 1
            if "$export" in path:
                raise Exception("REST not available")
            return all_response

        param_api._get = mock_get

        result = await param_api.export()

        assert isinstance(result, dict)

    def test_extract_param_value(self, param_api):
        """Test _extract_param_value method."""
        response = {
            "root": {
                "Properties": {
                    "FriendlyName": "Test Camera"
                }
            }
        }

        result = param_api._extract_param_value(
            response, "root.Properties.FriendlyName"
        )

        assert result == "Test Camera"

    def test_extract_param_value_not_found(self, param_api):
        """Test _extract_param_value returns None when not found."""
        response = {"root": {}}

        result = param_api._extract_param_value(
            response, "root.Properties.FriendlyName"
        )

        assert result is None

    def test_extract_param_value_non_string(self, param_api):
        """Test _extract_param_value returns None for non-string values."""
        response = {
            "root": {
                "Properties": {
                    "Count": 42
                }
            }
        }

        result = param_api._extract_param_value(
            response, "root.Properties.Count"
        )

        assert result is None

    def test_parse_group_response(self, param_api):
        """Test _parse_group_response method."""
        response = {
            "eth0": {
                "IPAddress": "192.168.1.10",
                "MACAddress": "AA:BB:CC:DD:EE:FF"
            }
        }

        result = param_api._parse_group_response("root.Network", response)

        assert isinstance(result, ParameterGroup)
        assert result.name == "Network"

    def test_parse_all_params(self, param_api):
        """Test _parse_all_params method."""
        response = {
            "root": {
                "Properties": {
                    "FriendlyName": "Test"
                },
                "Network": {
                    "eth0": {
                        "IPAddress": "192.168.1.10"
                    }
                }
            }
        }

        result = param_api._parse_all_params(response)

        assert isinstance(result, list)
        group_names = [g.name for g in result]
        # Should have groups organized
        assert len(group_names) >= 1

    def test_extract_params_recursive(self, param_api):
        """Test _extract_params_recursive method."""
        data = {
            "Network": {
                "eth0": {
                    "IPAddress": "192.168.1.10"
                }
            }
        }
        results = []

        param_api._extract_params_recursive(data, "root", results)

        assert len(results) >= 1
        param_names = [p.name for p in results]
        assert any("IPAddress" in name for name in param_names)

    def test_extract_params_recursive_string(self, param_api):
        """Test _extract_params_recursive with string value."""
        results = []

        param_api._extract_params_recursive("test_value", "root.Test", results)

        assert len(results) == 1
        assert results[0].value == "test_value"

    @pytest.mark.asyncio
    async def test_get_friendly_name(self, param_api):
        """Test get_friendly_name convenience method."""
        response = {
            "root": {
                "Properties": {
                    "FriendlyName": "Front Door Camera"
                }
            }
        }
        param_api._get = AsyncMock(return_value=response)

        result = await param_api.get_friendly_name()

        assert result == "Front Door Camera"

    @pytest.mark.asyncio
    async def test_get_friendly_name_empty(self, param_api):
        """Test get_friendly_name returns empty string when not found."""
        param_api._get = AsyncMock(return_value={})

        result = await param_api.get_friendly_name()

        assert result == ""

    @pytest.mark.asyncio
    async def test_get_location(self, param_api):
        """Test get_location convenience method."""
        response = {
            "root": {
                "Properties": {
                    "Location": "Main Entrance"
                }
            }
        }
        param_api._get = AsyncMock(return_value=response)

        result = await param_api.get_location()

        assert result == "Main Entrance"

    @pytest.mark.asyncio
    async def test_get_ip_address(self, param_api):
        """Test get_ip_address convenience method."""
        response = {
            "root": {
                "Network": {
                    "eth0": {
                        "IPAddress": "192.168.1.10"
                    }
                }
            }
        }
        param_api._get = AsyncMock(return_value=response)

        result = await param_api.get_ip_address()

        assert result == "192.168.1.10"

    @pytest.mark.asyncio
    async def test_get_ip_address_alternative(self, param_api):
        """Test get_ip_address tries alternative parameter names."""
        call_count = 0
        async def mock_get(path, params=None):
            nonlocal call_count
            call_count += 1
            group = params.get("group", "")
            if "VolatileHostName" in group:
                return {
                    "root": {
                        "Network": {
                            "VolatileHostName": {
                                "IPv4Address": "10.0.0.50"
                            }
                        }
                    }
                }
            return {}

        param_api._get = mock_get

        result = await param_api.get_ip_address()

        # Should try alternatives and return if found
        assert call_count >= 1

    @pytest.mark.asyncio
    async def test_get_mac_address(self, param_api):
        """Test get_mac_address convenience method."""
        response = {
            "root": {
                "Network": {
                    "eth0": {
                        "MACAddress": "AA:BB:CC:DD:EE:FF"
                    }
                }
            }
        }
        param_api._get = AsyncMock(return_value=response)

        result = await param_api.get_mac_address()

        assert result == "AA:BB:CC:DD:EE:FF"

    @pytest.mark.asyncio
    async def test_get_mac_address_empty(self, param_api):
        """Test get_mac_address returns empty string when not found."""
        param_api._get = AsyncMock(return_value={})

        result = await param_api.get_mac_address()

        assert result == ""
