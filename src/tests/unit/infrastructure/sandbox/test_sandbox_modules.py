"""Unit tests for sandbox modules (Phase 4)."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.domain.ports.services.sandbox_port import SandboxConfig, SandboxStatus
from src.infrastructure.adapters.secondary.sandbox.instance import (
    MCPSandboxInstance,
    SandboxPorts,
    SandboxResourceUsage,
)


def _create_sandbox_config() -> SandboxConfig:
    """Create a default sandbox config for tests."""
    return SandboxConfig(
        image="memstack/sandbox:latest",
        memory_limit="2g",
        cpu_limit=2.0,
        timeout_seconds=300,
    )


def _create_instance(
    sandbox_id: str = "sandbox-123",
    project_id: str = "proj-456",
    tenant_id: str = "tenant-789",
    status: SandboxStatus = SandboxStatus.RUNNING,
    **kwargs,
) -> MCPSandboxInstance:
    """Create an MCPSandboxInstance with default labels for project/tenant."""
    labels = kwargs.pop("labels", {})
    if project_id:
        labels["memstack.project.id"] = project_id
    if tenant_id:
        labels["memstack.tenant.id"] = tenant_id

    return MCPSandboxInstance(
        id=sandbox_id,
        status=status,
        config=_create_sandbox_config(),
        project_path="/workspace",
        labels=labels,
        **kwargs,
    )


# ============================================================================
# MCPSandboxInstance Tests
# ============================================================================


class TestMCPSandboxInstance:
    """Tests for MCPSandboxInstance."""

    def test_create_instance(self):
        """Test creating a basic instance."""
        instance = _create_instance()

        assert instance.id == "sandbox-123"
        assert instance.project_id == "proj-456"
        assert instance.tenant_id == "tenant-789"
        assert instance.status == SandboxStatus.RUNNING

    def test_is_mcp_connected_false_when_no_client(self):
        """Test is_mcp_connected is False when no client."""
        instance = _create_instance()
        assert instance.is_mcp_connected is False

    def test_is_mcp_connected_with_connected_client(self):
        """Test is_mcp_connected is True when client connected."""
        instance = _create_instance()

        # Mock connected client
        mock_client = MagicMock()
        mock_client.connected = True
        instance.mcp_client = mock_client

        assert instance.is_mcp_connected is True

    def test_is_mcp_connected_with_disconnected_client(self):
        """Test is_mcp_connected is False when client not connected."""
        instance = _create_instance()

        # Mock disconnected client
        mock_client = MagicMock()
        mock_client.connected = False
        instance.mcp_client = mock_client

        assert instance.is_mcp_connected is False

    def test_allocated_ports_empty(self):
        """Test allocated_ports returns empty list when no ports."""
        instance = _create_instance()
        assert instance.allocated_ports == []

    def test_allocated_ports_with_all_ports(self):
        """Test allocated_ports returns all allocated ports."""
        instance = _create_instance(
            mcp_port=18765,
            desktop_port=16080,
            terminal_port=17681,
        )

        ports = instance.allocated_ports
        assert 18765 in ports
        assert 16080 in ports
        assert 17681 in ports
        assert len(ports) == 3

    def test_allocated_ports_partial(self):
        """Test allocated_ports with only some ports allocated."""
        instance = _create_instance(mcp_port=18765)

        ports = instance.allocated_ports
        assert ports == [18765]

    def test_to_dict(self):
        """Test to_dict serialization."""
        now = datetime.now()
        instance = _create_instance(
            created_at=now,
            mcp_port=18765,
            desktop_port=16080,
        )

        data = instance.to_dict()

        assert data["id"] == "sandbox-123"
        assert data["project_id"] == "proj-456"
        assert data["tenant_id"] == "tenant-789"
        assert data["status"] == "running"
        assert data["mcp_port"] == 18765
        assert data["desktop_port"] == 16080
        assert data["is_mcp_connected"] is False

    def test_project_id_from_labels(self):
        """Test project_id is read from labels."""
        instance = _create_instance(project_id="custom-project")
        assert instance.project_id == "custom-project"

    def test_tenant_id_from_labels(self):
        """Test tenant_id is read from labels."""
        instance = _create_instance(tenant_id="custom-tenant")
        assert instance.tenant_id == "custom-tenant"

    def test_missing_project_id(self):
        """Test project_id is None when not in labels."""
        instance = MCPSandboxInstance(
            id="sandbox-123",
            status=SandboxStatus.RUNNING,
            config=_create_sandbox_config(),
            project_path="/workspace",
        )
        assert instance.project_id is None


# ============================================================================
# SandboxPorts Tests
# ============================================================================


class TestSandboxPorts:
    """Tests for SandboxPorts."""

    def test_create_ports(self):
        """Test creating ports allocation."""
        ports = SandboxPorts(
            mcp_port=18765,
            desktop_port=16080,
            terminal_port=17681,
        )

        assert ports.mcp_port == 18765
        assert ports.desktop_port == 16080
        assert ports.terminal_port == 17681

    def test_as_list(self):
        """Test as_list returns all ports."""
        ports = SandboxPorts(
            mcp_port=18765,
            desktop_port=16080,
            terminal_port=17681,
        )

        port_list = ports.as_list()
        assert len(port_list) == 3
        assert 18765 in port_list
        assert 16080 in port_list
        assert 17681 in port_list


# ============================================================================
# SandboxResourceUsage Tests
# ============================================================================


class TestSandboxResourceUsage:
    """Tests for SandboxResourceUsage."""

    def test_default_values(self):
        """Test default values are zero."""
        usage = SandboxResourceUsage()

        assert usage.memory_mb == 0.0
        assert usage.cpu_percent == 0.0
        assert usage.disk_mb == 0.0

    def test_to_dict(self):
        """Test to_dict serialization."""
        usage = SandboxResourceUsage(
            memory_mb=512.5,
            cpu_percent=25.0,
            disk_mb=1024.0,
            network_rx_bytes=1000,
            network_tx_bytes=500,
        )

        data = usage.to_dict()

        assert data["memory_mb"] == 512.5
        assert data["cpu_percent"] == 25.0
        assert data["disk_mb"] == 1024.0
        assert data["network_rx_bytes"] == 1000
        assert data["network_tx_bytes"] == 500


# ============================================================================
# MCPConnector Tests (unit tests with mocks)
# ============================================================================


class TestMCPConnector:
    """Tests for MCPConnector."""

    def test_build_websocket_url(self):
        """Test WebSocket URL building."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_connector import MCPConnector

        connector = MCPConnector()
        url = connector.build_websocket_url("localhost", 18765, "sandbox-123")

        assert url == "ws://localhost:18765/mcp/sandbox-123"

    def test_build_websocket_url_custom_host(self):
        """Test WebSocket URL with custom host."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_connector import MCPConnector

        connector = MCPConnector()
        url = connector.build_websocket_url("192.168.1.100", 18800, "sandbox-456")

        assert url == "ws://192.168.1.100:18800/mcp/sandbox-456"

    @pytest.mark.asyncio
    async def test_is_healthy_false_when_no_client(self):
        """Test is_healthy returns False when no client."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_connector import MCPConnector

        connector = MCPConnector()
        instance = _create_instance()

        result = await connector.is_healthy(instance)
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect_handles_no_client(self):
        """Test disconnect handles missing client gracefully."""
        from src.infrastructure.adapters.secondary.sandbox.mcp_connector import MCPConnector

        connector = MCPConnector()
        instance = _create_instance()

        # Should not raise
        await connector.disconnect(instance)
        assert instance.mcp_client is None


