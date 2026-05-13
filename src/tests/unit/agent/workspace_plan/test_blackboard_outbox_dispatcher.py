"""Tests for BlackboardOutboxDispatcher control flow."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import (
    WorkspaceBlackboardOutboxModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_blackboard_outbox_repository import (
    SqlBlackboardOutboxRepository,
)
from src.infrastructure.agent.workspace_plan.blackboard_outbox_dispatcher import (
    BlackboardOutboxDispatcher,
)


@pytest.fixture
def session_factory(db_session: AsyncSession) -> Any:
    """Return a context-manager factory that always yields the shared test session.

    The unit test environment uses a single in-memory SQLite session; multiple
    commits on it are safe because ``expire_on_commit=False``. The outbox table
    does not require any seeded tenant/workspace rows because there are no FKs
    from the outbox to those tables.
    """

    @asynccontextmanager
    async def _factory() -> Any:
        yield db_session

    return _factory


async def _enqueue(session_factory: Any, *, event_type: str = "blackboard.file.uploaded") -> str:
    async with session_factory() as session:
        repo = SqlBlackboardOutboxRepository(session)
        item = await repo.enqueue(
            workspace_id="workspace-1",
            tenant_id="tenant-1",
            project_id="project-1",
            event_type=event_type,
            payload={"k": "v"},
        )
        await session.commit()
        return item.id


@pytest.mark.unit
async def test_run_once_publishes_then_marks_dispatched(session_factory: Any) -> None:
    """Happy path: a single pending row is published and marked dispatched."""
    published: list[WorkspaceBlackboardOutboxModel] = []

    async def publisher(item: WorkspaceBlackboardOutboxModel) -> None:
        published.append(item)

    outbox_id = await _enqueue(session_factory)
    dispatcher = BlackboardOutboxDispatcher(
        session_factory=session_factory,
        redis_client=None,
        publisher=publisher,
    )

    processed = await dispatcher.run_once()
    assert processed == 1
    assert [item.id for item in published] == [outbox_id]

    async with session_factory() as session:
        repo = SqlBlackboardOutboxRepository(session)
        row = await repo.get_by_id(outbox_id)
    assert row is not None
    assert row.status == "dispatched"


@pytest.mark.unit
async def test_run_once_marks_failed_on_publisher_error(session_factory: Any) -> None:
    """When the publisher raises, the row should be marked failed for retry."""

    async def publisher(item: WorkspaceBlackboardOutboxModel) -> None:
        raise RuntimeError("redis down")

    outbox_id = await _enqueue(session_factory)
    dispatcher = BlackboardOutboxDispatcher(
        session_factory=session_factory,
        redis_client=None,
        publisher=publisher,
    )

    processed = await dispatcher.run_once()
    assert processed == 1

    async with session_factory() as session:
        repo = SqlBlackboardOutboxRepository(session)
        row = await repo.get_by_id(outbox_id)
    assert row is not None
    assert row.status == "failed"
    assert row.last_error == "redis down"
    assert row.next_attempt_at is not None


@pytest.mark.unit
async def test_run_once_empty_returns_zero(session_factory: Any) -> None:
    dispatcher = BlackboardOutboxDispatcher(
        session_factory=session_factory,
        redis_client=None,
        publisher=lambda _item: (_ for _ in ()).throw(  # type: ignore[arg-type, return-value]
            AssertionError("publisher should not be called")
        ),
    )
    assert await dispatcher.run_once() == 0


@pytest.mark.unit
async def test_run_once_drains_full_batch(session_factory: Any) -> None:
    """A run should process every claimed item, not just the first."""
    seen: list[str] = []

    async def publisher(item: WorkspaceBlackboardOutboxModel) -> None:
        seen.append(item.id)

    ids = [await _enqueue(session_factory) for _ in range(3)]
    dispatcher = BlackboardOutboxDispatcher(
        session_factory=session_factory,
        redis_client=None,
        publisher=publisher,
        batch_size=10,
    )
    processed = await dispatcher.run_once()
    assert processed == 3
    assert set(seen) == set(ids)


@pytest.mark.unit
async def test_run_once_uses_event_port_when_no_publisher(session_factory: Any) -> None:
    """Dispatcher with an injected ``event_port`` routes via the port."""
    from src.domain.events.types import AgentEventType
    from src.domain.ports.services.blackboard_event_port import BlackboardEventPort

    calls: list[dict[str, Any]] = []

    class _RecordingPort(BlackboardEventPort):
        async def publish(  # type: ignore[override]
            self,
            *,
            workspace_id: str,
            event_type: AgentEventType,
            payload: dict[str, Any],
            metadata: dict[str, Any] | None = None,
            correlation_id: str | None = None,
        ) -> str | None:
            calls.append(
                {
                    "workspace_id": workspace_id,
                    "event_type": event_type,
                    "payload": payload,
                    "metadata": metadata or {},
                    "correlation_id": correlation_id,
                }
            )
            return "1-0"

        async def stream_since(  # type: ignore[override]
            self,
            *,
            workspace_id: str,
            last_id: str = "0",
            limit: int = 100,
        ) -> list[dict[str, Any]]:
            return []

    outbox_id = await _enqueue(session_factory, event_type="blackboard_file_created")
    dispatcher = BlackboardOutboxDispatcher(
        session_factory=session_factory,
        redis_client=None,
        event_port=_RecordingPort(),
    )
    processed = await dispatcher.run_once()
    assert processed == 1
    assert len(calls) == 1
    assert calls[0]["workspace_id"] == "workspace-1"
    assert calls[0]["event_type"] == AgentEventType.BLACKBOARD_FILE_CREATED
    assert calls[0]["payload"] == {"k": "v"}

    async with session_factory() as session:
        repo = SqlBlackboardOutboxRepository(session)
        row = await repo.get_by_id(outbox_id)
    assert row is not None
    assert row.status == "dispatched"
