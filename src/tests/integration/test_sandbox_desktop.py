"""Integration tests for Sandbox Desktop API endpoints.

Tests the desktop management endpoints:
1. POST /api/v1/sandbox/{sandbox_id}/desktop - Start desktop
2. DELETE /api/v1/sandbox/{sandbox_id}/desktop - Stop desktop
3. GET /api/v1/sandbox/{sandbox_id}/desktop - Get desktop status

TDD: Tests written before implementation.
"""

from datetime import datetime
from unittest.mock import Mock

import pytest

# --- Test Data ---

DESKTOP_START_REQUEST = {
    "resolution": "1280x720",
    "display": ":1",
}


def create_mock_sandbox_instance(sandbox_id: str):
    """Create a mock sandbox instance for testing."""
    from src.domain.ports.services.sandbox_port import SandboxConfig, SandboxStatus

    mock_instance = Mock()
    mock_instance.id = sandbox_id
    mock_instance.status = SandboxStatus.RUNNING
    mock_instance.config = SandboxConfig(image="sandbox-mcp-server:latest")
    mock_instance.project_path = f"/tmp/{sandbox_id}"
    mock_instance.endpoint = "ws://localhost:8765"
    mock_instance.created_at = datetime.now()
    mock_instance.websocket_url = "ws://localhost:8765"
    mock_instance.mcp_client = None
    return mock_instance


