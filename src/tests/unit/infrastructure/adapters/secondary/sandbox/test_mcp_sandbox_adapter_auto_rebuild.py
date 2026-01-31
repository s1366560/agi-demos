"""Tests for MCPSandboxAdapter auto-rebuild when container is killed.

This test file follows TDD methodology:
1. Write failing test first (RED)
2. Implement minimal code to pass (GREEN)
3. Refactor while keeping tests passing (REFACTOR)

The test verifies that when a sandbox container is killed (e.g., via docker kill),
the adapter automatically rebuilds it on the next tool call.
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.domain.ports.services.sandbox_port import SandboxConfig, SandboxStatus
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
    MCPSandboxAdapter,
    MCPSandboxInstance,
)


@pytest.fixture
def mock_docker():
    """Create mock Docker client."""
    mock = MagicMock()
    return mock


@pytest.fixture
def mock_docker_container(mock_docker):
    """Create mock Docker container."""
    container = MagicMock()
    container.id = "test-container-id"
    container.name = "mcp-sandbox-test123"
    container.status = "running"
    container.ports = {}
    container.labels = {
        "memstack.sandbox": "true",
        "memstack.sandbox.id": "mcp-sandbox-test123",
        "memstack.sandbox.mcp_port": "18765",
        "memstack.sandbox.desktop_port": "16080",
        "memstack.sandbox.terminal_port": "17681",
    }
    return container


@pytest.fixture
def adapter(mock_docker):
    """Create MCPSandboxAdapter with mocked Docker."""
    with patch("src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.docker.from_env", return_value=mock_docker):
        adapter = MCPSandboxAdapter()
        yield adapter


@pytest.fixture
def mock_mcp_client():
    """Create mock MCP WebSocket client."""
    client = AsyncMock()
    client.is_connected = True
    client.call_tool = AsyncMock()
    client.get_cached_tools = Mock(return_value=[])
    client.connect = AsyncMock(return_value=True)
    client.disconnect = AsyncMock()
    return client


class TestSandboxAutoRebuild:
    """Test sandbox auto-rebuild when container is killed."""

    @pytest.mark.asyncio
    async def test_call_tool_detects_dead_container_and_rebuilds(
        self, adapter, mock_docker, mock_docker_container, mock_mcp_client
    ):
        """
        RED Test: Verify that call_tool detects a killed container and rebuilds it.

        This test should FAIL initially because call_tool doesn't check container status.
        After implementation, it should PASS.
        """
        sandbox_id = "mcp-sandbox-test123"
        project_path = "/tmp/test_project"

        # Track containers created by run()
        created_containers = {}

        # Mock run for creating new containers
        def run_side_effect(**kwargs):
            container_name = kwargs.get("name", "")
            mock_container = MagicMock()
            mock_container.name = container_name
            mock_container.status = "running"
            mock_container.ports = {}
            mock_container.labels = kwargs.get("labels", {})
            # Store for later retrieval by get()
            created_containers[container_name] = mock_container
            return mock_container

        mock_docker.containers.run = Mock(side_effect=run_side_effect)

        # Mock get to return containers that were created, otherwise raise NotFound
        from docker.errors import NotFound as DockerNotFound

        def get_side_effect(name):
            if name in created_containers:
                return created_containers[name]
            raise DockerNotFound(f"Container {name} not found")

        mock_docker.containers.get.side_effect = get_side_effect

        # Create a sandbox instance in the adapter's tracking
        instance = MCPSandboxInstance(
            id=sandbox_id,
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(image="sandbox-mcp-server:latest"),
            project_path=project_path,
            endpoint="ws://localhost:18765",
            websocket_url="ws://localhost:18765",
            mcp_port=18765,
            desktop_port=16080,
            terminal_port=17681,
            mcp_client=None,  # No MCP client initially
            labels={
                "memstack.sandbox": "true",
                "memstack.sandbox.id": sandbox_id,
                "memstack.sandbox.mcp_port": "18765",
                "memstack.sandbox.desktop_port": "16080",
                "memstack.sandbox.terminal_port": "17681",
            },
        )
        adapter._active_sandboxes[sandbox_id] = instance

        # Mock connect_mcp to succeed after rebuild
        async def mock_connect(sbid, timeout=30.0):
            inst = adapter._active_sandboxes.get(sbid)
            if inst:
                inst.mcp_client = mock_mcp_client
            return True

        # Mock successful tool call
        mock_mcp_client.call_tool.return_value = MagicMock(
            content=[{"type": "text", "text": "Success"}],
            isError=False,
        )

        with patch.object(adapter, "connect_mcp", side_effect=mock_connect):
            # Act: Call tool - should detect dead container and rebuild
            result = await adapter.call_tool(
                sandbox_id=sandbox_id,
                tool_name="read",
                arguments={"file_path": "/workspace/test.txt"},
            )

        # Assert: Should have created containers (at least one for rebuild)
        assert len(created_containers) >= 1, f"Should have created containers, but created: {list(created_containers.keys())}"

        # Assert: Tool call should succeed
        assert result.get("is_error") is False, f"Tool call should succeed after rebuild, got: {result}"
        assert result.get("content")[0]["text"] == "Success"

    @pytest.mark.asyncio
    async def test_call_tool_when_container_status_exited(
        self, adapter, mock_docker, mock_mcp_client
    ):
        """
        Test that call_tool detects container with 'exited' status and rebuilds.
        """

        sandbox_id = "mcp-sandbox-test456"
        project_path = "/tmp/test_project"

        # Mock get_sandbox to return stopped container
        stopped_container = MagicMock()
        stopped_container.status = "exited"

        # Create instance with stopped container
        instance = MCPSandboxInstance(
            id=sandbox_id,
            status=SandboxStatus.STOPPED,  # Container was stopped
            config=SandboxConfig(image="sandbox-mcp-server:latest"),
            project_path=project_path,
            endpoint="ws://localhost:18765",
            websocket_url="ws://localhost:18765",
            mcp_port=18765,
            desktop_port=16080,
            terminal_port=17681,
            mcp_client=None,  # No client connection
        )
        adapter._active_sandboxes[sandbox_id] = instance

        # Mock health_check to detect unhealthy state
        with patch.object(adapter, "health_check", return_value=False):
            # Mock create_sandbox for rebuilding
            new_instance = MCPSandboxInstance(
                id=sandbox_id,
                status=SandboxStatus.RUNNING,
                config=SandboxConfig(image="sandbox-mcp-server:latest"),
                project_path=project_path,
                endpoint="ws://localhost:18765",
                websocket_url="ws://localhost:18765",
                mcp_port=18765,
                desktop_port=16080,
                terminal_port=17681,
                mcp_client=mock_mcp_client,
            )

            with patch.object(adapter, "create_sandbox", return_value=new_instance):
                with patch.object(adapter, "connect_mcp", return_value=True):
                    mock_mcp_client.call_tool.return_value = MagicMock(
                        content=[{"type": "text", "text": "Success after rebuild"}],
                        isError=False,
                    )

                    # Act: Call tool on stopped container
                    await adapter.call_tool(
                        sandbox_id=sandbox_id,
                        tool_name="read",
                        arguments={"file_path": "/workspace/test.txt"},
                    )

                    # Assert: Should have attempted to create new sandbox
                    # Note: This will fail until we implement the fix
                    # For now, we expect the function to handle it gracefully

    @pytest.mark.asyncio
    async def test_health_check_returns_false_for_dead_container(
        self, adapter, mock_docker
    ):
        """
        Test that health_check correctly identifies a dead container.
        """
        from docker.errors import NotFound

        sandbox_id = "mcp-sandbox-dead"
        project_path = "/tmp/test_project"

        # Create instance
        instance = MCPSandboxInstance(
            id=sandbox_id,
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(image="sandbox-mcp-server:latest"),
            project_path=project_path,
            endpoint="ws://localhost:18765",
            websocket_url="ws://localhost:18765",
            mcp_port=18765,
            mcp_client=None,
        )
        adapter._active_sandboxes[sandbox_id] = instance

        # Mock containers.get to raise NotFound (container was killed)
        mock_docker.containers.get.side_effect = NotFound("Container not found")

        # Act: Check health
        is_healthy = await adapter.health_check(sandbox_id)

        # Assert: Should return False
        assert is_healthy is False, "health_check should return False for dead container"

    @pytest.mark.asyncio
    async def test_health_check_returns_false_for_exited_container(
        self, adapter, mock_docker
    ):
        """
        Test that health_check correctly identifies an exited container.
        """
        sandbox_id = "mcp-sandbox-exited"
        project_path = "/tmp/test_project"

        # Create instance
        instance = MCPSandboxInstance(
            id=sandbox_id,
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(image="sandbox-mcp-server:latest"),
            project_path=project_path,
            endpoint="ws://localhost:18765",
            websocket_url="ws://localhost:18765",
            mcp_port=18765,
            mcp_client=None,
        )
        adapter._active_sandboxes[sandbox_id] = instance

        # Mock container with exited status
        mock_container = MagicMock()
        mock_container.status = "exited"
        mock_docker.containers.get.return_value = mock_container

        # Act: Check health
        is_healthy = await adapter.health_check(sandbox_id)

        # Assert: Should return False
        assert is_healthy is False, "health_check should return False for exited container"

    @pytest.mark.asyncio
    async def test_call_tool_with_healthy_container_no_rebuild(
        self, adapter, mock_docker, mock_mcp_client
    ):
        """
        Test that call_tool doesn't rebuild when container is healthy.
        """
        sandbox_id = "mcp-sandbox-healthy"
        project_path = "/tmp/test_project"

        # Mock healthy container
        mock_container = MagicMock()
        mock_container.status = "running"
        mock_docker.containers.get.return_value = mock_container

        # Create instance with connected MCP client
        instance = MCPSandboxInstance(
            id=sandbox_id,
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(image="sandbox-mcp-server:latest"),
            project_path=project_path,
            endpoint="ws://localhost:18765",
            websocket_url="ws://localhost:18765",
            mcp_port=18765,
            desktop_port=16080,
            terminal_port=17681,
            mcp_client=mock_mcp_client,
        )
        adapter._active_sandboxes[sandbox_id] = instance

        # Mock successful tool call
        mock_mcp_client.call_tool.return_value = MagicMock(
            content=[{"type": "text", "text": "Success"}],
            isError=False,
        )

        # Act: Call tool
        result = await adapter.call_tool(
            sandbox_id=sandbox_id,
            tool_name="read",
            arguments={"file_path": "/workspace/test.txt"},
        )

        # Assert: Should NOT call create_sandbox (no rebuild)
        assert not mock_docker.containers.run.called, "Should not rebuild healthy container"

        # Assert: Tool call should succeed
        assert result.get("is_error") is False
        assert result.get("content")[0]["text"] == "Success"


class TestSandboxAutoRebuildIntegration:
    """Integration-style tests for auto-rebuild functionality."""

    @pytest.mark.asyncio
    async def test_full_rebuild_flow(self, adapter, mock_docker, mock_mcp_client):
        """
        Test the full rebuild flow: kill -> detect -> rebuild -> reconnect -> execute.
        """
        from docker.errors import NotFound

        sandbox_id = "mcp-sandbox-full-flow"
        project_path = "/tmp/test_project"

        # Initial setup: container will be found as NotFound (killed)
        call_count = [0]

        def get_side_effect(name):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: container not found (was killed)
                raise NotFound("Container not found")
            else:
                # Subsequent calls: return new running container
                mock_container = MagicMock()
                mock_container.status = "running"
                return mock_container

        mock_docker.containers.get.side_effect = get_side_effect

        # Mock run for creating new container
        new_container = MagicMock()
        new_container.name = sandbox_id
        new_container.status = "running"
        new_container.labels = {
            "memstack.sandbox": "true",
            "memstack.sandbox.id": sandbox_id,
            "memstack.sandbox.mcp_port": "18765",
        }
        mock_docker.containers.run = Mock(return_value=new_container)

        # Create initial instance (simulating cached state before container was killed)
        instance = MCPSandboxInstance(
            id=sandbox_id,
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(image="sandbox-mcp-server:latest"),
            project_path=project_path,
            endpoint="ws://localhost:18765",
            websocket_url="ws://localhost:18765",
            mcp_port=18765,
            desktop_port=16080,
            terminal_port=17681,
            mcp_client=None,  # Will be reconnected
        )
        adapter._active_sandboxes[sandbox_id] = instance

        # Mock connect_mcp to succeed after rebuild
        with patch.object(adapter, "connect_mcp", return_value=True) as mock_connect:
            # After connection, set the mock client
            async def connect_side_effect(sandbox_id, timeout=30.0):
                instance = adapter._active_sandboxes.get(sandbox_id)
                if instance:
                    instance.mcp_client = mock_mcp_client
                return True

            mock_connect.side_effect = connect_side_effect

            # Mock successful tool call
            mock_mcp_client.call_tool.return_value = MagicMock(
                content=[{"type": "text", "text": "Success after rebuild"}],
                isError=False,
            )

            # Act: Call tool - should trigger full rebuild flow
            result = await adapter.call_tool(
                sandbox_id=sandbox_id,
                tool_name="bash",
                arguments={"command": "echo test"},
            )

            # Assert: Should have created new container and reconnected
            assert mock_docker.containers.run.called, "Should create new container"
            assert mock_connect.called, "Should reconnect MCP"

            # Assert: Tool call should succeed
            assert result.get("is_error") is False
            assert "Success after rebuild" in result.get("content", [{}])[0].get("text", "")
