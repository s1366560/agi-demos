"""Tests for SqlBlackboardOutboxRepository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import (
    WorkspaceBlackboardOutboxModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_blackboard_outbox_repository import (
    SqlBlackboardOutboxRepository,
)


@pytest.fixture
def outbox_repo(v2_db_session: AsyncSession) -> SqlBlackboardOutboxRepository:
    return SqlBlackboardOutboxRepository(v2_db_session)


async def _enqueue(
    repo: SqlBlackboardOutboxRepository,
    *,
    workspace_id: str = "workspace-1",
    tenant_id: str = "tenant-1",
    project_id: str = "project-1",
    event_type: str = "blackboard.file.uploaded",
    max_attempts: int = 10,
) -> WorkspaceBlackboardOutboxModel:
    return await repo.enqueue(
        workspace_id=workspace_id,
        tenant_id=tenant_id,
        project_id=project_id,
        event_type=event_type,
        payload={"k": "v"},
        metadata={"m": True},
        correlation_id="corr-1",
        max_attempts=max_attempts,
    )


@pytest.mark.unit
async def test_enqueue_persists_pending_row(
    outbox_repo: SqlBlackboardOutboxRepository,
    workspace_test_seed: dict[str, str],
) -> None:
    item = await _enqueue(outbox_repo)
    assert item.status == "pending"
    assert item.attempt_count == 0
    assert item.next_attempt_at is None
    fetched = await outbox_repo.get_by_id(item.id)
    assert fetched is not None
    assert fetched.event_type == "blackboard.file.uploaded"
    assert fetched.payload_json == {"k": "v"}


@pytest.mark.unit
async def test_claim_due_locks_and_increments_attempt(
    outbox_repo: SqlBlackboardOutboxRepository,
    workspace_test_seed: dict[str, str],
) -> None:
    item = await _enqueue(outbox_repo)
    claimed = await outbox_repo.claim_due(limit=10)
    assert [c.id for c in claimed] == [item.id]
    assert claimed[0].attempt_count == 1


@pytest.mark.unit
async def test_mark_dispatched_clears_pending(
    outbox_repo: SqlBlackboardOutboxRepository,
    workspace_test_seed: dict[str, str],
) -> None:
    item = await _enqueue(outbox_repo)
    await outbox_repo.claim_due(limit=10)
    ok = await outbox_repo.mark_dispatched(item.id)
    assert ok is True
    fetched = await outbox_repo.get_by_id(item.id)
    assert fetched is not None
    assert fetched.status == "dispatched"
    assert fetched.dispatched_at is not None
    assert fetched.next_attempt_at is None
    # Subsequent claim should not return dispatched rows.
    redo = await outbox_repo.claim_due(limit=10)
    assert redo == []


@pytest.mark.unit
async def test_mark_failed_applies_exponential_backoff(
    outbox_repo: SqlBlackboardOutboxRepository,
    workspace_test_seed: dict[str, str],
) -> None:
    item = await _enqueue(outbox_repo)
    # First claim → attempt_count = 1
    await outbox_repo.claim_due(limit=10)
    now = datetime.now(UTC)
    ok = await outbox_repo.mark_failed(item.id, "boom", now=now)
    assert ok is True
    fetched = await outbox_repo.get_by_id(item.id)
    assert fetched is not None
    assert fetched.status == "failed"
    assert fetched.last_error == "boom"
    # backoff = min(2 ** attempt_count, 300) = 2
    expected = now + timedelta(seconds=2)
    assert fetched.next_attempt_at is not None
    # SQLite drops timezone info — compare naive forms when needed.
    actual = fetched.next_attempt_at
    if actual.tzinfo is None:
        actual = actual.replace(tzinfo=UTC)
    delta = abs((actual - expected).total_seconds())
    assert delta <= 2


@pytest.mark.unit
async def test_mark_failed_dead_letter_at_max_attempts(
    outbox_repo: SqlBlackboardOutboxRepository,
    workspace_test_seed: dict[str, str],
) -> None:
    item = await _enqueue(outbox_repo, max_attempts=1)
    await outbox_repo.claim_due(limit=10)  # attempt_count -> 1, equals max_attempts
    ok = await outbox_repo.mark_failed(item.id, "fatal")
    assert ok is True
    fetched = await outbox_repo.get_by_id(item.id)
    assert fetched is not None
    assert fetched.status == "dead_letter"
    assert fetched.next_attempt_at is None
    # Dead-letter rows must not be re-claimed.
    again = await outbox_repo.claim_due(limit=10)
    assert again == []


@pytest.mark.unit
async def test_purge_dispatched_before_removes_old_rows(
    outbox_repo: SqlBlackboardOutboxRepository,
    v2_db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> None:
    a = await _enqueue(outbox_repo)
    b = await _enqueue(outbox_repo)
    await outbox_repo.claim_due(limit=10)
    await outbox_repo.mark_dispatched(a.id, now=datetime(2000, 1, 1, tzinfo=UTC))
    await outbox_repo.mark_dispatched(b.id, now=datetime.now(UTC))

    purged = await outbox_repo.purge_dispatched_before(
        cutoff=datetime(2010, 1, 1, tzinfo=UTC),
    )
    assert purged == 1
    remaining = (
        await v2_db_session.execute(select(WorkspaceBlackboardOutboxModel))
    ).scalars().all()
    assert {row.id for row in remaining} == {b.id}
