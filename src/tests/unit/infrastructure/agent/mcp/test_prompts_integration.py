"""Tests for MCP Prompts API integration.

This module tests the MCP Prompts API support, which allows MCP servers
to expose reusable prompt templates that can be used by the agent.

MCP Prompts are server-provided templates that:
- Can include parameterized arguments
- Provide structured guidance for common tasks
- Are discovered dynamically from registered servers
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any, List

from src.infrastructure.agent.mcp.registry import MCPServerRegistry


@pytest.mark.unit
class TestMCPPromptsRegistry:
    """Test MCP Prompts API in the registry."""

    @pytest.fixture
    def registry(self):
        """Create a fresh MCPServerRegistry for each test."""
        return MCPServerRegistry(cache_ttl_seconds=60, health_check_interval_seconds=30)

    @pytest.fixture
    def mock_client_with_prompts(self):
        """Create a mock MCP client with prompts support."""
        client = AsyncMock()
        client.connect = AsyncMock()
        client.disconnect = AsyncMock()
        client.ping = AsyncMock(return_value=True)
        client.list_tools = AsyncMock(return_value=[])
        client.list_prompts = AsyncMock(
            return_value=[
                {
                    "name": "code_review",
                    "description": "Generate a code review for the given code",
                    "arguments": [
                        {"name": "code", "description": "The code to review", "required": True},
                        {
                            "name": "language",
                            "description": "Programming language",
                            "required": False,
                        },
                    ],
                },
                {
                    "name": "explain_code",
                    "description": "Explain what the code does",
                    "arguments": [
                        {"name": "code", "description": "The code to explain", "required": True}
                    ],
                },
            ]
        )
        client.get_prompt = AsyncMock(
            return_value={
                "description": "Review code for best practices",
                "messages": [
                    {
                        "role": "user",
                        "content": {"type": "text", "text": "Please review this code:\n\n{code}"},
                    }
                ],
            }
        )
        return client

    @pytest.mark.asyncio
    async def test_list_prompts_from_server(self, registry, mock_client_with_prompts):
        """Test listing prompts from a registered MCP server.

        RED: This should fail because get_server_prompts doesn't exist yet.
        """
        # Register server with mock client
        with patch.object(registry, "_clients", {"server_1": mock_client_with_prompts}):
            prompts = await registry.get_server_prompts("server_1")

        assert len(prompts) == 2
        assert prompts[0]["name"] == "code_review"
        assert prompts[1]["name"] == "explain_code"

    @pytest.mark.asyncio
    async def test_list_prompts_server_not_found(self, registry):
        """Test listing prompts from unregistered server raises error."""
        with pytest.raises(ValueError, match="Server not registered"):
            await registry.get_server_prompts("nonexistent_server")

    @pytest.mark.asyncio
    async def test_get_specific_prompt(self, registry, mock_client_with_prompts):
        """Test getting a specific prompt by name.

        RED: This should fail because get_server_prompt doesn't exist yet.
        """
        with patch.object(registry, "_clients", {"server_1": mock_client_with_prompts}):
            prompt = await registry.get_server_prompt(
                server_id="server_1",
                prompt_name="code_review",
                arguments={"code": "def hello(): pass", "language": "python"},
            )

        assert prompt is not None
        assert "messages" in prompt
        assert len(prompt["messages"]) == 1

    @pytest.mark.asyncio
    async def test_get_prompt_server_not_found(self, registry):
        """Test getting prompt from unregistered server raises error."""
        with pytest.raises(ValueError, match="Server not registered"):
            await registry.get_server_prompt(server_id="nonexistent", prompt_name="test_prompt")

    @pytest.mark.asyncio
    async def test_get_all_prompts(self, registry, mock_client_with_prompts):
        """Test getting prompts from all registered servers.

        RED: This should fail because get_all_prompts doesn't exist yet.
        """
        # Create a second mock client
        mock_client_2 = AsyncMock()
        mock_client_2.list_prompts = AsyncMock(
            return_value=[{"name": "translate", "description": "Translate text"}]
        )

        with patch.object(
            registry, "_clients", {"server_1": mock_client_with_prompts, "server_2": mock_client_2}
        ):
            all_prompts = await registry.get_all_prompts()

        assert "server_1" in all_prompts
        assert "server_2" in all_prompts
        assert len(all_prompts["server_1"]) == 2
        assert len(all_prompts["server_2"]) == 1
        assert all_prompts["server_2"][0]["name"] == "translate"

    @pytest.mark.asyncio
    async def test_prompts_not_supported(self, registry):
        """Test graceful handling when server doesn't support prompts."""
        mock_client = AsyncMock()
        # Simulate server not supporting prompts
        del mock_client.list_prompts

        with patch.object(registry, "_clients", {"server_1": mock_client}):
            prompts = await registry.get_server_prompts("server_1")

        # Should return empty list when prompts not supported
        assert prompts == []

    @pytest.mark.asyncio
    async def test_prompts_error_handling(self, registry):
        """Test error handling when prompts API fails."""
        mock_client = AsyncMock()
        mock_client.list_prompts = AsyncMock(side_effect=Exception("MCP server error"))

        with patch.object(registry, "_clients", {"server_1": mock_client}):
            with pytest.raises(Exception, match="MCP server error"):
                await registry.get_server_prompts("server_1")


