"""Unit tests for :mod:`worker_launch_drain` after the Avernet Core cutover.

The platform SQL worker-launch outbox is retired: ``_enqueue_worker_launch``
fail-closes with ``LegacyWorkspaceRuntimeRetiredError`` instead of writing
``workspace_plan_outbox`` rows. The drain helpers still have live callers, so
their queue-preservation contract matters: a failed enqueue must restore the
pending ``(task, actor_user_id, leader_agent_id)`` triples instead of dropping
them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest

from src.application.services.workspace_task_command_service import (
    WorkspaceTaskCommandService,
)
from src.infrastructure.agent.workspace import worker_launch_drain
from src.infrastructure.workspace_core.legacy_runtime import (
    LegacyWorkspaceRuntimeRetiredError,
)


@dataclass
class _FakeTask:
    id: str
    workspace_id: str
    assignee_agent_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@pytest.mark.unit
class TestDrainPendingWorkerLaunches:
    @pytest.mark.asyncio
    async def test_drain_propagates_retired_error_and_restores_pending_launches(self) -> None:
        session = AsyncMock()
        command_service = WorkspaceTaskCommandService(AsyncMock())
        task = _FakeTask(id="wt-queued", workspace_id="workspace-1", assignee_agent_id="agent-1")
        command_service._pending_worker_launches.append((task, "user-1", "leader-1"))

        with pytest.raises(LegacyWorkspaceRuntimeRetiredError):
            await worker_launch_drain.drain_pending_worker_launches_to_outbox(
                command_service,
                session,
            )

        session.rollback.assert_awaited_once()
        pending = command_service.consume_pending_worker_launches()
        assert len(pending) == 1
        assert pending[0][0] is task
        assert pending[0][1] == "user-1"
        assert pending[0][2] == "leader-1"

    @pytest.mark.asyncio
    async def test_drain_consumes_non_launchable_without_touching_session(self) -> None:
        session = AsyncMock()
        command_service = WorkspaceTaskCommandService(AsyncMock())
        task = _FakeTask(id="wt-unassigned", workspace_id="workspace-1")
        command_service._pending_worker_launches.append((task, "user-1", None))

        fired = await worker_launch_drain.drain_pending_worker_launches_to_outbox(
            command_service,
            session,
        )

        assert fired == 0
        assert command_service.consume_pending_worker_launches() == []
        session.commit.assert_not_awaited()
        session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_transactional_enqueue_propagates_retired_error_without_committing(self) -> None:
        session = AsyncMock()
        command_service = WorkspaceTaskCommandService(AsyncMock())
        task = _FakeTask(id="wt-direct", workspace_id="workspace-1", assignee_agent_id="agent-1")
        command_service._pending_worker_launches.append((task, "user-1", None))

        with pytest.raises(LegacyWorkspaceRuntimeRetiredError):
            await worker_launch_drain.enqueue_pending_worker_launches_to_outbox(
                command_service,
                session,
            )

        session.commit.assert_not_awaited()
        session.rollback.assert_not_awaited()
        pending = command_service.consume_pending_worker_launches()
        assert len(pending) == 1
        assert pending[0][0] is task
        assert pending[0][1] == "user-1"
        assert pending[0][2] is None
