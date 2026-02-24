"""Tests for SandboxResourceProvider.

TDD approach: RED -> GREEN -> REFACTOR

This test file verifies that the SandboxResourceProvider correctly manages
the global SandboxResourcePort instance for agent workflow access.
"""

import pytest

from src.domain.ports.services.sandbox_resource_port import (
    SandboxInfo,
    SandboxResourcePort,
)
from src.infrastructure.agent.sandbox_resource_provider import (
    get_sandbox_resource_port,
    get_sandbox_resource_port_or_raise,
    is_sandbox_resource_available,
    set_sandbox_resource_port,
)


class MockSandboxResource(SandboxResourcePort):
    """Mock implementation for testing."""

    def __init__(self, sandbox_id: str = "sb-test") -> None:
        self._sandbox_id = sandbox_id

    async def get_sandbox_id(self, project_id: str, tenant_id: str):
        return self._sandbox_id if project_id == "exists" else None

    async def ensure_sandbox_ready(self, project_id: str, tenant_id: str):
        return self._sandbox_id

    async def execute_tool(self, project_id: str, tool_name: str, arguments, timeout=30.0):
        return {"tool": tool_name, "result": "ok"}

    async def sync_file(self, project_id: str, filename: str, content, destination="/workspace"):
        return True

    async def get_sandbox_info(self, project_id: str):
        return SandboxInfo(
            sandbox_id=self._sandbox_id,
            project_id=project_id,
            tenant_id="tenant-test",
            status="running",
            is_healthy=True,
        )


class TestSetSandboxResourcePort:
    """Tests for set_sandbox_resource_port function."""

    def test_set_port_registers_instance(self):
        """set_sandbox_resource_port should register the port instance."""
        mock_port = MockSandboxResource()
        set_sandbox_resource_port(mock_port)

        retrieved = get_sandbox_resource_port()
        assert retrieved is mock_port

        # Clean up
        set_sandbox_resource_port(None)

    def test_set_port_overwrites_existing(self):
        """set_sandbox_resource_port should overwrite existing instance."""
        mock_port1 = MockSandboxResource("sb-1")
        mock_port2 = MockSandboxResource("sb-2")

        set_sandbox_resource_port(mock_port1)
        set_sandbox_resource_port(mock_port2)

        retrieved = get_sandbox_resource_port()
        assert retrieved is mock_port2
        assert retrieved._sandbox_id == "sb-2"

        # Clean up
        set_sandbox_resource_port(None)


class TestGetSandboxResourcePort:
    """Tests for get_sandbox_resource_port function."""

    def test_get_port_returns_none_when_not_set(self):
        """get_sandbox_resource_port should return None when not set."""
        # Ensure clean state
        set_sandbox_resource_port(None)

        retrieved = get_sandbox_resource_port()
        assert retrieved is None

    def test_get_port_returns_registered_instance(self):
        """get_sandbox_resource_port should return the registered instance."""
        mock_port = MockSandboxResource("sb-test")
        set_sandbox_resource_port(mock_port)

        retrieved = get_sandbox_resource_port()
        assert retrieved is mock_port

        # Clean up
        set_sandbox_resource_port(None)


class TestGetSandboxResourcePortOrRaise:
    """Tests for get_sandbox_resource_port_or_raise function."""

    def test_or_raise_returns_port_when_available(self):
        """get_sandbox_resource_port_or_raise should return port when available."""
        mock_port = MockSandboxResource()
        set_sandbox_resource_port(mock_port)

        retrieved = get_sandbox_resource_port_or_raise()
        assert retrieved is mock_port

        # Clean up
        set_sandbox_resource_port(None)

    def test_or_raises_runtime_error_when_not_available(self):
        """get_sandbox_resource_port_or_raise should raise RuntimeError when not available."""
        # Ensure clean state
        set_sandbox_resource_port(None)

        with pytest.raises(RuntimeError) as exc_info:
            get_sandbox_resource_port_or_raise()

        assert "SandboxResourcePort not registered" in str(exc_info.value)
        assert "set_sandbox_resource_port" in str(exc_info.value)


class TestIsSandboxResourceAvailable:
    """Tests for is_sandbox_resource_available function."""

    def test_returns_false_when_not_set(self):
        """is_sandbox_resource_available should return False when not set."""
        set_sandbox_resource_port(None)

        result = is_sandbox_resource_available()
        assert result is False

    def test_returns_true_when_set(self):
        """is_sandbox_resource_available should return True when set."""
        mock_port = MockSandboxResource()
        set_sandbox_resource_port(mock_port)

        result = is_sandbox_resource_available()
        assert result is True

        # Clean up
        set_sandbox_resource_port(None)


class TestProviderIntegration:
    """Integration tests for the provider pattern."""

    @pytest.mark.asyncio
    async def test_can_use_port_through_provider(self):
        """Should be able to use SandboxResourcePort through the provider."""
        mock_port = MockSandboxResource("sb-integration")
        set_sandbox_resource_port(mock_port)

        # Get port through provider
        port = get_sandbox_resource_port_or_raise()

        # Use the port
        sandbox_id = await port.get_sandbox_id("exists", "tenant-1")
        assert sandbox_id == "sb-integration"

        info = await port.get_sandbox_info("proj-1")
        assert info.sandbox_id == "sb-integration"
        assert info.status == "running"

        result = await port.execute_tool("proj-1", "bash", {"command": "ls"})
        assert result == {"tool": "bash", "result": "ok"}

        # Clean up
        set_sandbox_resource_port(None)

    @pytest.mark.asyncio
    async def test_provider_pattern_allows_port_swapping(self):
        """Provider pattern should allow swapping implementations."""
        port1 = MockSandboxResource("sb-original")
        port2 = MockSandboxResource("sb-new")

        # Use first port
        set_sandbox_resource_port(port1)
        retrieved = get_sandbox_resource_port_or_raise()
        sandbox_id = await retrieved.get_sandbox_id("exists", "tenant-1")
        assert sandbox_id == "sb-original"

        # Swap to second port
        set_sandbox_resource_port(port2)
        retrieved = get_sandbox_resource_port_or_raise()
        sandbox_id = await retrieved.get_sandbox_id("exists", "tenant-1")
        assert sandbox_id == "sb-new"

        # Clean up
        set_sandbox_resource_port(None)