@pytest.mark.unit
class TestMCPClientPromptsSupport:
    """Test MCP client prompts support."""

    @pytest.fixture
    def transport(self):
        """Create a mock transport."""
        transport = AsyncMock()
        transport.connect = AsyncMock()
        transport.disconnect = AsyncMock()
        transport.ping = AsyncMock(return_value=True)
        return transport

    @pytest.mark.asyncio
    async def test_client_list_prompts(self, transport):
        """Test MCPClient.list_prompts method.

        RED: This should fail because list_prompts may not be implemented on client.
        """
        from src.infrastructure.agent.mcp.client import MCPClient

        # The transport returns the full response, list_prompts extracts the prompts list
        transport.list_prompts = AsyncMock(
            return_value=[{"name": "test_prompt", "description": "A test prompt"}]
        )

        client = MCPClient("stdio", {})
        client._connected = True
        client.transport = transport

        prompts = await client.list_prompts()

        assert len(prompts) == 1
        assert prompts[0]["name"] == "test_prompt"

    @pytest.mark.asyncio
    async def test_client_get_prompt(self, transport):
        """Test MCPClient.get_prompt method.

        RED: This should fail because get_prompt may not be implemented on client.
        """
        from src.infrastructure.agent.mcp.client import MCPClient

        transport.get_prompt = AsyncMock(
            return_value={
                "description": "Test prompt",
                "messages": [{"role": "user", "content": "Hello"}],
            }
        )

        client = MCPClient("stdio", {})
        client._connected = True
        client.transport = transport

        prompt = await client.get_prompt("test_prompt", {"arg": "value"})

        assert prompt is not None
        assert "messages" in prompt

    @pytest.mark.asyncio
    async def test_client_not_connected_error(self):
        """Test that prompts methods raise when not connected."""
        from src.infrastructure.agent.mcp.client import MCPClient

        client = MCPClient("stdio", {})

        with pytest.raises(RuntimeError, match="not connected"):
            await client.list_prompts()

        with pytest.raises(RuntimeError, match="not connected"):
            await client.get_prompt("test", {})


@pytest.mark.unit
class TestPromptArgumentValidation:
    """Test prompt argument validation."""

    @pytest.fixture
    def registry(self):
        """Create a fresh MCPServerRegistry for each test."""
        return MCPServerRegistry(cache_ttl_seconds=60, health_check_interval_seconds=30)

    @pytest.mark.asyncio
    async def test_required_argument_missing(self, registry):
        """Test that missing required arguments are handled."""
        mock_client = AsyncMock()
        mock_client.get_prompt = AsyncMock(
            side_effect=ValueError("Missing required argument: code")
        )

        with patch.object(registry, "_clients", {"server_1": mock_client}):
            with pytest.raises(ValueError, match="Missing required argument"):
                await registry.get_server_prompt(
                    server_id="server_1",
                    prompt_name="code_review",
                    arguments={},  # Missing required 'code' argument
                )

    @pytest.mark.asyncio
    async def test_optional_arguments_omitted(self, registry):
        """Test that prompts work with only required arguments."""
        mock_client = AsyncMock()
        mock_client.get_prompt = AsyncMock(
            return_value={"messages": [{"role": "user", "content": "Review this"}]}
        )

        with patch.object(registry, "_clients", {"server_1": mock_client}):
            prompt = await registry.get_server_prompt(
                server_id="server_1",
                prompt_name="code_review",
                arguments={"code": "print('hello')"},  # Only required arg
            )

        assert prompt is not None

    @pytest.mark.asyncio
    async def test_extra_arguments_ignored(self, registry):
        """Test that extra arguments are safely ignored."""
        mock_client = AsyncMock()
        mock_client.get_prompt = AsyncMock(
            return_value={"messages": [{"role": "user", "content": "Review"}]}
        )

        with patch.object(registry, "_clients", {"server_1": mock_client}):
            prompt = await registry.get_server_prompt(
                server_id="server_1",
                prompt_name="code_review",
                arguments={
                    "code": "print('hello')",
                    "extra_arg": "should be ignored",  # Extra argument
                },
            )

        assert prompt is not None
