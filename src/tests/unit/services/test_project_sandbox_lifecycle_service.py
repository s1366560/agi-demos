"""Tests for ProjectSandboxLifecycleService."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.services.project_sandbox_lifecycle_service import (
    ProjectSandboxLifecycleService,
    SandboxInfo,
)
from src.application.services.sandbox_profile import SandboxProfileType
from src.domain.model.sandbox.project_sandbox import (
    ProjectSandbox,
    ProjectSandboxStatus,
)
from src.domain.ports.services.sandbox_port import SandboxStatus


class TestSandboxInfo:
    """Tests for SandboxInfo dataclass."""

    def test_to_dict(self) -> None:
        """Should convert SandboxInfo to dictionary."""
        now = datetime.now(timezone.utc)
        info = SandboxInfo(
            sandbox_id="sb-123",
            project_id="proj-456",
            tenant_id="tenant-789",
            status="running",
            endpoint="ws://localhost:8765",
            mcp_port=8765,
            is_healthy=True,
            created_at=now,
            last_accessed_at=now,
        )

        data = info.to_dict()

        assert data["sandbox_id"] == "sb-123"
        assert data["project_id"] == "proj-456"
        assert data["status"] == "running"
        assert data["is_healthy"] is True
        assert data["created_at"] == now.isoformat()


class TestProjectSandboxLifecycleService:
    """Tests for ProjectSandboxLifecycleService."""

    @pytest.fixture
    def mock_repository(self):
        """Create mock repository."""
        repo = MagicMock()
        repo.save = AsyncMock()
        repo.find_by_project = AsyncMock(return_value=None)
        repo.find_by_id = AsyncMock(return_value=None)
        repo.find_by_sandbox = AsyncMock(return_value=None)
        repo.find_by_tenant = AsyncMock(return_value=[])
        repo.find_stale = AsyncMock(return_value=[])
        repo.delete = AsyncMock(return_value=True)
        repo.delete_by_project = AsyncMock(return_value=True)
        repo.exists_for_project = AsyncMock(return_value=False)
        # Distributed locking methods (SESSION-level locks)
        repo.acquire_project_lock = AsyncMock(return_value=True)
        repo.release_project_lock = AsyncMock()
        repo.find_and_lock_by_project = AsyncMock(return_value=None)
        return repo

    @pytest.fixture
    def mock_adapter(self):
        """Create mock sandbox adapter."""
        adapter = MagicMock()
        adapter.create_sandbox = AsyncMock()
        adapter.terminate_sandbox = AsyncMock()
        adapter.get_sandbox = AsyncMock(return_value=None)
        adapter.health_check = AsyncMock(return_value=True)
        adapter.call_tool = AsyncMock(return_value={"content": [], "is_error": False})
        adapter.connect_mcp = AsyncMock(return_value=True)
        # Container existence check (for detecting externally killed containers)
        adapter.container_exists = AsyncMock(return_value=True)
        adapter.cleanup_project_containers = AsyncMock(return_value=0)
        return adapter

    @pytest.fixture
    def service(self, mock_repository, mock_adapter):
        """Create service with mock dependencies."""
        return ProjectSandboxLifecycleService(
            repository=mock_repository,
            sandbox_adapter=mock_adapter,
            default_profile=SandboxProfileType.STANDARD,
            health_check_interval_seconds=60,
            auto_recover=True,
        )

    @pytest.fixture
    def sample_association(self):
        """Create a sample ProjectSandbox association."""
        return ProjectSandbox(
            id="assoc-123",
            project_id="proj-456",
            tenant_id="tenant-789",
            sandbox_id="sb-abc",
            status=ProjectSandboxStatus.RUNNING,
            created_at=datetime.now(timezone.utc),
            last_accessed_at=datetime.now(timezone.utc),
        )

    @pytest.mark.asyncio
    async def test_get_or_create_sandbox_creates_new(
        self, service, mock_repository, mock_adapter
    ) -> None:
        """Should create new sandbox when none exists."""
        # Setup
        mock_repository.find_by_project.return_value = None

        mock_instance = MagicMock()
        mock_instance.id = "sb-new"
        mock_instance.status = SandboxStatus.RUNNING
        mock_instance.endpoint = "ws://localhost:8765"
        mock_instance.websocket_url = "ws://localhost:8765"
        mock_instance.mcp_port = 8765
        mock_instance.desktop_port = 6080
        mock_instance.terminal_port = 7681
        mock_adapter.create_sandbox.return_value = mock_instance
        mock_adapter.get_sandbox.return_value = mock_instance

        # Execute
        result = await service.get_or_create_sandbox(
            project_id="proj-456",
            tenant_id="tenant-789",
        )

        # Verify
        assert result.sandbox_id == "sb-new"
        assert result.status == "running"
        assert result.is_healthy is True
        mock_adapter.create_sandbox.assert_called_once()
        mock_repository.save.assert_called()

    @pytest.mark.asyncio
    async def test_get_or_create_sandbox_returns_existing(
        self, service, mock_repository, mock_adapter, sample_association
    ) -> None:
        """Should return existing sandbox if healthy."""
        # Setup
        mock_repository.find_by_project.return_value = sample_association

        mock_instance = MagicMock()
        mock_instance.id = "sb-abc"
        mock_instance.status = SandboxStatus.RUNNING
        mock_instance.endpoint = "ws://localhost:8765"
        mock_adapter.get_sandbox.return_value = mock_instance

        # Execute
        result = await service.get_or_create_sandbox(
            project_id="proj-456",
            tenant_id="tenant-789",
        )

        # Verify
        assert result.sandbox_id == "sb-abc"
        assert result.status == "running"
        mock_adapter.create_sandbox.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_or_create_sandbox_restarts_stopped(
        self, service, mock_repository, mock_adapter
    ) -> None:
        """Should restart stopped sandbox."""
        # Setup
        stopped_association = ProjectSandbox(
            id="assoc-123",
            project_id="proj-456",
            tenant_id="tenant-789",
            sandbox_id="sb-stopped",
            status=ProjectSandboxStatus.STOPPED,
            created_at=datetime.now(timezone.utc),
        )
        mock_repository.find_by_project.return_value = stopped_association

        mock_instance = MagicMock()
        mock_instance.id = "sb-new"
        mock_instance.status = SandboxStatus.RUNNING
        mock_adapter.create_sandbox.return_value = mock_instance
        mock_adapter.get_sandbox.return_value = mock_instance

        # Execute
        result = await service.get_or_create_sandbox(
            project_id="proj-456",
            tenant_id="tenant-789",
        )

        # Verify
        assert result.status == "running"
        mock_adapter.create_sandbox.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_project_sandbox_returns_none_if_not_exists(
        self, service, mock_repository
    ) -> None:
        """Should return None if no sandbox exists."""
        mock_repository.find_by_project.return_value = None

        result = await service.get_project_sandbox("proj-456")

        assert result is None

    @pytest.mark.asyncio
    async def test_health_check_healthy(
        self, service, mock_repository, mock_adapter, sample_association
    ) -> None:
        """Should return True for healthy sandbox."""
        mock_repository.find_by_project.return_value = sample_association
        mock_adapter.health_check.return_value = True

        result = await service.health_check("proj-456")

        assert result is True
        assert sample_association.status == ProjectSandboxStatus.RUNNING

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(
        self, service, mock_repository, mock_adapter, sample_association
    ) -> None:
        """Should return False for unhealthy sandbox."""
        mock_repository.find_by_project.return_value = sample_association
        mock_adapter.health_check.return_value = False

        result = await service.health_check("proj-456")

        assert result is False
        assert sample_association.status == ProjectSandboxStatus.ERROR

    @pytest.mark.asyncio
    async def test_health_check_no_sandbox(self, service, mock_repository) -> None:
        """Should return False if no sandbox found."""
        mock_repository.find_by_project.return_value = None

        result = await service.health_check("proj-456")

        assert result is False

    @pytest.mark.asyncio
    async def test_terminate_project_sandbox_success(
        self, service, mock_repository, mock_adapter, sample_association
    ) -> None:
        """Should successfully terminate sandbox."""
        mock_repository.find_by_project.return_value = sample_association
        mock_adapter.terminate_sandbox.return_value = True

        result = await service.terminate_project_sandbox("proj-456")

        assert result is True
        mock_adapter.terminate_sandbox.assert_called_once_with("sb-abc")
        mock_repository.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_terminate_project_sandbox_not_found(self, service, mock_repository) -> None:
        """Should return False if sandbox not found."""
        mock_repository.find_by_project.return_value = None

        result = await service.terminate_project_sandbox("proj-456")

        assert result is False

    @pytest.mark.asyncio
    async def test_execute_tool_success(
        self, service, mock_repository, mock_adapter, sample_association
    ) -> None:
        """Should execute tool in project's sandbox."""
        mock_repository.find_by_project.return_value = sample_association
        mock_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": "Hello"}],
            "is_error": False,
        }

        result = await service.execute_tool(
            project_id="proj-456",
            tool_name="bash",
            arguments={"command": "echo Hello"},
        )

        assert result["is_error"] is False
        assert result["content"][0]["text"] == "Hello"
        mock_adapter.call_tool.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_tool_no_sandbox(self, service, mock_repository) -> None:
        """Should raise error if no sandbox found."""
        from src.domain.ports.services.sandbox_port import SandboxNotFoundError

        mock_repository.find_by_project.return_value = None

        with pytest.raises(SandboxNotFoundError):
            await service.execute_tool(
                project_id="proj-456",
                tool_name="bash",
                arguments={},
            )

    @pytest.mark.asyncio
    async def test_ensure_sandbox_running_creates_if_needed(
        self, service, mock_repository, mock_adapter
    ) -> None:
        """Should create sandbox if not exists."""
        mock_repository.find_by_project.return_value = None

        mock_instance = MagicMock()
        mock_instance.id = "sb-new"
        mock_instance.status = SandboxStatus.RUNNING
        mock_adapter.create_sandbox.return_value = mock_instance
        mock_adapter.get_sandbox.return_value = mock_instance

        result = await service.ensure_sandbox_running("proj-456", "tenant-789")

        assert result.is_healthy is True
        mock_adapter.create_sandbox.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_project_sandboxes(
        self, service, mock_repository, mock_adapter, sample_association
    ) -> None:
        """Should list sandboxes for tenant."""
        mock_repository.find_by_tenant.return_value = [sample_association]

        mock_instance = MagicMock()
        mock_instance.id = "sb-abc"
        mock_instance.status = SandboxStatus.RUNNING
        mock_adapter.get_sandbox.return_value = mock_instance

        results = await service.list_project_sandboxes("tenant-789")

        assert len(results) == 1
        assert results[0].sandbox_id == "sb-abc"

    @pytest.mark.asyncio
    async def test_cleanup_stale_sandboxes(self, service, mock_repository, mock_adapter) -> None:
        """Should clean up stale sandboxes."""
        stale_association = ProjectSandbox(
            id="assoc-old",
            project_id="proj-old",
            tenant_id="tenant-789",
            sandbox_id="sb-old",
            status=ProjectSandboxStatus.RUNNING,
            last_accessed_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        mock_repository.find_stale.return_value = [stale_association]

        result = await service.cleanup_stale_sandboxes(max_idle_seconds=3600)

        assert len(result) == 1
        assert result[0] == "sb-old"
        mock_adapter.terminate_sandbox.assert_called_once_with("sb-old")

    @pytest.mark.asyncio
    async def test_cleanup_stale_sandboxes_dry_run(
        self, service, mock_repository, mock_adapter
    ) -> None:
        """Should not terminate in dry run mode."""
        stale_association = ProjectSandbox(
            id="assoc-old",
            project_id="proj-old",
            tenant_id="tenant-789",
            sandbox_id="sb-old",
            status=ProjectSandboxStatus.RUNNING,
            last_accessed_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        mock_repository.find_stale.return_value = [stale_association]

        result = await service.cleanup_stale_sandboxes(max_idle_seconds=3600, dry_run=True)

        assert len(result) == 1
        mock_adapter.terminate_sandbox.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_sandbox_status_updates_db(
        self, service, mock_repository, mock_adapter, sample_association
    ) -> None:
        """Should sync database status with container status."""
        mock_repository.find_by_project.return_value = sample_association

        mock_instance = MagicMock()
        mock_instance.id = "sb-abc"
        mock_instance.status = SandboxStatus.RUNNING
        mock_adapter.get_sandbox.return_value = mock_instance

        result = await service.sync_sandbox_status("proj-456")

        assert result.is_healthy is True
        mock_repository.save.assert_called()

    @pytest.mark.asyncio
    async def test_restart_project_sandbox(
        self, service, mock_repository, mock_adapter, sample_association
    ) -> None:
        """Should restart project sandbox."""
        mock_repository.find_by_project.return_value = sample_association

        mock_instance = MagicMock()
        mock_instance.id = "sb-new"
        mock_instance.status = SandboxStatus.RUNNING
        mock_adapter.create_sandbox.return_value = mock_instance
        mock_adapter.get_sandbox.return_value = mock_instance

        result = await service.restart_project_sandbox("proj-456")

        assert result.status == "running"

    @pytest.mark.asyncio
    async def test_recover_unhealthy_sandbox_success(
        self, service, mock_repository, mock_adapter
    ) -> None:
        """Should recover unhealthy sandbox."""
        unhealthy_association = ProjectSandbox(
            id="assoc-123",
            project_id="proj-456",
            tenant_id="tenant-789",
            sandbox_id="sb-unhealthy",
            status=ProjectSandboxStatus.UNHEALTHY,
            created_at=datetime.now(timezone.utc),
        )
        mock_repository.find_by_project.return_value = unhealthy_association
        mock_adapter.health_check.return_value = True

        mock_instance = MagicMock()
        mock_instance.id = "sb-unhealthy"
        mock_instance.status = SandboxStatus.RUNNING
        mock_adapter.get_sandbox.return_value = mock_instance

        result = await service.get_or_create_sandbox("proj-456", "tenant-789")

        assert result.status == "running"

    @pytest.mark.asyncio
    async def test_auto_recover_recreate_failed_sandbox(
        self, service, mock_repository, mock_adapter
    ) -> None:
        """Should recreate sandbox if recovery fails."""
        unhealthy_association = ProjectSandbox(
            id="assoc-123",
            project_id="proj-456",
            tenant_id="tenant-789",
            sandbox_id="sb-failed",
            status=ProjectSandboxStatus.UNHEALTHY,
            created_at=datetime.now(timezone.utc),
        )
        mock_repository.find_by_project.return_value = unhealthy_association
        mock_adapter.health_check.return_value = False

        mock_instance = MagicMock()
        mock_instance.id = "sb-new"
        mock_instance.status = SandboxStatus.RUNNING
        mock_adapter.create_sandbox.return_value = mock_instance
        mock_adapter.get_sandbox.return_value = mock_instance

        result = await service.get_or_create_sandbox("proj-456", "tenant-789")

        assert result.sandbox_id == "sb-new"


@pytest.mark.unit
class TestRecreateSandboxLifecycleFixes:
    """Tests for D1 (_reinstall_mcp_servers) and D3 (_clear_mcp_app_resources) fixes."""

    @pytest.fixture
    def mock_repository(self):
        repo = MagicMock()
        repo.save = AsyncMock()
        repo.find_by_project = AsyncMock(return_value=None)
        repo.find_by_id = AsyncMock(return_value=None)
        repo.find_by_sandbox = AsyncMock(return_value=None)
        repo.find_by_tenant = AsyncMock(return_value=[])
        repo.find_stale = AsyncMock(return_value=[])
        repo.delete = AsyncMock(return_value=True)
        repo.delete_by_project = AsyncMock(return_value=True)
        repo.exists_for_project = AsyncMock(return_value=False)
        repo.acquire_project_lock = AsyncMock(return_value=True)
        repo.release_project_lock = AsyncMock()
        repo.find_and_lock_by_project = AsyncMock(return_value=None)
        return repo

    @pytest.fixture
    def mock_adapter(self):
        adapter = MagicMock()
        adapter.create_sandbox = AsyncMock()
        adapter.terminate_sandbox = AsyncMock()
        adapter.get_sandbox = AsyncMock(return_value=None)
        adapter.health_check = AsyncMock(return_value=True)
        adapter.call_tool = AsyncMock(
            return_value={"content": [{"type": "text", "text": '{"success": true}'}]}
        )
        adapter.connect_mcp = AsyncMock(return_value=True)
        adapter.container_exists = AsyncMock(return_value=True)
        adapter.cleanup_project_containers = AsyncMock(return_value=0)
        return adapter

    @pytest.fixture
    def service(self, mock_repository, mock_adapter):
        return ProjectSandboxLifecycleService(
            repository=mock_repository,
            sandbox_adapter=mock_adapter,
            default_profile=SandboxProfileType.STANDARD,
            health_check_interval_seconds=60,
            auto_recover=True,
        )

    @pytest.mark.asyncio
    async def test_recreate_sandbox_spawns_reinstall_and_clear_tasks(
        self, service, mock_repository, mock_adapter
    ) -> None:
        """_recreate_sandbox should spawn background tasks for reinstall and clear."""
        import asyncio
        from unittest.mock import patch

        association = ProjectSandbox(
            id="assoc-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            sandbox_id="sb-old",
            status=ProjectSandboxStatus.UNHEALTHY,
            created_at=datetime.now(timezone.utc),
        )

        mock_instance = MagicMock()
        mock_instance.id = "sb-old"
        mock_instance.status = "running"
        mock_adapter.create_sandbox.return_value = mock_instance

        spawned_tasks = []
        original_create_task = asyncio.create_task

        def capture_task(coro, **kwargs):
            task = original_create_task(coro, **kwargs)
            spawned_tasks.append(task)
            return task

        with patch("asyncio.create_task", side_effect=capture_task):
            await service._recreate_sandbox(association)

        # Allow background tasks to run (they will fail due to missing DB, but that's ok)
        await asyncio.gather(*spawned_tasks, return_exceptions=True)

        # Both _reinstall_mcp_servers and _clear_mcp_app_resources tasks spawned
        assert len(spawned_tasks) == 2

    @pytest.mark.asyncio
    async def test_install_single_mcp_server_calls_install_and_start(
        self, service, mock_repository, mock_adapter
    ) -> None:
        """_install_single_mcp_server should call mcp_server_install then mcp_server_start."""
        assoc = ProjectSandbox(
            id="assoc-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            sandbox_id="sb-1",
            status=ProjectSandboxStatus.RUNNING,
            created_at=datetime.now(timezone.utc),
        )
        mock_repository.find_by_project.return_value = assoc

        await service._install_single_mcp_server(
            project_id="proj-1",
            server_name="snake-game",
            server_type="stdio",
            transport_config={"command": "node", "args": ["server.js"]},
        )

        # Should have called call_tool twice: install + start
        assert mock_adapter.call_tool.call_count == 2
        calls = mock_adapter.call_tool.call_args_list
        assert calls[0].kwargs["tool_name"] == "mcp_server_install"
        assert calls[1].kwargs["tool_name"] == "mcp_server_start"
        assert calls[0].kwargs["arguments"]["name"] == "snake-game"
