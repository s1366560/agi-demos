"""Tests for SandboxResourcePort abstract interface.

TDD approach: RED → GREEN → REFACTOR

This test file defines the behavior for the SandboxResourcePort interface
that decouples agent workflow from sandbox lifecycle management.

The interface provides:
1. get_sandbox_id() - Get sandbox ID without creating
2. ensure_sandbox_ready() - Ensure sandbox exists (may create)
3. execute_tool() - Execute tool in sandbox
4. sync_file() - Sync file to sandbox
5. get_sandbox_info() - Get sandbox status info
"""

import pytest
from abc import ABC
from unittest.mock import AsyncMock
from datetime import datetime

from src.domain.ports.services.sandbox_resource_port import (
    SandboxResourcePort,
    SandboxInfo,
)


class TestSandboxInfo:
    """Test SandboxInfo data class."""

    def test_sandbox_info_creation(self):
        """SandboxInfo should be creatable with all fields."""
        info = SandboxInfo(
            sandbox_id="sb-123",
            project_id="proj-456",
            tenant_id="tenant-789",
            status="running",
            is_healthy=True,
        )
        assert info.sandbox_id == "sb-123"
        assert info.project_id == "proj-456"
        assert info.status == "running"
        assert info.is_healthy is True

    def test_sandbox_info_to_dict(self):
        """SandboxInfo should convert to dictionary."""
        info = SandboxInfo(
            sandbox_id="sb-123",
            project_id="proj-456",
            tenant_id="tenant-789",
            status="running",
            endpoint="ws://localhost:8080",
            is_healthy=True,
        )
        data = info.to_dict()
        assert data["sandbox_id"] == "sb-123"
        assert data["status"] == "running"
        assert data["endpoint"] == "ws://localhost:8080"

    def test_sandbox_info_with_optional_fields(self):
        """SandboxInfo should handle optional fields."""
        info = SandboxInfo(
            sandbox_id="sb-123",
            project_id="proj-456",
            tenant_id="tenant-789",
            status="running",
        )
        assert info.endpoint is None
        assert info.websocket_url is None
        assert info.error_message is None


class TestSandboxResourcePortInterface:
    """Test SandboxResourcePort interface contract."""

    def test_is_abstract_base_class(self):
        """SandboxResourcePort should be an abstract base class."""
        assert issubclass(SandboxResourcePort, ABC)

    def test_has_required_abstract_methods(self):
        """SandboxResourcePort should have all required abstract methods."""
        abstract_methods = SandboxResourcePort.__abstractmethods__
        expected_methods = {
            "get_sandbox_id",
            "ensure_sandbox_ready",
            "execute_tool",
            "sync_file",
            "get_sandbox_info",
        }
        assert abstract_methods == expected_methods

    def test_cannot_instantiate_directly(self):
        """Should not be able to instantiate SandboxResourcePort directly."""
        with pytest.raises(TypeError):
            SandboxResourcePort()  # type: ignore


