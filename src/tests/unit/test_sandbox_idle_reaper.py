"""Unit tests for SandboxIdleReaper."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from plugins.business.environments.backend.sandbox.sandbox_idle_reaper import SandboxIdleReaper
from src.domain.model.sandbox.project_sandbox import (
    ProjectSandbox,
    ProjectSandboxStatus,
)


def _make_association(
    *,
    sandbox_id: str = "sb-1",
    project_id: str = "proj-1",
    tenant_id: str = "t-1",
    status: ProjectSandboxStatus = ProjectSandboxStatus.RUNNING,
    idle_minutes: int = 60,
) -> ProjectSandbox:
    return ProjectSandbox(
        project_id=project_id,
        tenant_id=tenant_id,
        sandbox_id=sandbox_id,
        status=status,
        last_accessed_at=datetime.now(UTC) - timedelta(minutes=idle_minutes),
    )


def _make_session_factory(
    session: AsyncMock,
) -> Any:

    @asynccontextmanager
    async def factory() -> AsyncGenerator[AsyncMock, None]:
        yield session

    return factory



@pytest.mark.unit
class TestSweep:

    async def test_sweep_no_stale_sandboxes(self) -> None:
        session = AsyncMock()
        adapter = AsyncMock()

        reaper = SandboxIdleReaper(
            idle_timeout_seconds=1800,
            check_interval_seconds=60,
            session_factory=_make_session_factory(session),
            sandbox_adapter=adapter,
        )

        with patch(
            "plugins.business.environments.backend.sandbox.sandbox_idle_reaper.SqlProjectSandboxRepository"
        ) as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.find_stale.return_value = []
            mock_repo_cls.return_value = mock_repo

            terminated = await reaper._sweep()  # type: ignore[reportPrivateUsage]

        assert terminated == []
        adapter.terminate_sandbox.assert_not_called()
        session.commit.assert_not_called()

    async def test_sweep_terminates_stale_sandboxes(self) -> None:
        session = AsyncMock()
        adapter = AsyncMock()
        adapter.terminate_sandbox = AsyncMock()

        assoc1 = _make_association(sandbox_id="sb-1", project_id="p-1")
        assoc2 = _make_association(sandbox_id="sb-2", project_id="p-2")

        reaper = SandboxIdleReaper(
            idle_timeout_seconds=1800,
            check_interval_seconds=60,
            session_factory=_make_session_factory(session),
            sandbox_adapter=adapter,
        )

        with patch(
            "plugins.business.environments.backend.sandbox.sandbox_idle_reaper.SqlProjectSandboxRepository"
        ) as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.find_stale.return_value = [assoc1, assoc2]
            mock_repo_cls.return_value = mock_repo

            terminated = await reaper._sweep()  # type: ignore[reportPrivateUsage]

        assert sorted(terminated) == ["sb-1", "sb-2"]
        assert adapter.terminate_sandbox.call_count == 2
        session.commit.assert_awaited_once()

    async def test_sweep_with_workspace_sync(self) -> None:
        session = AsyncMock()
        adapter = AsyncMock()
        adapter.terminate_sandbox = AsyncMock()
        workspace_sync = AsyncMock()
        workspace_sync.pre_destroy_sync = AsyncMock()

        assoc = _make_association(sandbox_id="sb-42", project_id="proj-7", tenant_id="t-3")

        reaper = SandboxIdleReaper(
            idle_timeout_seconds=1800,
            check_interval_seconds=60,
            session_factory=_make_session_factory(session),
            sandbox_adapter=adapter,
            workspace_sync=workspace_sync,
        )

        with patch(
            "plugins.business.environments.backend.sandbox.sandbox_idle_reaper.SqlProjectSandboxRepository"
        ) as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.find_stale.return_value = [assoc]
            mock_repo_cls.return_value = mock_repo

            terminated = await reaper._sweep()  # type: ignore[reportPrivateUsage]

        assert terminated == ["sb-42"]
        workspace_sync.pre_destroy_sync.assert_awaited_once_with(
            sandbox_id="sb-42",
            project_id="proj-7",
            tenant_id="t-3",
        )
        adapter.terminate_sandbox.assert_awaited_once_with("sb-42")

    async def test_sweep_continues_on_single_termination_failure(self) -> None:
        session = AsyncMock()
        adapter = AsyncMock()

        assoc1 = _make_association(sandbox_id="sb-fail", project_id="p-1")
        assoc2 = _make_association(sandbox_id="sb-ok", project_id="p-2")

        adapter.terminate_sandbox = AsyncMock(side_effect=[RuntimeError("container gone"), None])

        reaper = SandboxIdleReaper(
            idle_timeout_seconds=1800,
            check_interval_seconds=60,
            session_factory=_make_session_factory(session),
            sandbox_adapter=adapter,
        )

        with patch(
            "plugins.business.environments.backend.sandbox.sandbox_idle_reaper.SqlProjectSandboxRepository"
        ) as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.find_stale.return_value = [assoc1, assoc2]
            mock_repo_cls.return_value = mock_repo

            terminated = await reaper._sweep()  # type: ignore[reportPrivateUsage]

        assert terminated == ["sb-ok"]
        session.commit.assert_awaited_once()

    async def test_sweep_marks_association_terminated(self) -> None:
        session = AsyncMock()
        adapter = AsyncMock()
        adapter.terminate_sandbox = AsyncMock()

        assoc = _make_association(sandbox_id="sb-1")

        reaper = SandboxIdleReaper(
            idle_timeout_seconds=1800,
            check_interval_seconds=60,
            session_factory=_make_session_factory(session),
            sandbox_adapter=adapter,
        )

        with patch(
            "plugins.business.environments.backend.sandbox.sandbox_idle_reaper.SqlProjectSandboxRepository"
        ) as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.find_stale.return_value = [assoc]
            mock_repo_cls.return_value = mock_repo

            _ = await reaper._sweep()  # type: ignore[reportPrivateUsage]

        assert assoc.status == ProjectSandboxStatus.TERMINATED

    async def test_sweep_skips_recently_active_stale_sandbox(self) -> None:
        session = AsyncMock()
        adapter = AsyncMock()
        assoc = _make_association(sandbox_id="sb-recent", project_id="p-recent")

        reaper = SandboxIdleReaper(
            idle_timeout_seconds=1800,
            check_interval_seconds=60,
            session_factory=_make_session_factory(session),
            sandbox_adapter=adapter,
            is_recently_active=AsyncMock(return_value=True),
            recent_activity_window_seconds=300,
        )

        with patch(
            "plugins.business.environments.backend.sandbox.sandbox_idle_reaper.SqlProjectSandboxRepository"
        ) as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.find_stale.return_value = [assoc]
            mock_repo_cls.return_value = mock_repo

            terminated = await reaper._sweep()  # type: ignore[reportPrivateUsage]

        assert terminated == []
        adapter.terminate_sandbox.assert_not_called()
        mock_repo.save.assert_awaited_once()
        session.commit.assert_not_called()



@pytest.mark.unit
class TestTerminateOne:

    async def test_terminate_one_calls_adapter_and_marks_terminated(self) -> None:
        session = AsyncMock()
        adapter = AsyncMock()
        adapter.terminate_sandbox = AsyncMock()

        assoc = _make_association(sandbox_id="sb-1")

        reaper = SandboxIdleReaper(
            idle_timeout_seconds=1800,
            check_interval_seconds=60,
            session_factory=_make_session_factory(session),
            sandbox_adapter=adapter,
        )

        with patch(
            "plugins.business.environments.backend.sandbox.sandbox_idle_reaper.SqlProjectSandboxRepository"
        ) as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo_cls.return_value = mock_repo

            await reaper._terminate_one(assoc, session)  # type: ignore[reportPrivateUsage]

        adapter.terminate_sandbox.assert_awaited_once_with("sb-1")
        assert assoc.status == ProjectSandboxStatus.TERMINATED
        mock_repo.save.assert_awaited_once_with(assoc)

    async def test_terminate_one_workspace_sync_failure_does_not_block(self) -> None:
        session = AsyncMock()
        adapter = AsyncMock()
        adapter.terminate_sandbox = AsyncMock()
        workspace_sync = AsyncMock()
        workspace_sync.pre_destroy_sync = AsyncMock(side_effect=RuntimeError("sync failed"))

        assoc = _make_association(sandbox_id="sb-1", project_id="proj-1", tenant_id="t-1")

        reaper = SandboxIdleReaper(
            idle_timeout_seconds=1800,
            check_interval_seconds=60,
            session_factory=_make_session_factory(session),
            sandbox_adapter=adapter,
            workspace_sync=workspace_sync,
        )

        with patch(
            "plugins.business.environments.backend.sandbox.sandbox_idle_reaper.SqlProjectSandboxRepository"
        ) as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo_cls.return_value = mock_repo

            await reaper._terminate_one(assoc, session)  # type: ignore[reportPrivateUsage]

        workspace_sync.pre_destroy_sync.assert_awaited_once()
        adapter.terminate_sandbox.assert_awaited_once_with("sb-1")
        assert assoc.status == ProjectSandboxStatus.TERMINATED

    async def test_terminate_one_without_workspace_sync(self) -> None:
        session = AsyncMock()
        adapter = AsyncMock()
        adapter.terminate_sandbox = AsyncMock()

        assoc = _make_association(sandbox_id="sb-1")

        reaper = SandboxIdleReaper(
            idle_timeout_seconds=1800,
            check_interval_seconds=60,
            session_factory=_make_session_factory(session),
            sandbox_adapter=adapter,
            workspace_sync=None,
        )

        with patch(
            "plugins.business.environments.backend.sandbox.sandbox_idle_reaper.SqlProjectSandboxRepository"
        ) as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo_cls.return_value = mock_repo

            await reaper._terminate_one(assoc, session)  # type: ignore[reportPrivateUsage]

        adapter.terminate_sandbox.assert_awaited_once_with("sb-1")
        assert assoc.status == ProjectSandboxStatus.TERMINATED



@pytest.mark.unit
class TestLifecycle:

    async def test_start_creates_background_task(self) -> None:
        session = AsyncMock()
        adapter = AsyncMock()

        reaper = SandboxIdleReaper(
            idle_timeout_seconds=1800,
            check_interval_seconds=60,
            session_factory=_make_session_factory(session),
            sandbox_adapter=adapter,
        )

        reaper.start()
        assert reaper.is_running is True
        assert reaper._task is not None  # type: ignore[reportPrivateUsage]

        await reaper.stop()
        assert reaper.is_running is False
        assert reaper._task is None  # type: ignore[reportPrivateUsage]

    async def test_start_idempotent(self) -> None:
        session = AsyncMock()
        adapter = AsyncMock()

        reaper = SandboxIdleReaper(
            idle_timeout_seconds=1800,
            check_interval_seconds=60,
            session_factory=_make_session_factory(session),
            sandbox_adapter=adapter,
        )

        reaper.start()
        first_task = reaper._task  # type: ignore[reportPrivateUsage]

        reaper.start()
        assert reaper._task is first_task  # type: ignore[reportPrivateUsage]

        await reaper.stop()

    async def test_start_disabled_when_timeout_zero(self) -> None:
        session = AsyncMock()
        adapter = AsyncMock()

        reaper = SandboxIdleReaper(
            idle_timeout_seconds=0,
            check_interval_seconds=60,
            session_factory=_make_session_factory(session),
            sandbox_adapter=adapter,
        )

        reaper.start()
        assert reaper.is_running is False
        assert reaper._task is None  # type: ignore[reportPrivateUsage]

    async def test_start_disabled_when_timeout_negative(self) -> None:
        session = AsyncMock()
        adapter = AsyncMock()

        reaper = SandboxIdleReaper(
            idle_timeout_seconds=-1,
            check_interval_seconds=60,
            session_factory=_make_session_factory(session),
            sandbox_adapter=adapter,
        )

        reaper.start()
        assert reaper.is_running is False
        assert reaper._task is None  # type: ignore[reportPrivateUsage]

    async def test_stop_idempotent(self) -> None:
        session = AsyncMock()
        adapter = AsyncMock()

        reaper = SandboxIdleReaper(
            idle_timeout_seconds=1800,
            check_interval_seconds=60,
            session_factory=_make_session_factory(session),
            sandbox_adapter=adapter,
        )

        await reaper.stop()
        assert reaper.is_running is False



@pytest.mark.unit
class TestReaperLoop:

    async def test_reaper_loop_calls_sweep(self) -> None:
        session = AsyncMock()
        adapter = AsyncMock()

        sweep_called = asyncio.Event()

        reaper = SandboxIdleReaper(
            idle_timeout_seconds=1800,
            check_interval_seconds=0,  # No wait between sweeps for test speed
            session_factory=_make_session_factory(session),
            sandbox_adapter=adapter,
        )


        async def mock_sweep() -> list[str]:
            sweep_called.set()
            reaper._running = False  # type: ignore[reportPrivateUsage]
            return []

        reaper._sweep = mock_sweep  # type: ignore[method-assign]

        reaper._running = True  # type: ignore[reportPrivateUsage]
        await reaper._reaper_loop()  # type: ignore[reportPrivateUsage]

        assert sweep_called.is_set()

    async def test_reaper_loop_handles_sweep_exception(self) -> None:
        session = AsyncMock()
        adapter = AsyncMock()

        call_count = 0

        reaper = SandboxIdleReaper(
            idle_timeout_seconds=1800,
            check_interval_seconds=0,
            session_factory=_make_session_factory(session),
            sandbox_adapter=adapter,
        )

        async def failing_sweep() -> list[str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("sweep exploded")
            reaper._running = False  # type: ignore[reportPrivateUsage]
            return []

        reaper._sweep = failing_sweep  # type: ignore[method-assign]

        reaper._running = True  # type: ignore[reportPrivateUsage]
        await reaper._reaper_loop()  # type: ignore[reportPrivateUsage]

        assert call_count == 2
