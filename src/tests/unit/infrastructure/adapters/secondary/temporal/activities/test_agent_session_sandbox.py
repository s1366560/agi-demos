"""Tests for Agent Session sandbox file sync using SandboxResourcePort.

TDD approach: RED -> GREEN -> REFACTOR

This test file verifies that the file sync functionality in agent_session
correctly uses the SandboxResourcePort interface instead of directly
accessing the MCPSandboxAdapter.
"""

import base64
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.ports.services.sandbox_resource_port import (
    SandboxInfo,
    SandboxResourcePort,
)


class MockSandboxResourcePort(SandboxResourcePort):
    """Mock SandboxResourcePort for testing."""

    def __init__(self):
        self.synced_files = []
        self._sandbox_id = "sb-test-123"
        self._should_error = False

    async def get_sandbox_id(self, project_id: str, tenant_id: str):
        return self._sandbox_id

    async def ensure_sandbox_ready(self, project_id: str, tenant_id: str):
        if self._should_error:
            raise RuntimeError("Sandbox creation failed")
        return self._sandbox_id

    async def execute_tool(self, project_id: str, tool_name: str, arguments, timeout=30.0):
        if self._should_error:
            return {"error": "Tool execution failed"}

        filename = arguments.get("filename", "unknown")
        content_base64 = arguments.get("content_base64", "")

        # Store synced file for verification
        self.synced_files.append({
            "filename": filename,
            "content_base64": content_base64,
            "destination": arguments.get("destination", "/workspace"),
        })

        return {
            "content": [
                {
                    "type": "text",
                    "text": '{"success": true, "path": "/workspace/test.txt"}'
                }
            ],
            "is_error": False
        }

    async def sync_file(self, project_id: str, filename: str, content, destination="/workspace"):
        self.synced_files.append({
            "filename": filename,
            "content_base64": content,
            "destination": destination,
        })
        return True

    async def get_sandbox_info(self, project_id: str):
        return SandboxInfo(
            sandbox_id=self._sandbox_id,
            project_id=project_id,
            tenant_id="tenant-test",
            status="running",
            is_healthy=True,
        )

    def set_error_mode(self, should_error: bool):
        """Set error mode for testing error handling."""
        self._should_error = should_error


