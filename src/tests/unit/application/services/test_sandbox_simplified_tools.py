"""Tests for Phase 5 & 6: Simplify Tool Registry and Cleanup.

TDD approach: RED -> GREEN -> REFACTOR

This test file defines the simplified behavior for tool management:
1. Tools are available in SandboxInfo.available_tools
2. No separate SandboxToolRegistry service needed
3. Agent can get tools directly from SandboxResourcePort
"""

import pytest

from src.domain.ports.services.sandbox_resource_port import (
    SandboxInfo,
    SandboxResourcePort,
)


class MockSandboxResourceWithTools(SandboxResourcePort):
    """Mock SandboxResourcePort that returns tool list."""

    def __init__(self, available_tools=None) -> None:
        self._available_tools = available_tools or []
        self._sandbox_id = "sb-test-123"

    async def get_sandbox_id(self, project_id: str, tenant_id: str):
        return self._sandbox_id

    async def ensure_sandbox_ready(self, project_id: str, tenant_id: str):
        return self._sandbox_id

    async def execute_tool(self, project_id: str, tool_name: str, arguments, timeout=30.0):
        return {"result": "ok"}

    async def sync_file(self, project_id: str, filename: str, content, destination="/workspace"):
        return True

    async def get_sandbox_info(self, project_id: str):
        return SandboxInfo(
            sandbox_id=self._sandbox_id,
            project_id=project_id,
            tenant_id="tenant-test",
            status="running",
            is_healthy=True,
            available_tools=self._available_tools,
        )

    def set_tools(self, tools):
        """Update available tools list."""
        self._available_tools = tools


class TestSandboxInfoIncludesTools:
    """Test SandboxInfo includes available_tools field."""

    def test_sandbox_info_has_available_tools_field(self):
        """SandboxInfo should have available_tools field."""
        info = SandboxInfo(
            sandbox_id="sb-123",
            project_id="proj-456",
            tenant_id="tenant-789",
            status="running",
            available_tools=["bash", "read", "write"],
        )

        assert info.available_tools == ["bash", "read", "write"]

    def test_sandbox_info_empty_tools_by_default(self):
        """SandboxInfo should default to empty tools list."""
        info = SandboxInfo(
            sandbox_id="sb-123",
            project_id="proj-456",
            tenant_id="tenant-789",
            status="running",
        )

        assert info.available_tools == []

    def test_sandbox_info_to_dict_includes_tools(self):
        """SandboxInfo.to_dict should include available_tools."""
        info = SandboxInfo(
            sandbox_id="sb-123",
            project_id="proj-456",
            tenant_id="tenant-789",
            status="running",
            available_tools=["bash", "read"],
        )

        data = info.to_dict()
        assert "available_tools" in data
        assert data["available_tools"] == ["bash", "read"]


class TestSandboxResourcePortProvidesTools:
    """Test SandboxResourcePort provides tools through get_sandbox_info."""

    @pytest.mark.asyncio
    async def test_get_sandbox_info_includes_available_tools(self):
        """get_sandbox_info should return SandboxInfo with available_tools."""
        port = MockSandboxResourceWithTools(
            available_tools=["bash", "read", "write", "import_file"]
        )

        info = await port.get_sandbox_info("proj-123")

        assert info.available_tools == ["bash", "read", "write", "import_file"]
        assert len(info.available_tools) == 4

    @pytest.mark.asyncio
    async def test_tools_can_be_updated_dynamically(self):
        """Available tools should be updatable."""
        port = MockSandboxResourceWithTools(available_tools=["bash", "read"])

        info = await port.get_sandbox_info("proj-123")
        assert info.available_tools == ["bash", "read"]

        # Update tools
        port.set_tools(["bash", "read", "write", "new_tool"])

        info = await port.get_sandbox_info("proj-123")
        assert info.available_tools == ["bash", "read", "write", "new_tool"]


class TestAgentCanGetToolsDirectly:
    """Test agent workflow can get tools from SandboxResourcePort."""

    @pytest.mark.asyncio
    async def test_agent_workflow_tool_discovery(self):
        """Agent should discover available tools through SandboxResourcePort."""
        from src.infrastructure.agent.sandbox_resource_provider import (
            get_sandbox_resource_port,
            set_sandbox_resource_port,
        )

        # Set up port with tools
        port = MockSandboxResourceWithTools(
            available_tools=["bash", "read", "write", "import_file", "browse"]
        )
        set_sandbox_resource_port(port)

        # Agent workflow retrieves port
        retrieved_port = get_sandbox_resource_port()
        assert retrieved_port is not None

        # Get sandbox info with tools
        info = await retrieved_port.get_sandbox_info("proj-123")

        # Verify tools are available
        assert "bash" in info.available_tools
        assert "write" in info.available_tools
        assert "import_file" in info.available_tools
        assert len(info.available_tools) == 5

        # Clean up
        set_sandbox_resource_port(None)


class TestSimplifiedToolManagement:
    """Test simplified tool management without separate registry."""

    @pytest.mark.asyncio
    async def test_no_separate_registry_needed(self):
        """Tools should be available through SandboxInfo, not separate registry."""
        port = MockSandboxResourceWithTools(available_tools=["bash", "read", "write"])

        # Get sandbox info - contains tools
        info = await port.get_sandbox_info("proj-123")

        # Agent can check if tool is available
        has_bash = "bash" in info.available_tools
        has_python = "python" in info.available_tools

        assert has_bash is True
        assert has_python is False

        # List all available tools
        all_tools = info.available_tools
        assert all_tools == ["bash", "read", "write"]

    @pytest.mark.asyncio
    async def test_sandbox_status_includes_tool_count(self):
        """Sandbox status should include tool count for monitoring."""
        port = MockSandboxResourceWithTools(
            available_tools=["bash", "read", "write", "import_file", "browse", "search"]
        )

        info = await port.get_sandbox_info("proj-123")

        # Tool count available for metrics
        tool_count = len(info.available_tools)
        assert tool_count == 6

        # Can be used for health checks
        is_healthy = info.is_healthy and tool_count > 0
        assert is_healthy is True


class TestBackwardCompatibility:
    """Test backward compatibility during migration."""

    @pytest.mark.asyncio
    async def test_sandbox_info_without_tools_field_works(self):
        """SandboxInfo without tools field should default to empty list."""
        info = SandboxInfo(
            sandbox_id="sb-123",
            project_id="proj-456",
            tenant_id="tenant-789",
            status="running",
            # available_tools not specified
        )

        # Should default to empty list
        assert info.available_tools == []
        assert len(info.available_tools) == 0

    def test_to_dict_handles_none_tools(self):
        """to_dict should handle None tools gracefully."""
        info = SandboxInfo(
            sandbox_id="sb-123",
            project_id="proj-456",
            tenant_id="tenant-789",
            status="running",
            available_tools=None,  # Explicit None
        )

        # Should be converted to empty list
        assert info.available_tools == []

        data = info.to_dict()
        assert data["available_tools"] == []
