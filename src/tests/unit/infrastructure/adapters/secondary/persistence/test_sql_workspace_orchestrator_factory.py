"""Tests for SQL-backed Workspace V2 orchestrator wiring."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace_plan import PlanNodeKind
from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import (
    SqlPlanRepository,
)
from src.infrastructure.agent.workspace_plan import (
    OrchestratorConfig,
    build_sql_orchestrator,
)


@pytest.mark.asyncio
async def test_build_sql_orchestrator_persists_started_goal(
    db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> None:
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )

    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Durable blackboard goal",
        created_by=workspace_test_seed["owner_user_id"],
    )
    await orchestrator.stop_goal("workspace-1")
    await db_session.commit()

    repo = SqlPlanRepository(db_session)
    loaded = await repo.get(plan.id)

    assert loaded is not None
    assert loaded.workspace_id == "workspace-1"
    assert loaded.goal_id == plan.goal_id
    assert any(node.kind is PlanNodeKind.GOAL for node in loaded.nodes.values())
    assert any(node.kind is PlanNodeKind.TASK for node in loaded.nodes.values())