@pytest.mark.integration
class TestSandboxDesktopEndpoints:
    """Integration tests for sandbox desktop endpoints."""

    async def test_start_desktop_returns_200(
        self,
        authenticated_async_client,
        monkeypatch,
        test_sandbox_id: str,
    ):
        """Test starting desktop returns 200 with desktop status."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        # Mock get_sandbox to return a valid sandbox instance
        async def mock_get_sandbox(self, sandbox_id: str):
            return create_mock_sandbox_instance(sandbox_id)

        # Mock the MCP tool call response - returns the expected format
        async def mock_call_tool(
            self, sandbox_id: str, tool_name: str, arguments: dict, timeout: float = 600.0
        ):
            if tool_name == "start_desktop":
                # Return in the format that MCP adapter returns
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": '{"success": true, "message": "Desktop started successfully", '
                            '"url": "http://localhost:6080/vnc.html", "display": ":1", '
                            '"resolution": "1280x720", "port": 6080}',
                        }
                    ],
                    "is_error": False,
                }
            return {"content": [], "is_error": False}

        # Mock connect_mcp to avoid connection attempts
        async def mock_connect_mcp(self, sandbox_id: str, timeout: float = 30.0):
            return True

        monkeypatch.setattr(MCPSandboxAdapter, "get_sandbox", mock_get_sandbox)
        monkeypatch.setattr(MCPSandboxAdapter, "call_tool", mock_call_tool)
        monkeypatch.setattr(MCPSandboxAdapter, "connect_mcp", mock_connect_mcp)

        response = await authenticated_async_client.post(
            f"/api/v1/sandbox/{test_sandbox_id}/desktop",
            json=DESKTOP_START_REQUEST,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True
        assert data["display"] == ":1"
        assert data["resolution"] == "1280x720"
        assert "url" in data
        assert data["port"] == 6080

    async def test_start_desktop_with_custom_resolution(
        self,
        authenticated_async_client,
        monkeypatch,
        test_sandbox_id: str,
    ):
        """Test starting desktop with custom resolution."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        async def mock_get_sandbox(self, sandbox_id: str):
            return create_mock_sandbox_instance(sandbox_id)

        async def mock_call_tool(
            self, sandbox_id: str, tool_name: str, arguments: dict, timeout: float = 600.0
        ):
            if tool_name == "start_desktop":
                resolution = arguments.get("resolution", "1280x720")
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f'{{"success": true, "message": "Desktop started successfully", '
                            f'"url": "http://localhost:6080/vnc.html", "display": ":1", '
                            f'"resolution": "{resolution}", "port": 6080}}',
                        }
                    ],
                    "is_error": False,
                }
            return {"content": [], "is_error": False}

        async def mock_connect_mcp(self, sandbox_id: str, timeout: float = 30.0):
            return True

        monkeypatch.setattr(MCPSandboxAdapter, "get_sandbox", mock_get_sandbox)
        monkeypatch.setattr(MCPSandboxAdapter, "call_tool", mock_call_tool)
        monkeypatch.setattr(MCPSandboxAdapter, "connect_mcp", mock_connect_mcp)

        response = await authenticated_async_client.post(
            f"/api/v1/sandbox/{test_sandbox_id}/desktop",
            json={"resolution": "1920x1080", "display": ":1"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["resolution"] == "1920x1080"

    async def test_start_desktop_sandbox_not_found_returns_404(
        self,
        authenticated_async_client,
        monkeypatch,
    ):
        """Test starting desktop for non-existent sandbox returns 404."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        async def mock_get_sandbox(self, sandbox_id: str):
            return None  # Sandbox not found

        monkeypatch.setattr(
            MCPSandboxAdapter,
            "get_sandbox",
            mock_get_sandbox,
        )

        response = await authenticated_async_client.post(
            "/api/v1/sandbox/nonexistent/desktop",
            json=DESKTOP_START_REQUEST,
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    async def test_stop_desktop_returns_200(
        self,
        authenticated_async_client,
        monkeypatch,
        test_sandbox_id: str,
    ):
        """Test stopping desktop returns 200."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        async def mock_get_sandbox(self, sandbox_id: str):
            return create_mock_sandbox_instance(sandbox_id)

        async def mock_call_tool(
            self, sandbox_id: str, tool_name: str, arguments: dict, timeout: float = 600.0
        ):
            if tool_name == "stop_desktop":
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": '{"success": true, "message": "Desktop stopped successfully"}',
                        }
                    ],
                    "is_error": False,
                }
            return {"content": [], "is_error": False}

        async def mock_connect_mcp(self, sandbox_id: str, timeout: float = 30.0):
            return True

        monkeypatch.setattr(MCPSandboxAdapter, "get_sandbox", mock_get_sandbox)
        monkeypatch.setattr(MCPSandboxAdapter, "call_tool", mock_call_tool)
        monkeypatch.setattr(MCPSandboxAdapter, "connect_mcp", mock_connect_mcp)

        response = await authenticated_async_client.delete(
            f"/api/v1/sandbox/{test_sandbox_id}/desktop"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    async def test_stop_desktop_sandbox_not_found_returns_404(
        self,
        authenticated_async_client,
        monkeypatch,
    ):
        """Test stopping desktop for non-existent sandbox returns 404."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        async def mock_get_sandbox(self, sandbox_id: str):
            return None  # Sandbox not found

        monkeypatch.setattr(
            MCPSandboxAdapter,
            "get_sandbox",
            mock_get_sandbox,
        )

        response = await authenticated_async_client.delete("/api/v1/sandbox/nonexistent/desktop")

        assert response.status_code == 404

    async def test_get_desktop_status_when_running_returns_200(
        self,
        authenticated_async_client,
        monkeypatch,
        test_sandbox_id: str,
    ):
        """Test getting desktop status when running returns 200."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        async def mock_get_sandbox(self, sandbox_id: str):
            return create_mock_sandbox_instance(sandbox_id)

        async def mock_call_tool(
            self, sandbox_id: str, tool_name: str, arguments: dict, timeout: float = 600.0
        ):
            if tool_name == "get_desktop_status":
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": '{"running": true, "url": "http://localhost:6080/vnc.html", '
                            '"display": ":1", "resolution": "1280x720", "port": 6080}',
                        }
                    ],
                    "is_error": False,
                }
            return {"content": [], "is_error": False}

        async def mock_connect_mcp(self, sandbox_id: str, timeout: float = 30.0):
            return True

        monkeypatch.setattr(MCPSandboxAdapter, "get_sandbox", mock_get_sandbox)
        monkeypatch.setattr(MCPSandboxAdapter, "call_tool", mock_call_tool)
        monkeypatch.setattr(MCPSandboxAdapter, "connect_mcp", mock_connect_mcp)

        response = await authenticated_async_client.get(
            f"/api/v1/sandbox/{test_sandbox_id}/desktop"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True
        assert data["url"] == "http://localhost:6080/vnc.html"
        assert data["port"] == 6080

    async def test_get_desktop_status_when_stopped_returns_200(
        self,
        authenticated_async_client,
        monkeypatch,
        test_sandbox_id: str,
    ):
        """Test getting desktop status when stopped returns 200."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        async def mock_get_sandbox(self, sandbox_id: str):
            return create_mock_sandbox_instance(sandbox_id)

        async def mock_call_tool(
            self, sandbox_id: str, tool_name: str, arguments: dict, timeout: float = 600.0
        ):
            if tool_name == "get_desktop_status":
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": '{"running": false, "url": null, "display": "", '
                            '"resolution": "", "port": 0}',
                        }
                    ],
                    "is_error": False,
                }
            return {"content": [], "is_error": False}

        async def mock_connect_mcp(self, sandbox_id: str, timeout: float = 30.0):
            return True

        monkeypatch.setattr(MCPSandboxAdapter, "get_sandbox", mock_get_sandbox)
        monkeypatch.setattr(MCPSandboxAdapter, "call_tool", mock_call_tool)
        monkeypatch.setattr(MCPSandboxAdapter, "connect_mcp", mock_connect_mcp)

        response = await authenticated_async_client.get(
            f"/api/v1/sandbox/{test_sandbox_id}/desktop"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["running"] is False
        assert data["url"] is None

    async def test_get_desktop_status_sandbox_not_found_returns_404(
        self,
        authenticated_async_client,
        monkeypatch,
    ):
        """Test getting desktop status for non-existent sandbox returns 404."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        async def mock_get_sandbox(self, sandbox_id: str):
            return None  # Sandbox not found

        monkeypatch.setattr(
            MCPSandboxAdapter,
            "get_sandbox",
            mock_get_sandbox,
        )

        response = await authenticated_async_client.get("/api/v1/sandbox/nonexistent/desktop")

        assert response.status_code == 404