# ============================================================================
# ContainerManager Tests (unit tests with mocks)
# ============================================================================


class TestContainerManager:
    """Tests for ContainerManager."""

    def test_generate_container_name(self):
        """Test container name generation."""
        from src.infrastructure.adapters.secondary.sandbox.container_manager import (
            ContainerManager,
        )

        mock_docker = MagicMock()
        manager = ContainerManager(mock_docker)

        name = manager._generate_container_name("sandbox-12345678-abcd")
        assert name == "memstack-sandbox-sandbox-"

    def test_generate_container_name_short_id(self):
        """Test container name with short sandbox ID."""
        from src.infrastructure.adapters.secondary.sandbox.container_manager import (
            ContainerManager,
        )

        mock_docker = MagicMock()
        manager = ContainerManager(mock_docker)

        name = manager._generate_container_name("abc")
        assert name == "memstack-sandbox-abc"

    @pytest.mark.asyncio
    async def test_container_exists_returns_false_when_not_found(self):
        """Test container_exists returns False when container not found."""
        from src.infrastructure.adapters.secondary.sandbox.container_manager import (
            ContainerManager,
        )

        mock_docker = MagicMock()
        mock_docker.containers.list.return_value = []

        manager = ContainerManager(mock_docker)
        result = await manager.container_exists("sandbox-123")

        assert result is False
