"""Retirement tests for the historical Python Plan V2 kickoff bridge."""

from __future__ import annotations

import pytest

from src.infrastructure.agent.workspace.goal_runtime.v2_bridge import (
    LegacyWorkspacePlanRuntimeRetiredError,
    kickoff_v2_plan,
    reset_orchestrator_singleton_for_testing,
    set_orchestrator_singleton_for_testing,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_orchestrator_singleton_for_testing()
    yield
    reset_orchestrator_singleton_for_testing()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_production_kickoff_fails_closed_without_sql_fallback() -> None:
    with pytest.raises(
        LegacyWorkspacePlanRuntimeRetiredError,
        match="Avernet Workspace Core",
    ):
        await kickoff_v2_plan(
            workspace_id="workspace-1",
            title="Ship feature",
            created_by="user-1",
            root_task_id="task-1",
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_explicit_in_memory_test_seam_remains_available() -> None:
    class _InMemoryOrchestrator:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        async def start_goal(self, **kwargs: str) -> object:
            self.calls.append(dict(kwargs))
            return object()

    orchestrator = _InMemoryOrchestrator()
    set_orchestrator_singleton_for_testing(orchestrator)  # type: ignore[arg-type]

    started = await kickoff_v2_plan(
        workspace_id="workspace-1",
        title="Ship feature",
        description="First slice",
        created_by="user-1",
    )

    assert started is True
    assert orchestrator.calls == [
        {
            "workspace_id": "workspace-1",
            "title": "Ship feature",
            "description": "First slice",
            "created_by": "user-1",
        }
    ]
