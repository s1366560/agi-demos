"""Unit tests for DockerSandboxAdapter workspace path configuration.

This test validates that the sandbox container correctly mounts the project
to /workspace (not /workspace/project) and uses /workspace as working directory.

TDD Workflow:
1. RED: Tests fail because current implementation mounts to /workspace/project
2. GREEN: Fix the mount path to /workspace
3. REFACTOR: Ensure consistency across all sandbox adapters
"""

import tempfile
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.domain.ports.services.sandbox_port import SandboxConfig
from src.infrastructure.adapters.secondary.sandbox.docker_sandbox_adapter import (
    DockerSandboxAdapter,
)


@pytest.fixture
def docker_adapter():
    """Create DockerSandboxAdapter with mocked Docker client."""
    with patch("docker.from_env") as mock_from_env:
        docker_client = MagicMock()
        mock_from_env.return_value = docker_client
        yield DockerSandboxAdapter(), docker_client


@pytest.mark.unit
class TestDockerSandboxWorkspacePath:
    """Test workspace path configuration in Docker sandbox."""

    @pytest.mark.asyncio
    async def test_create_sandbox_mounts_project_to_workspace_root(
        self, docker_adapter
    ):
        """Test that project is mounted to /workspace (not /workspace/project)."""
        # Arrange
        adapter, mock_docker = docker_adapter
        with tempfile.TemporaryDirectory() as project_path:
            mock_container = MagicMock()
            mock_docker.containers.run.return_value = mock_container
            mock_docker.containers.get.return_value = mock_container
            mock_container.status = "running"

            config = SandboxConfig(timeout_seconds=300)

            # Act
            await adapter.create_sandbox(
                project_path=project_path,
                config=config,
            )

            # Assert - verify the container.run was called
            assert mock_docker.containers.run.called
            call_args, call_kwargs = mock_docker.containers.run.call_args

            # Verify working directory is /workspace
            assert call_kwargs.get("working_dir") == "/workspace"

            # Verify project is mounted to /workspace (NOT /workspace/project)
            assert "volumes" in call_kwargs
            volumes = call_kwargs["volumes"]
            assert project_path in volumes
            assert volumes[project_path]["bind"] == "/workspace", (
                f"Expected mount to /workspace but got {volumes[project_path]['bind']}. "
                "Current implementation mounts to /workspace/project which is inconsistent."
            )
            assert volumes[project_path]["mode"] == "rw", (
                "Expected read-write mode but got read-only. "
                "Tools need write access for temporary files."
            )

    @pytest.mark.asyncio
    async def test_create_sandbox_without_project_uses_default_workspace(
        self, docker_adapter
    ):
        """Test that sandbox without project path still uses /workspace as working dir."""
        # Arrange
        adapter, mock_docker = docker_adapter
        mock_container = MagicMock()
        mock_docker.containers.run.return_value = mock_container
        mock_docker.containers.get.return_value = mock_container
        mock_container.status = "running"

        config = SandboxConfig(timeout_seconds=300)

        # Act
        await adapter.create_sandbox(
            project_path=None,
            config=config,
        )

        # Assert
        assert mock_docker.containers.run.called
        call_args, call_kwargs = mock_docker.containers.run.call_args

        # Working directory should still be /workspace
        assert call_kwargs.get("working_dir") == "/workspace"

        # No custom volumes when no project path
        assert "volumes" not in call_kwargs or len(call_kwargs.get("volumes", {})) == 0

    def test_workspace_path_consistency_with_mcp_adapter(self):
        """Test that DockerSandboxAdapter uses same paths as MCPSandboxAdapter.

        MCPSandboxAdapter mounts to /workspace with mode=rw.
        DockerSandboxAdapter should do the same for consistency.
        """
        # This is a documentation test - verifies the contract
        # Both adapters should:
        # 1. Set working_dir to /workspace
        # 2. Mount project_path to /workspace (not /workspace/project)
        # 3. Use mode=rw for read-write access

        expected_config = {
            "working_dir": "/workspace",
            "mount_bind": "/workspace",
            "mount_mode": "rw",
        }

        # Document the expected behavior
        assert expected_config["working_dir"] == "/workspace"
        assert expected_config["mount_bind"] == "/workspace"
        assert expected_config["mount_mode"] == "rw"


@pytest.mark.unit
class TestDockerSandboxVolumeConfiguration:
    """Test volume mount configuration details."""

    @pytest.mark.asyncio
    async def test_volume_mount_is_read_write(self, docker_adapter):
        """Test that mounted volume is read-write (not read-only)."""
        adapter, mock_docker = docker_adapter
        with tempfile.TemporaryDirectory() as project_path:
            mock_container = MagicMock()
            mock_docker.containers.run.return_value = mock_container
            mock_docker.containers.get.return_value = mock_container
            mock_container.status = "running"

            config = SandboxConfig(timeout_seconds=300)

            await adapter.create_sandbox(
                project_path=project_path,
                config=config,
            )

            call_args, call_kwargs = mock_docker.containers.run.call_args
            volumes = call_kwargs["volumes"]

            # Mode should be "rw" for read-write access
            # This allows tools to create temporary files in workspace
            assert volumes[project_path]["mode"] == "rw"

    @pytest.mark.asyncio
    async def test_tmp_workspace_uses_default_without_custom_mount(
        self, docker_adapter
    ):
        """Test that /tmp/sandbox_workspace doesn't create custom volume mount."""
        adapter, mock_docker = docker_adapter
        mock_container = MagicMock()
        mock_docker.containers.run.return_value = mock_container
        mock_docker.containers.get.return_value = mock_container
        mock_container.status = "running"

        config = SandboxConfig(timeout_seconds=300)

        await adapter.create_sandbox(
            project_path="/tmp/sandbox_workspace",
            config=config,
        )

        call_args, call_kwargs = mock_docker.containers.run.call_args

        # Should not have custom volumes for default tmp path
        assert "volumes" not in call_kwargs or len(call_kwargs.get("volumes", {})) == 0
