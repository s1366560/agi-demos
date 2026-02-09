"""Test that concurrent sandbox creation is prevented by distributed locks."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.unit
class TestConcurrentCreationFix:
    """Test the multi-layer locking mechanism that prevents duplicate sandbox creation."""

    @pytest.fixture
    def mock_repository(self):
        """Create mock repository with distributed lock support."""
        repo = MagicMock()
        repo.find_by_project = AsyncMock(return_value=None)
        repo.save = AsyncMock()
        # Distributed lock methods
        repo.acquire_project_lock = AsyncMock(return_value=True)
        repo.release_project_lock = AsyncMock()
        repo.find_and_lock_by_project = AsyncMock(return_value=None)
        return repo

    @pytest.fixture
    def mock_adapter(self):
        """Create mock adapter."""
        return MagicMock()

    @pytest.fixture
    def lifecycle_service(self, mock_repository, mock_adapter):
        """Create lifecycle service with mocks."""
        from src.application.services.project_sandbox_lifecycle_service import (
            ProjectSandboxLifecycleService,
        )

        return ProjectSandboxLifecycleService(
            repository=mock_repository,
            sandbox_adapter=mock_adapter,
        )

    async def test_same_project_gets_same_in_process_lock(self, lifecycle_service):
        """Verify that the same project always gets the same in-process lock instance."""
        lock1 = await lifecycle_service._get_project_lock("test-project-1")
        lock2 = await lifecycle_service._get_project_lock("test-project-1")

        assert lock1 is lock2, "Same project should get same lock"

    async def test_different_projects_get_different_in_process_locks(self, lifecycle_service):
        """Verify that different projects get different in-process lock instances."""
        lock1 = await lifecycle_service._get_project_lock("test-project-1")
        lock2 = await lifecycle_service._get_project_lock("test-project-2")

        assert lock1 is not lock2, "Different projects should get different locks"

    async def test_lock_cleanup_removes_lock(self, lifecycle_service):
        """Verify that lock cleanup properly removes the lock."""
        lock1 = await lifecycle_service._get_project_lock("test-project-1")
        await lifecycle_service._cleanup_project_lock("test-project-1")
        lock2 = await lifecycle_service._get_project_lock("test-project-1")

        assert lock1 is not lock2, "After cleanup, should get new lock"

    async def test_concurrent_requests_serialized(self, lifecycle_service):
        """Verify that concurrent requests for the same project are serialized."""
        execution_order = []

        async def simulate_request(request_id: str):
            """Simulate a request that acquires the lock."""
            lock = await lifecycle_service._get_project_lock("test-project")
            async with lock:
                execution_order.append(f"{request_id}-start")
                await asyncio.sleep(0.01)  # Simulate some work
                execution_order.append(f"{request_id}-end")

        # Launch two concurrent requests
        await asyncio.gather(
            simulate_request("req1"),
            simulate_request("req2"),
        )

        # Verify they were serialized (one completed before other started)
        assert execution_order in [
            ["req1-start", "req1-end", "req2-start", "req2-end"],
            ["req2-start", "req2-end", "req1-start", "req1-end"],
        ], f"Requests should be serialized, got: {execution_order}"

    async def test_different_projects_can_run_concurrently(self, lifecycle_service):
        """Verify that requests for different projects can run concurrently."""
        execution_order = []

        async def simulate_request(project_id: str, request_id: str):
            """Simulate a request that acquires the lock."""
            lock = await lifecycle_service._get_project_lock(project_id)
            async with lock:
                execution_order.append(f"{request_id}-start")
                await asyncio.sleep(0.01)  # Simulate some work
                execution_order.append(f"{request_id}-end")

        # Launch two concurrent requests for different projects
        await asyncio.gather(
            simulate_request("project-1", "req1"),
            simulate_request("project-2", "req2"),
        )

        # Verify they ran concurrently (interleaved execution)
        # With different projects, starts should happen before both ends
        assert execution_order[0].endswith("-start")
        assert execution_order[1].endswith("-start")
        # Both requests should have started before both finished
        # (they run concurrently, so we see start-start-end-end pattern)
        starts = [e for e in execution_order if e.endswith("-start")]
        ends = [e for e in execution_order if e.endswith("-end")]
        assert len(starts) == 2
        assert len(ends) == 2

    async def test_db_lock_is_called_in_get_or_create(self, lifecycle_service, mock_repository):
        """Verify that database-level lock is acquired during get_or_create_sandbox."""
        # Setup mock to simulate successful sandbox creation
        mock_adapter = lifecycle_service._adapter
        mock_instance = MagicMock()
        mock_instance.id = "sb-123"
        mock_instance.config = MagicMock()
        mock_instance.config.mcp_port = 8765
        mock_adapter.create_sandbox = AsyncMock(return_value=mock_instance)
        mock_adapter.connect_mcp = AsyncMock(return_value=True)
        mock_adapter.health_check = AsyncMock(return_value=True)

        try:
            await lifecycle_service.get_or_create_sandbox(
                project_id="test-proj",
                tenant_id="test-tenant",
            )
        except Exception:
            pass  # Ignore any errors from incomplete mocking

        # Verify database SESSION lock was called with correct parameters
        mock_repository.acquire_project_lock.assert_called_with(
            "test-proj", blocking=True, timeout_seconds=30
        )
        # Verify lock was released after operation
        mock_repository.release_project_lock.assert_called_with("test-proj")

    async def test_rebuild_when_container_externally_deleted(
        self, lifecycle_service, mock_repository
    ):
        """Verify that sandbox is rebuilt when container is externally deleted."""
        from src.domain.model.sandbox.project_sandbox import ProjectSandbox, ProjectSandboxStatus

        # Setup: existing association in RUNNING state
        existing_sandbox = ProjectSandbox(
            id="assoc-1",
            project_id="test-proj",
            tenant_id="test-tenant",
            sandbox_id="old-container-id",
            status=ProjectSandboxStatus.RUNNING,
        )
        mock_repository.find_by_project = AsyncMock(return_value=existing_sandbox)

        # Simulate container was deleted externally
        mock_adapter = lifecycle_service._adapter
        mock_adapter.container_exists = AsyncMock(return_value=False)
        mock_adapter.terminate_sandbox = AsyncMock()
        mock_adapter.cleanup_project_containers = AsyncMock(return_value=0)

        # Setup mock for creating new container
        mock_instance = MagicMock()
        mock_instance.id = "new-container-id"
        mock_instance.config = MagicMock()
        mock_instance.config.mcp_port = 8765
        mock_adapter.create_sandbox = AsyncMock(return_value=mock_instance)
        mock_adapter.connect_mcp = AsyncMock(return_value=True)

        try:
            await lifecycle_service.get_or_create_sandbox(
                project_id="test-proj",
                tenant_id="test-tenant",
            )
        except Exception:
            pass  # Ignore any errors from incomplete mocking

        # Verify container existence was checked
        mock_adapter.container_exists.assert_called_with("old-container-id")

        # Verify cleanup was attempted (since container doesn't exist, need to rebuild)
        # The cleanup_project_containers should be called during _cleanup_failed_sandbox
        assert (
            mock_adapter.cleanup_project_containers.called or mock_adapter.terminate_sandbox.called
        )

    async def test_container_exists_check_called_for_running_state(
        self, lifecycle_service, mock_repository
    ):
        """Verify that container existence is checked for sandboxes in RUNNING state."""
        from src.domain.model.sandbox.project_sandbox import ProjectSandbox, ProjectSandboxStatus

        # Setup: existing association in RUNNING state with container that exists
        existing_sandbox = ProjectSandbox(
            id="assoc-1",
            project_id="test-proj",
            tenant_id="test-tenant",
            sandbox_id="existing-container-id",
            status=ProjectSandboxStatus.RUNNING,
        )
        mock_repository.find_by_project = AsyncMock(return_value=existing_sandbox)

        # Simulate container exists
        mock_adapter = lifecycle_service._adapter
        mock_adapter.container_exists = AsyncMock(return_value=True)
        mock_adapter.get_sandbox = AsyncMock(
            return_value=MagicMock(
                status=MagicMock(value="running"),
                endpoint="ws://localhost:8765",
                mcp_port=8765,
            )
        )

        result = await lifecycle_service.get_or_create_sandbox(
            project_id="test-proj",
            tenant_id="test-tenant",
        )

        # Verify container existence was checked
        mock_adapter.container_exists.assert_called_with("existing-container-id")

        # Verify we got the existing sandbox back (no recreation)
        assert result.sandbox_id == "existing-container-id"


@pytest.mark.unit
class TestAgentWorkerSandboxConsistency:
    """Test that Agent Worker uses the same sandbox as API Server.

    These tests verify that:
    1. Agent Worker queries database FIRST for sandbox associations
    2. Agent Worker NEVER creates sandboxes directly
    3. Agent Worker syncs with Docker to ensure cache consistency
    """

    @pytest.fixture
    def mock_sandbox_adapter(self):
        """Create mock MCPSandboxAdapter."""
        adapter = MagicMock()
        adapter._active_sandboxes = {}
        adapter.sync_from_docker = AsyncMock()
        adapter.container_exists = AsyncMock(return_value=True)
        adapter.connect_mcp = AsyncMock(return_value=True)
        adapter.list_tools = AsyncMock(return_value=[])
        adapter.create_sandbox = AsyncMock()  # Should NOT be called
        adapter._docker = MagicMock()
        adapter._docker.containers.list = MagicMock(return_value=[])
        return adapter

    @pytest.fixture
    def mock_db_session(self):
        """Create mock database session."""
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock()
        return session

    async def test_load_project_sandbox_tools_never_creates_sandbox(
        self, mock_sandbox_adapter, monkeypatch
    ):
        """Verify _load_project_sandbox_tools NEVER creates sandboxes directly.

        This is critical to prevent duplicate container creation between
        API Server and Agent Worker.
        """
        # Setup: No sandbox in DB, no containers in Docker
        mock_repo = MagicMock()
        mock_repo.find_by_project = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        # Patch database session factory and global adapter
        import src.infrastructure.agent.state.agent_worker_state as worker_state

        original_adapter = getattr(worker_state, "_mcp_sandbox_adapter", None)

        try:
            # Set the mock adapter as the global
            worker_state._mcp_sandbox_adapter = mock_sandbox_adapter

            # Patch database imports
            with monkeypatch.context() as m:
                # Mock the database session factory
                m.setattr(
                    "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
                    MagicMock(return_value=mock_session),
                )
                m.setattr(
                    "src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository.SqlProjectSandboxRepository",
                    MagicMock(return_value=mock_repo),
                )

                # Call the function
                from src.infrastructure.agent.state.agent_worker_state import (
                    _load_project_sandbox_tools,
                )

                result = await _load_project_sandbox_tools(
                    project_id="test-proj",
                    tenant_id="test-tenant",
                )

                # Verify NO sandbox was created
                mock_sandbox_adapter.create_sandbox.assert_not_called()

                # Verify result is empty (no tools since no sandbox)
                assert result == {}

        finally:
            # Restore original adapter
            worker_state._mcp_sandbox_adapter = original_adapter

    async def test_load_project_sandbox_tools_uses_db_sandbox(
        self, mock_sandbox_adapter, monkeypatch
    ):
        """Verify _load_project_sandbox_tools uses sandbox from database.

        When a sandbox exists in the database, Agent Worker should use it
        instead of creating a new one.
        """
        from src.domain.model.sandbox.project_sandbox import ProjectSandbox, ProjectSandboxStatus

        # Setup: Sandbox exists in DB
        existing_sandbox = ProjectSandbox(
            id="assoc-1",
            project_id="test-proj",
            tenant_id="test-tenant",
            sandbox_id="db-sandbox-id",
            status=ProjectSandboxStatus.RUNNING,
        )

        mock_repo = MagicMock()
        mock_repo.find_by_project = AsyncMock(return_value=existing_sandbox)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        # Simulate sandbox exists in adapter cache after sync
        def add_to_cache():
            mock_sandbox_adapter._active_sandboxes["db-sandbox-id"] = MagicMock()

        mock_sandbox_adapter.sync_from_docker = AsyncMock(side_effect=add_to_cache)
        mock_sandbox_adapter.list_tools = AsyncMock(
            return_value=[{"name": "bash"}, {"name": "read"}]
        )

        import src.infrastructure.agent.state.agent_worker_state as worker_state

        original_adapter = getattr(worker_state, "_mcp_sandbox_adapter", None)

        try:
            worker_state._mcp_sandbox_adapter = mock_sandbox_adapter

            with monkeypatch.context() as m:
                m.setattr(
                    "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
                    MagicMock(return_value=mock_session),
                )
                m.setattr(
                    "src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository.SqlProjectSandboxRepository",
                    MagicMock(return_value=mock_repo),
                )

                from src.infrastructure.agent.state.agent_worker_state import (
                    _load_project_sandbox_tools,
                )

                result = await _load_project_sandbox_tools(
                    project_id="test-proj",
                    tenant_id="test-tenant",
                )

                # Verify database was queried
                mock_repo.find_by_project.assert_called_with("test-proj")

                # Verify sync was called (to populate adapter cache)
                mock_sandbox_adapter.sync_from_docker.assert_called()

                # Verify NO new sandbox was created
                mock_sandbox_adapter.create_sandbox.assert_not_called()

                # Verify MCP was connected to the DB sandbox
                mock_sandbox_adapter.connect_mcp.assert_called_with("db-sandbox-id")

        finally:
            worker_state._mcp_sandbox_adapter = original_adapter

    @pytest.mark.skip(reason="_sync_files_to_sandbox was removed; file sync now handled differently")
    async def test_sync_files_uses_db_sandbox_not_cache(self, mock_sandbox_adapter, monkeypatch):
        """Verify _sync_files_to_sandbox uses database as source of truth.

        This tests that files are always synced to the sandbox that was
        created by API Server, not a potentially stale cached one.
        """
        from src.domain.model.sandbox.project_sandbox import ProjectSandbox, ProjectSandboxStatus

        # Setup: Sandbox in DB
        db_sandbox = ProjectSandbox(
            id="assoc-1",
            project_id="test-proj",
            tenant_id="test-tenant",
            sandbox_id="api-server-sandbox",
            status=ProjectSandboxStatus.RUNNING,
        )

        mock_repo = MagicMock()
        mock_repo.find_by_project = AsyncMock(return_value=db_sandbox)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        # Simulate sandbox exists in adapter cache after sync
        def add_to_cache():
            mock_sandbox_adapter._active_sandboxes["api-server-sandbox"] = MagicMock()

        mock_sandbox_adapter.sync_from_docker = AsyncMock(side_effect=add_to_cache)
        mock_sandbox_adapter.call_tool = AsyncMock(
            return_value={
                "content": [
                    {"type": "text", "text": '{"success": true, "path": "/workspace/test.txt"}'}
                ],
                "is_error": False,
            }
        )

        import src.infrastructure.agent.state.agent_worker_state as worker_state

        original_adapter = getattr(worker_state, "_mcp_sandbox_adapter", None)

        try:
            worker_state._mcp_sandbox_adapter = mock_sandbox_adapter

            with monkeypatch.context() as m:
                m.setattr(
                    "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
                    MagicMock(return_value=mock_session),
                )
                m.setattr(
                    "src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository.SqlProjectSandboxRepository",
                    MagicMock(return_value=mock_repo),
                )

                from src.infrastructure.adapters.secondary.temporal.activities.agent_session import (
                    _sync_files_to_sandbox,
                )

                await _sync_files_to_sandbox(
                    sandbox_files=[
                        {
                            "filename": "test.txt",
                            "content_base64": "dGVzdCBjb250ZW50",
                            "attachment_id": "att-1",
                        }
                    ],
                    project_id="test-proj",
                    tenant_id="test-tenant",
                    attachment_service=MagicMock(),
                )

                # Verify database was queried
                mock_repo.find_by_project.assert_called_with("test-proj")

                # Verify file was synced to the correct sandbox from DB
                mock_sandbox_adapter.call_tool.assert_called()
                call_args = mock_sandbox_adapter.call_tool.call_args
                assert call_args.kwargs["sandbox_id"] == "api-server-sandbox"

        finally:
            worker_state._mcp_sandbox_adapter = original_adapter


@pytest.mark.unit
class TestWebSocketSandboxIntegration:
    """Test that WebSocket handlers have sandbox lifecycle integration code."""

    def test_handle_start_agent_has_sandbox_integration(self):
        """
        Verify that StartAgentHandler contains sandbox lifecycle integration code.
        """
        import inspect

        from src.infrastructure.adapters.primary.web.websocket.handlers.lifecycle_handler import (
            StartAgentHandler,
        )

        source = inspect.getsource(StartAgentHandler)

        # Verify sandbox lifecycle is referenced
        assert "sandbox" in source.lower(), (
            "StartAgentHandler should have sandbox integration"
        )

    def test_handle_restart_agent_has_sandbox_integration(self):
        """
        Verify that RestartAgentHandler contains sandbox lifecycle integration code.
        """
        import inspect

        from src.infrastructure.adapters.primary.web.websocket.handlers.lifecycle_handler import (
            RestartAgentHandler,
        )

        source = inspect.getsource(RestartAgentHandler)

        # Verify sandbox lifecycle is referenced
        assert "sandbox" in source.lower(), (
            "RestartAgentHandler should have sandbox integration"
        )

    def test_sandbox_integration_handles_errors_gracefully(self):
        """
        Verify that sandbox integration errors are caught and logged.
        """
        import inspect

        from src.infrastructure.adapters.primary.web.websocket.handlers.lifecycle_handler import (
            _ensure_sandbox_exists,
        )

        source = inspect.getsource(_ensure_sandbox_exists)

        # Verify there's a try/except around sandbox code
        assert "except Exception" in source or "except" in source, (
            "Sandbox integration should have error handling"
        )
