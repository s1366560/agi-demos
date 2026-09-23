"""Unit tests for SandboxMCPServerToolAdapter."""

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.mcp.sandbox_tool_adapter import SandboxMCPServerToolAdapter


@pytest.fixture
def managed_call(monkeypatch):
    call = AsyncMock()
    monkeypatch.setattr("src.infrastructure.mcp.sandbox_tool_adapter.agent_mcp_call", call)
    return call


@pytest.mark.unit
class TestSandboxMCPServerToolAdapter:
    """Tests for SandboxMCPServerToolAdapter."""

    def _make_adapter(self, **overrides):
        sandbox_adapter = overrides.get("sandbox_adapter", AsyncMock())
        sandbox_id = overrides.get("sandbox_id", "sandbox-1")
        server_name = overrides.get("server_name", "test-server")
        tool_info = overrides.get(
            "tool_info",
            {
                "name": "read_file",
                "description": "Read a file",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        )
        return SandboxMCPServerToolAdapter(
            sandbox_adapter=sandbox_adapter,
            sandbox_id=sandbox_id,
            server_name=server_name,
            tool_info=tool_info,
        )

    def test_name_generation(self):
        adapter = self._make_adapter()
        assert adapter.name == "mcp__test_server__read_file"

    def test_name_with_dashes(self):
        adapter = self._make_adapter(server_name="my-mcp-server")
        assert adapter.name == "mcp__my_mcp_server__read_file"

    def test_description(self):
        adapter = self._make_adapter()
        assert adapter.description == "Read a file"

    def test_description_fallback(self):
        adapter = self._make_adapter(tool_info={"name": "tool1", "description": ""})
        assert "tool1" in adapter.description
        assert "test-server" in adapter.description

    def test_parameters(self):
        adapter = self._make_adapter()
        assert adapter.parameters["type"] == "object"
        assert "path" in adapter.parameters["properties"]

    def test_get_parameters_schema_empty(self):
        adapter = self._make_adapter(tool_info={"name": "t", "description": "d"})
        schema = adapter.get_parameters_schema()
        assert schema["type"] == "object"
        assert schema["properties"] == {}
        assert schema["required"] == []

    def test_get_parameters_schema_fills_defaults(self):
        adapter = self._make_adapter(
            tool_info={
                "name": "t",
                "description": "d",
                "input_schema": {"properties": {"x": {"type": "string"}}},
            }
        )
        schema = adapter.get_parameters_schema()
        assert schema["type"] == "object"
        assert schema["required"] == []

    async def test_execute_success(self, managed_call):
        mock_adapter = AsyncMock()
        managed_call.return_value = {
            "content": [{"type": "text", "text": "file content here"}],
            "is_error": False,
        }
        adapter = self._make_adapter(sandbox_adapter=mock_adapter)

        result = await adapter.execute(path="/tmp/test.txt")

        assert result == "file content here"
        managed_call.assert_awaited_once_with(
            "sandbox-1", "test-server", "read_file", {"path": "/tmp/test.txt"}
        )
        mock_adapter.call_tool.assert_not_awaited()


    async def test_execute_error(self, managed_call):
        mock_adapter = AsyncMock()
        managed_call.return_value = {
            "content": [{"type": "text", "text": "File not found"}],
            "is_error": True,
        }
        adapter = self._make_adapter(sandbox_adapter=mock_adapter)

        result = await adapter.execute(path="/nonexistent")

        assert "Error:" in result
        assert "File not found" in result

    async def test_execute_camelcase_error_field(self, managed_call):
        mock_adapter = AsyncMock()
        managed_call.return_value = {
            "content": [{"type": "text", "text": "error msg"}],
            "isError": True,
        }
        adapter = self._make_adapter(sandbox_adapter=mock_adapter)

        result = await adapter.execute()
        assert "Error:" in result

    async def test_execute_exception(self, managed_call):
        mock_adapter = AsyncMock()
        managed_call.side_effect = ConnectionError("lost connection")
        adapter = self._make_adapter(sandbox_adapter=mock_adapter)

        result = await adapter.execute()
        assert "Error executing tool:" in result
        assert "lost connection" in result

    async def test_execute_no_output(self, managed_call):
        mock_adapter = AsyncMock()
        managed_call.return_value = {
            "content": [],
            "is_error": False,
        }
        adapter = self._make_adapter(sandbox_adapter=mock_adapter)

        result = await adapter.execute()
        assert result == "Tool executed successfully (no output)"
