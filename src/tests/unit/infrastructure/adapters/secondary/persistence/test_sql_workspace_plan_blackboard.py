"""Tests for the durable workspace plan blackboard adapter."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.services.blackboard_port import BlackboardEntry
from src.infrastructure.adapters.secondary.persistence.models import PlanModel
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_blackboard import (
    SqlWorkspacePlanBlackboard,
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
async def test_put_get_returns_latest_version(
    db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> None:
    await _seed_plan(db_session, "workspace-1", "bb-plan-1")
    blackboard = SqlWorkspacePlanBlackboard(db_session)

    v1 = await blackboard.put(
        BlackboardEntry(
            plan_id="bb-plan-1",
            key="research.summary",
            value={"summary": "first"},
            published_by="agent-a",
            schema_ref="schema://summary/v1",
            metadata={"node_id": "task-1"},
        )
    )
    v2 = await blackboard.put(
        BlackboardEntry(
            plan_id="bb-plan-1",
            key="research.summary",
            value={"summary": "second"},
            published_by="agent-b",
        )
    )
    await db_session.commit()

    assert v1 == 1
    assert v2 == 2

    loaded = await blackboard.get("bb-plan-1", "research.summary")
    assert loaded is not None
    assert loaded.version == 2
    assert loaded.value == {"summary": "second"}
    assert loaded.published_by == "agent-b"


@pytest.mark.asyncio
async def test_list_returns_latest_entry_per_key(
    db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> None:
    await _seed_plan(db_session, "workspace-1", "bb-plan-1")
    blackboard = SqlWorkspacePlanBlackboard(db_session)

    await blackboard.put(
        BlackboardEntry(plan_id="bb-plan-1", key="artifact.a", value="old", published_by="agent-a")
    )
    await blackboard.put(
        BlackboardEntry(plan_id="bb-plan-1", key="artifact.b", value="only", published_by="agent-b")
    )
    await blackboard.put(
        BlackboardEntry(plan_id="bb-plan-1", key="artifact.a", value="new", published_by="agent-a")
    )
    await db_session.commit()

    entries = await blackboard.list("bb-plan-1")
    by_key = {entry.key: entry for entry in entries}

    assert sorted(by_key) == ["artifact.a", "artifact.b"]
    assert by_key["artifact.a"].value == "new"
    assert by_key["artifact.a"].version == 2
    assert by_key["artifact.b"].value == "only"
    assert by_key["artifact.b"].version == 1


@pytest.mark.asyncio
async def test_entries_are_scoped_by_plan(
    db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> None:
    await _seed_plan(db_session, "workspace-1", "bb-plan-1")
    await _seed_plan(db_session, "workspace-1", "bb-plan-2")
    blackboard = SqlWorkspacePlanBlackboard(db_session)

    await blackboard.put(
        BlackboardEntry(plan_id="bb-plan-1", key="shared", value="plan-one", published_by="agent-a")
    )
    await blackboard.put(
        BlackboardEntry(plan_id="bb-plan-2", key="shared", value="plan-two", published_by="agent-b")
    )
    await db_session.commit()

    plan_one = await blackboard.get("bb-plan-1", "shared")
    plan_two = await blackboard.get("bb-plan-2", "shared")

    assert plan_one is not None
    assert plan_two is not None
    assert plan_one.value == "plan-one"
    assert plan_two.value == "plan-two"