class TestSyncFilesToSandboxWithPort:
    """Test _sync_files_to_sandbox using SandboxResourcePort."""

    @pytest.mark.asyncio
    async def test_sync_files_calls_port_methods(self):
        """sync_files_to_sandbox should call SandboxResourcePort methods."""
        from src.infrastructure.agent.sandbox_resource_provider import set_sandbox_resource_port

        mock_port = MockSandboxResourcePort()
        set_sandbox_resource_port(mock_port)

        sandbox_files = [
            {
                "filename": "test.txt",
                "content_base64": base64.b64encode(b"Hello, World!").decode(),
                "size_bytes": 13,
                "attachment_id": "att-1",
            }
        ]

        # Import the function under test
        from src.infrastructure.adapters.secondary.temporal.activities.agent_session import (
            _sync_files_to_sandbox,
        )

        # Mock attachment_service
        mock_attachment_service = MagicMock()
        mock_attachment_service.mark_sandbox_imported = AsyncMock()

        await _sync_files_to_sandbox(
            sandbox_files=sandbox_files,
            project_id="proj-1",
            tenant_id="tenant-1",
            attachment_service=mock_attachment_service,
        )

        # Verify port was called
        assert len(mock_port.synced_files) == 1
        assert mock_port.synced_files[0]["filename"] == "test.txt"

        # Verify attachment was marked as imported
        mock_attachment_service.mark_sandbox_imported.assert_called_once()

        # Clean up
        set_sandbox_resource_port(None)

    @pytest.mark.asyncio
    async def test_sync_files_handles_multiple_files(self):
        """sync_files_to_sandbox should handle multiple files correctly."""
        from src.infrastructure.agent.sandbox_resource_provider import set_sandbox_resource_port

        mock_port = MockSandboxResourcePort()
        set_sandbox_resource_port(mock_port)

        sandbox_files = [
            {
                "filename": "file1.txt",
                "content_base64": base64.b64encode(b"Content 1").decode(),
                "size_bytes": 8,
                "attachment_id": "att-1",
            },
            {
                "filename": "file2.txt",
                "content_base64": base64.b64encode(b"Content 2").decode(),
                "size_bytes": 8,
                "attachment_id": "att-2",
            },
        ]

        mock_attachment_service = MagicMock()
        mock_attachment_service.mark_sandbox_imported = AsyncMock()

        from src.infrastructure.adapters.secondary.temporal.activities.agent_session import (
            _sync_files_to_sandbox,
        )

        await _sync_files_to_sandbox(
            sandbox_files=sandbox_files,
            project_id="proj-1",
            tenant_id="tenant-1",
            attachment_service=mock_attachment_service,
        )

        # Verify both files were synced
        assert len(mock_port.synced_files) == 2
        assert mock_attachment_service.mark_sandbox_imported.call_count == 2

        # Clean up
        set_sandbox_resource_port(None)

    @pytest.mark.asyncio
    async def test_sync_files_handles_empty_content(self):
        """sync_files_to_sandbox should skip files with empty content."""
        from src.infrastructure.agent.sandbox_resource_provider import set_sandbox_resource_port

        mock_port = MockSandboxResourcePort()
        set_sandbox_resource_port(mock_port)

        sandbox_files = [
            {
                "filename": "empty.txt",
                "content_base64": "",
                "size_bytes": 0,
                "attachment_id": "att-1",
            },
        ]

        mock_attachment_service = MagicMock()
        mock_attachment_service.mark_sandbox_imported = AsyncMock()

        from src.infrastructure.adapters.secondary.temporal.activities.agent_session import (
            _sync_files_to_sandbox,
        )

        await _sync_files_to_sandbox(
            sandbox_files=sandbox_files,
            project_id="proj-1",
            tenant_id="tenant-1",
            attachment_service=mock_attachment_service,
        )

        # Empty content should be skipped
        assert len(mock_port.synced_files) == 0
        mock_attachment_service.mark_sandbox_imported.assert_not_called()

        # Clean up
        set_sandbox_resource_port(None)

    @pytest.mark.asyncio
    async def test_sync_files_returns_early_when_port_not_available(self):
        """sync_files_to_sandbox should return early when SandboxResourcePort is not available."""
        from src.infrastructure.agent.sandbox_resource_provider import set_sandbox_resource_port

        # Ensure no port is registered
        set_sandbox_resource_port(None)

        sandbox_files = [
            {
                "filename": "test.txt",
                "content_base64": base64.b64encode(b"Hello").decode(),
                "size_bytes": 5,
                "attachment_id": "att-1",
            },
        ]

        mock_attachment_service = MagicMock()

        from src.infrastructure.adapters.secondary.temporal.activities.agent_session import (
            _sync_files_to_sandbox,
        )

        # Should not raise error, just return
        await _sync_files_to_sandbox(
            sandbox_files=sandbox_files,
            project_id="proj-1",
            tenant_id="tenant-1",
            attachment_service=mock_attachment_service,
        )

        # Attachment service should not be called
        mock_attachment_service.mark_sandbox_imported.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_files_handles_tool_execution_error(self):
        """sync_files_to_sandbox should handle tool execution errors gracefully."""
        from src.infrastructure.agent.sandbox_resource_provider import set_sandbox_resource_port

        mock_port = MockSandboxResourcePort()
        mock_port.set_error_mode(True)
        set_sandbox_resource_port(mock_port)

        sandbox_files = [
            {
                "filename": "test.txt",
                "content_base64": base64.b64encode(b"Hello").decode(),
                "size_bytes": 5,
                "attachment_id": "att-1",
            },
        ]

        mock_attachment_service = MagicMock()
        mock_attachment_service.mark_sandbox_imported = AsyncMock()

        from src.infrastructure.adapters.secondary.temporal.activities.agent_session import (
            _sync_files_to_sandbox,
        )

        # Should not raise error, just log and continue
        await _sync_files_to_sandbox(
            sandbox_files=sandbox_files,
            project_id="proj-1",
            tenant_id="tenant-1",
            attachment_service=mock_attachment_service,
        )

        # Clean up
        set_sandbox_resource_port(None)


class TestSandboxResourcePortIntegration:
    """Test integration patterns for SandboxResourcePort."""

    @pytest.mark.asyncio
    async def test_port_provides_all_needed_methods(self):
        """SandboxResourcePort should provide all methods needed by agent_session."""
        from src.infrastructure.agent.sandbox_resource_provider import (
            get_sandbox_resource_port_or_raise,
            set_sandbox_resource_port,
        )

        mock_port = MockSandboxResourcePort()
        set_sandbox_resource_port(mock_port)

        port = get_sandbox_resource_port_or_raise()

        # Test all methods are callable
        sandbox_id = await port.get_sandbox_id("proj-1", "tenant-1")
        assert sandbox_id == "sb-test-123"

        ensured_id = await port.ensure_sandbox_ready("proj-1", "tenant-1")
        assert ensured_id == "sb-test-123"

        info = await port.get_sandbox_info("proj-1")
        assert info.sandbox_id == "sb-test-123"
        assert info.status == "running"

        result = await port.execute_tool("proj-1", "test", {"arg": "val"})
        assert "error" not in result or result["error"] is None

        sync_result = await port.sync_file("proj-1", "test.txt", "base64content")
        assert sync_result is True

        # Clean up
        set_sandbox_resource_port(None)
