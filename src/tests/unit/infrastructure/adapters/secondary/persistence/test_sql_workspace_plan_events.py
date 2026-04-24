"""Tests for the durable workspace plan event repository."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import PlanModel
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_events import (
    SqlWorkspacePlanEventRepository,
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


@pytest.mark.asyncio
async def test_append_and_list_recent_roundtrips_payload(
    db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> None:
    await _seed_plan(db_session, "workspace-1", "event-plan-1")
    repo = SqlWorkspacePlanEventRepository(db_session)

    event = await repo.append(
        plan_id="event-plan-1",
        workspace_id="workspace-1",
        node_id="node-1",
        attempt_id="attempt-1",
        actor_id="worker-1",
        event_type="worker_report_terminal",
        source="worker_report",
        payload={"summary": "done"},
    )
    await db_session.commit()

    events = await repo.list_recent("event-plan-1", limit=10)

    assert [item.id for item in events] == [event.id]
    assert events[0].node_id == "node-1"
    assert events[0].attempt_id == "attempt-1"
    assert events[0].actor_id == "worker-1"
    assert events[0].event_type == "worker_report_terminal"
    assert events[0].source == "worker_report"
    assert events[0].payload == {"summary": "done"}


@pytest.mark.asyncio
async def test_list_recent_respects_limit_and_plan_scope(
    db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> None:
    await _seed_plan(db_session, "workspace-1", "event-plan-1")
    await _seed_plan(db_session, "workspace-1", "event-plan-2")
    repo = SqlWorkspacePlanEventRepository(db_session)

    first = await repo.append(
        plan_id="event-plan-1",
        workspace_id="workspace-1",
        event_type="first",
    )
    second = await repo.append(
        plan_id="event-plan-1",
        workspace_id="workspace-1",
        event_type="second",
    )
    _ = await repo.append(
        plan_id="event-plan-2",
        workspace_id="workspace-1",
        event_type="other-plan",
    )
    await db_session.commit()

    events = await repo.list_recent("event-plan-1", limit=1)

    assert len(events) == 1
    assert events[0].id in {first.id, second.id}
    assert events[0].plan_id == "event-plan-1"
