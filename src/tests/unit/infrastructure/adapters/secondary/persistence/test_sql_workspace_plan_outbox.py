"""Tests for the durable workspace plan outbox repository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import PlanModel
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_outbox import (
    SqlWorkspacePlanOutboxRepository,
)


async def _seed_plan(db_session: AsyncSession, workspace_id: str, plan_id: str) -> None:
    db_session.add(
        PlanModel(
            id=plan_id,
            workspace_id=workspace_id,
            goal_id=f"{plan_id}-goal",
            status="active",
        )
    )
    await db_session.flush()


def _as_utc(value: datetime | None) -> datetime:
    assert value is not None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@pytest.mark.asyncio
async def test_enqueue_and_get_roundtrips_payload_and_metadata(
    db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> None:
    await _seed_plan(db_session, "workspace-1", "outbox-plan-1")
    repo = SqlWorkspacePlanOutboxRepository(db_session)

    item = await repo.enqueue(
        plan_id="outbox-plan-1",
        workspace_id="workspace-1",
        event_type="dispatch_ready_tasks",
        payload={"node_ids": ["task-1", "task-2"]},
        metadata={"source": "supervisor"},
        max_attempts=3,
    )
    await db_session.commit()

    loaded = await repo.get_by_id(item.id)
    assert loaded is not None
    assert loaded.plan_id == "outbox-plan-1"
    assert loaded.workspace_id == "workspace-1"
    assert loaded.event_type == "dispatch_ready_tasks"
    assert loaded.payload_json == {"node_ids": ["task-1", "task-2"]}
    assert loaded.metadata_json == {"source": "supervisor"}
    assert loaded.status == "pending"
    assert loaded.attempt_count == 0
    assert loaded.max_attempts == 3


@pytest.mark.asyncio
async def test_enqueue_accepts_workspace_scoped_item_without_plan(
    db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> None:
    repo = SqlWorkspacePlanOutboxRepository(db_session)

    item = await repo.enqueue(
        plan_id=None,
        workspace_id="workspace-1",
        event_type="worker_launch",
        payload={"task_id": "task-1"},
        metadata={"source": "worker_launch_drain"},
    )
    await db_session.commit()

    loaded = await repo.get_by_id(item.id)
    assert loaded is not None
    assert loaded.plan_id is None
    assert loaded.workspace_id == "workspace-1"
    assert loaded.event_type == "worker_launch"
    assert loaded.payload_json == {"task_id": "task-1"}


@pytest.mark.asyncio
async def test_claim_due_leases_only_due_items(
    db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> None:
    await _seed_plan(db_session, "workspace-1", "outbox-plan-1")
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    current_time = datetime(2026, 4, 24, 8, 0, tzinfo=UTC)

    due_item = await repo.enqueue(
        plan_id="outbox-plan-1",
        workspace_id="workspace-1",
        event_type="supervisor_tick",
    )
    future_item = await repo.enqueue(
        plan_id="outbox-plan-1",
        workspace_id="workspace-1",
        event_type="verify_node",
        next_attempt_at=current_time + timedelta(minutes=5),
    )

    claimed = await repo.claim_due(
        limit=10,
        lease_owner="worker-a",
        lease_seconds=30,
        now=current_time,
    )

    assert [item.id for item in claimed] == [due_item.id]
    assert claimed[0].status == "processing"
    assert claimed[0].attempt_count == 1
    assert claimed[0].lease_owner == "worker-a"
    assert claimed[0].lease_expires_at == current_time + timedelta(seconds=30)
    assert claimed[0].next_attempt_at is None

    not_due_yet = await repo.claim_due(
        limit=10,
        lease_owner="worker-b",
        now=current_time + timedelta(seconds=10),
    )
    assert not_due_yet == []

    loaded_future = await repo.get_by_id(future_item.id)
    assert loaded_future is not None
    assert loaded_future.status == "pending"
    assert loaded_future.attempt_count == 0


@pytest.mark.asyncio
async def test_claim_due_recovers_expired_processing_lease(
    db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> None:
    await _seed_plan(db_session, "workspace-1", "outbox-plan-1")
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    current_time = datetime(2026, 4, 24, 8, 0, tzinfo=UTC)

    item = await repo.enqueue(
        plan_id="outbox-plan-1",
        workspace_id="workspace-1",
        event_type="dispatch_ready_tasks",
    )
    first_claim = await repo.claim_due(
        limit=1,
        lease_owner="worker-a",
        lease_seconds=30,
        now=current_time,
    )
    assert [claimed.id for claimed in first_claim] == [item.id]

    second_claim = await repo.claim_due(
        limit=1,
        lease_owner="worker-b",
        lease_seconds=30,
        now=current_time + timedelta(seconds=31),
    )

    assert [claimed.id for claimed in second_claim] == [item.id]
    assert second_claim[0].lease_owner == "worker-b"
    assert second_claim[0].attempt_count == 2


@pytest.mark.asyncio
async def test_mark_completed_clears_lease_and_sets_processed_at(
    db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> None:
    await _seed_plan(db_session, "workspace-1", "outbox-plan-1")
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    current_time = datetime(2026, 4, 24, 8, 0, tzinfo=UTC)
    completed_time = current_time + timedelta(seconds=12)

    item = await repo.enqueue(
        plan_id="outbox-plan-1",
        workspace_id="workspace-1",
        event_type="verify_node",
    )
    await repo.claim_due(
        limit=1,
        lease_owner="worker-a",
        lease_seconds=30,
        now=current_time,
    )

    assert await repo.mark_completed(item.id, now=completed_time) is True

    loaded = await repo.get_by_id(item.id)
    assert loaded is not None
    assert loaded.status == "completed"
    assert loaded.lease_owner is None
    assert loaded.lease_expires_at is None
    assert loaded.last_error is None
    assert loaded.next_attempt_at is None
    assert _as_utc(loaded.processed_at) == completed_time
    assert await repo.mark_completed(item.id, now=completed_time) is False


@pytest.mark.asyncio
async def test_mark_failed_retries_then_dead_letters(
    db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> None:
    await _seed_plan(db_session, "workspace-1", "outbox-plan-1")
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    current_time = datetime(2026, 4, 24, 8, 0, tzinfo=UTC)

    item = await repo.enqueue(
        plan_id="outbox-plan-1",
        workspace_id="workspace-1",
        event_type="verify_node",
        max_attempts=2,
    )
    await repo.claim_due(
        limit=1,
        lease_owner="worker-a",
        lease_seconds=30,
        now=current_time,
    )

    assert await repo.mark_failed(item.id, "tool failed", now=current_time) is True
    first_failure = await repo.get_by_id(item.id)
    assert first_failure is not None
    assert first_failure.status == "failed"
    assert first_failure.attempt_count == 1
    assert first_failure.last_error == "tool failed"
    assert _as_utc(first_failure.next_attempt_at) == current_time + timedelta(seconds=2)

    not_due_yet = await repo.claim_due(
        limit=1,
        lease_owner="worker-b",
        now=current_time + timedelta(seconds=1),
    )
    assert not_due_yet == []

    retry = await repo.claim_due(
        limit=1,
        lease_owner="worker-b",
        lease_seconds=30,
        now=current_time + timedelta(seconds=3),
    )
    assert [claimed.id for claimed in retry] == [item.id]
    assert retry[0].attempt_count == 2

    assert (
        await repo.mark_failed(
            item.id,
            "still failed",
            now=current_time + timedelta(seconds=3),
        )
        is True
    )
    final = await repo.get_by_id(item.id)
    assert final is not None
    assert final.status == "dead_letter"
    assert final.last_error == "still failed"
    assert final.next_attempt_at is None

    after_dead_letter = await repo.claim_due(
        limit=1,
        lease_owner="worker-c",
        now=current_time + timedelta(minutes=10),
    )
    assert after_dead_letter == []


@pytest.mark.asyncio
async def test_retry_now_releases_dead_letter_for_operator_retry(
    db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> None:
    await _seed_plan(db_session, "workspace-1", "outbox-plan-1")
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    current_time = datetime(2026, 4, 24, 8, 0, tzinfo=UTC)

    item = await repo.enqueue(
        plan_id="outbox-plan-1",
        workspace_id="workspace-1",
        event_type="verify_node",
        max_attempts=1,
    )
    await repo.claim_due(limit=1, lease_owner="worker-a", now=current_time)
    assert await repo.mark_failed(item.id, "terminal failure", now=current_time) is True

    retried = await repo.retry_now(
        item.id,
        workspace_id="workspace-1",
        actor_id="operator-1",
        reason="tooling fixed",
        now=current_time + timedelta(minutes=2),
    )

    assert retried is not None
    assert retried.status == "pending"
    assert retried.attempt_count == 0
    assert retried.last_error is None
    assert retried.next_attempt_at is None
    assert retried.metadata_json["operator_retry"]["actor_id"] == "operator-1"
    assert retried.metadata_json["operator_retry"]["previous_status"] == "dead_letter"

    claimed = await repo.claim_due(
        limit=1,
        lease_owner="worker-b",
        now=current_time + timedelta(minutes=3),
    )
    assert [claimed_item.id for claimed_item in claimed] == [item.id]
