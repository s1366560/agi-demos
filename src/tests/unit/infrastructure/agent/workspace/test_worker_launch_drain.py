"""Unit tests for :mod:`worker_launch_drain`.

Regression anchors: the drain helper is the single path that converts
``WorkspaceTaskCommandService._pending_worker_launches`` into durable outbox
events. Skipping it leaves assigned execution tasks stranded with no
conversation (the ``2c11849d-…`` stuck-workspace bug).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.workspace_task_command_service import (
    WorkspaceTaskCommandService,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    User,
    WorkspaceModel,
    WorkspacePlanOutboxModel,
)
from src.infrastructure.agent.workspace import worker_launch_drain
from src.infrastructure.agent.workspace_plan.outbox_handlers import WORKER_LAUNCH_EVENT


@dataclass
class _FakeTask:
    id: str
    workspace_id: str
    assignee_agent_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


async def _seed_workspace(
    db_session: AsyncSession,
    *,
    project: Project,
    user: User,
) -> None:
    db_session.add(
        WorkspaceModel(
            id="workspace-1",
            tenant_id=project.tenant_id,
            project_id=project.id,
            name="Workspace",
            description="",
            created_by=user.id,
            is_archived=False,
            metadata_json={},
        )
    )
    await db_session.flush()


@pytest.mark.unit
class TestDrainPendingWorkerLaunches:
    @pytest.mark.asyncio
    async def test_async_drain_enqueues_worker_launch_outbox_without_plan(
        self,
        db_session: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        await _seed_workspace(db_session, project=test_project_db, user=test_user)
        command_service = WorkspaceTaskCommandService(AsyncMock())
        task = _FakeTask(id="wt-queued", workspace_id="workspace-1", assignee_agent_id="agent-1")
        command_service._pending_worker_launches.append((task, "user-1", "leader-1"))

        fired = await worker_launch_drain.drain_pending_worker_launches_to_outbox(
            command_service,
            db_session,
        )

        assert fired == 1
        outbox_items = list(
            (
                await db_session.execute(
                    select(WorkspacePlanOutboxModel).where(
                        WorkspacePlanOutboxModel.event_type == WORKER_LAUNCH_EVENT
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(outbox_items) == 1
        item = outbox_items[0]
        assert item.plan_id is None
        assert item.workspace_id == "workspace-1"
        assert item.payload_json["task_id"] == "wt-queued"
        assert item.payload_json["worker_agent_id"] == "agent-1"
        assert item.payload_json["actor_user_id"] == "user-1"
        assert item.payload_json["leader_agent_id"] == "leader-1"
        assert item.metadata_json["source"] == "workspace.worker_launch_drain"

    @pytest.mark.asyncio
    async def test_async_drain_raises_when_outbox_enqueue_fails(
        self,
        db_session: AsyncSession,
        test_project_db: Project,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await _seed_workspace(db_session, project=test_project_db, user=test_user)

        async def boom(*args: object, **kwargs: object) -> object:
            raise RuntimeError("outbox down")

        monkeypatch.setattr(worker_launch_drain, "_enqueue_worker_launch", boom)
        command_service = WorkspaceTaskCommandService(AsyncMock())
        task = _FakeTask(id="wt-direct", workspace_id="workspace-1", assignee_agent_id="agent-1")
        command_service._pending_worker_launches.append((task, "user-1", None))

        with pytest.raises(RuntimeError, match="outbox down"):
            await worker_launch_drain.drain_pending_worker_launches_to_outbox(
                command_service,
                db_session,
            )