class TestSandboxResourcePortImplementation:
    """Test that implementations must follow the contract."""

    @pytest.mark.asyncio
    async def test_get_sandbox_id_returns_id_or_none(self):
        """Implementations should return sandbox ID or None."""
        # Create a mock implementation
        class MockSandboxResource(SandboxResourcePort):
            async def get_sandbox_id(self, project_id: str, tenant_id: str):
                return "sb-123" if project_id == "exists" else None

            async def ensure_sandbox_ready(self, project_id: str, tenant_id: str):
                return "sb-new"

            async def execute_tool(self, project_id: str, tool_name: str, arguments, timeout=30.0):
                return {"result": "ok"}

            async def sync_file(self, project_id: str, filename: str, content, destination="/workspace"):
                return True

            async def get_sandbox_info(self, project_id: str):
                return None

        mock = MockSandboxResource()
        assert await mock.get_sandbox_id("exists", "tenant-1") == "sb-123"
        assert await mock.get_sandbox_id("new", "tenant-1") is None

    @pytest.mark.asyncio
    async def test_ensure_sandbox_ready_creates_if_needed(self):
        """ensure_sandbox_ready should create sandbox if not exists."""
        class MockSandboxResource(SandboxResourcePort):
            def __init__(self):
                self.created = False

            async def get_sandbox_id(self, project_id: str, tenant_id: str):
                return "sb-existing" if not self.created else None

            async def ensure_sandbox_ready(self, project_id: str, tenant_id: str):
                self.created = True
                return "sb-new"

            async def execute_tool(self, project_id: str, tool_name: str, arguments, timeout=30.0):
                return {"result": "ok"}

            async def sync_file(self, project_id: str, filename: str, content, destination="/workspace"):
                return True

            async def get_sandbox_info(self, project_id: str):
                return None

        mock = MockSandboxResource()
        result = await mock.ensure_sandbox_ready("proj-1", "tenant-1")
        assert result == "sb-new"
        assert mock.created is True

    @pytest.mark.asyncio
    async def test_execute_tool_calls_sandbox(self):
        """execute_tool should delegate to sandbox adapter."""
        class MockSandboxResource(SandboxResourcePort):
            async def get_sandbox_id(self, project_id: str, tenant_id: str):
                return None

            async def ensure_sandbox_ready(self, project_id: str, tenant_id: str):
                return "sb-123"

            async def execute_tool(self, project_id: str, tool_name: str, arguments, timeout=30.0):
                return {"tool": tool_name, "args": arguments}

            async def sync_file(self, project_id: str, filename: str, content, destination="/workspace"):
                return True

            async def get_sandbox_info(self, project_id: str):
                return None

        mock = MockSandboxResource()
        result = await mock.execute_tool("proj-1", "bash", {"command": "ls"})
        assert result == {"tool": "bash", "args": {"command": "ls"}}

    @pytest.mark.asyncio
    async def test_sync_file_handles_base64_content(self):
        """sync_file should handle base64 encoded file content."""
        import base64

        class MockSandboxResource(SandboxResourcePort):
            def __init__(self):
                self.synced_files = []

            async def get_sandbox_id(self, project_id: str, tenant_id: str):
                return None

            async def ensure_sandbox_ready(self, project_id: str, tenant_id: str):
                return "sb-123"

            async def execute_tool(self, project_id: str, tool_name: str, arguments, timeout=30.0):
                return {"result": "ok"}

            async def sync_file(self, project_id: str, filename: str, content, destination="/workspace"):
                # Decode base64 and store
                decoded = base64.b64decode(content).decode()
                self.synced_files.append((filename, decoded, destination))
                return True

            async def get_sandbox_info(self, project_id: str):
                return None

        mock = MockSandboxResource()
        content = base64.b64encode(b"Hello, World!").decode()
        result = await mock.sync_file("proj-1", "test.txt", content)
        assert result is True
        assert ("test.txt", "Hello, World!", "/workspace") in mock.synced_files

    @pytest.mark.asyncio
    async def test_get_sandbox_info_returns_status(self):
        """get_sandbox_info should return sandbox status."""
        class MockSandboxResource(SandboxResourcePort):
            async def get_sandbox_id(self, project_id: str, tenant_id: str):
                return None

            async def ensure_sandbox_ready(self, project_id: str, tenant_id: str):
                return "sb-123"

            async def execute_tool(self, project_id: str, tool_name: str, arguments, timeout=30.0):
                return {"result": "ok"}

            async def sync_file(self, project_id: str, filename: str, content, destination="/workspace"):
                return True

            async def get_sandbox_info(self, project_id: str):
                return SandboxInfo(
                    sandbox_id="sb-123",
                    project_id=project_id,
                    tenant_id="tenant-1",
                    status="running",
                    is_healthy=True,
                )

        mock = MockSandboxResource()
        info = await mock.get_sandbox_info("proj-1")
        assert info.sandbox_id == "sb-123"
        assert info.status == "running"
        assert info.is_healthy is True


class TestSandboxInfoEdgeCases:
    """Test edge cases for SandboxInfo."""

    def test_sandbox_info_with_datetime_fields(self):
        """SandboxInfo should handle datetime fields correctly."""
        now = datetime.now()
        info = SandboxInfo(
            sandbox_id="sb-123",
            project_id="proj-456",
            tenant_id="tenant-789",
            status="running",
            created_at=now,
            last_accessed_at=now,
        )
        assert info.created_at == now
        assert info.last_accessed_at == now

    def test_sandbox_info_to_dict_with_datetime(self):
        """to_dict should serialize datetime to ISO format."""
        now = datetime(2024, 1, 1, 12, 0, 0)
        info = SandboxInfo(
            sandbox_id="sb-123",
            project_id="proj-456",
            tenant_id="tenant-789",
            status="running",
            created_at=now,
        )
        data = info.to_dict()
        assert data["created_at"] == "2024-01-01T12:00:00"

    def test_sandbox_info_with_none_datetime(self):
        """to_dict should handle None datetime fields."""
        info = SandboxInfo(
            sandbox_id="sb-123",
            project_id="proj-456",
            tenant_id="tenant-789",
            status="running",
            created_at=None,
            last_accessed_at=None,
        )
        data = info.to_dict()
        assert data["created_at"] is None
        assert data["last_accessed_at"] is None
