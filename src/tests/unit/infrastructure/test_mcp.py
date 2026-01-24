"""
Unit tests for MCP (Model Context Protocol) infrastructure components.

Tests cover:
- MCP configuration models
"""

from src.infrastructure.mcp.config import (
    McpLocalConfig,
    McpOAuthConfig,
    McpRemoteConfig,
    MCPStatus,
    MCPStatusType,
    MCPToolDefinition,
)


class TestMcpConfig:
    """Tests for MCP configuration models."""

    def test_local_config_defaults(self):
        """Test McpLocalConfig with default values."""
        config = McpLocalConfig(command=["python", "server.py"])

        assert config.type == "local"
        assert config.command == ["python", "server.py"]
        assert config.environment is None
        assert config.enabled is True
        assert config.timeout == 30000

    def test_local_config_with_env(self):
        """Test McpLocalConfig with environment variables."""
        config = McpLocalConfig(
            command=["docker", "run", "-i", "mcp/fetch"],
            environment={"DEBUG": "true", "API_KEY": "secret"},
            enabled=True,
            timeout=60000,
        )

        assert config.command == ["docker", "run", "-i", "mcp/fetch"]
        assert config.environment == {"DEBUG": "true", "API_KEY": "secret"}
        assert config.timeout == 60000

    def test_remote_config_defaults(self):
        """Test McpRemoteConfig with default values."""
        config = McpRemoteConfig(url="https://api.example.com/mcp")

        assert config.type == "remote"
        assert config.url == "https://api.example.com/mcp"
        assert config.headers is None
        assert config.oauth is None
        assert config.enabled is True
        assert config.timeout == 30000

    def test_remote_config_with_oauth(self):
        """Test McpRemoteConfig with OAuth configuration."""
        oauth = McpOAuthConfig(
            client_id="my-client",
            client_secret="secret",
            scope="read write",
        )
        config = McpRemoteConfig(
            url="https://api.example.com/mcp",
            headers={"X-Custom": "header"},
            oauth=oauth,
        )

        assert config.oauth.client_id == "my-client"
        assert config.oauth.scope == "read write"

    def test_remote_config_oauth_disabled(self):
        """Test McpRemoteConfig with OAuth explicitly disabled."""
        config = McpRemoteConfig(
            url="https://api.example.com/mcp",
            oauth=False,
        )

        assert config.oauth is False


class TestMcpStatus:
    """Tests for MCPStatus model."""

    def test_status_connected(self):
        """Test creating connected status."""
        status = MCPStatus.connected()

        assert status.status == MCPStatusType.CONNECTED
        assert status.error is None

    def test_status_disabled(self):
        """Test creating disabled status."""
        status = MCPStatus.disabled()

        assert status.status == MCPStatusType.DISABLED
        assert status.error is None

    def test_status_failed(self):
        """Test creating failed status with error."""
        status = MCPStatus.failed("Connection refused")

        assert status.status == MCPStatusType.FAILED
        assert status.error == "Connection refused"

    def test_status_needs_auth(self):
        """Test creating needs_auth status."""
        status = MCPStatus.needs_auth()

        assert status.status == MCPStatusType.NEEDS_AUTH


class TestMcpToolDefinition:
    """Tests for MCPToolDefinition model."""

    def test_tool_definition_minimal(self):
        """Test MCPToolDefinition with minimal fields."""
        tool = MCPToolDefinition(name="fetch")

        assert tool.name == "fetch"
        assert tool.description is None
        assert tool.inputSchema == {}

    def test_tool_definition_full(self):
        """Test MCPToolDefinition with all fields."""
        tool = MCPToolDefinition(
            name="fetch",
            description="Fetch URL content",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                },
                "required": ["url"],
            },
        )

        assert tool.name == "fetch"
        assert tool.description == "Fetch URL content"
        assert "url" in tool.inputSchema["properties"]
