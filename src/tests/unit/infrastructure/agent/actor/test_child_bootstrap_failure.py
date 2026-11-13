"""A child that never starts is failed with a parent-visible cause."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.application.services.agent.runtime_bootstrapper import _settle_local_bootstrap_failure
from src.domain.model.agent.spawn_mode import SpawnMode
from src.infrastructure.agent.actor import execution
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


@pytest.mark.unit
async def test_failed_session_child_does_not_stay_running() -> None:
    orchestrator = SimpleNamespace(
        get_spawn_record=AsyncMock(
            return_value=SimpleNamespace(mode=SpawnMode.SESSION, status="running")
        )
    )
    with patch(
        "src.infrastructure.plugins.v2.agent_worker_runtime.current_agent_orchestrator_v2",
        return_value=orchestrator,
    ):
        status = await execution._resolve_child_terminal_status(
            child_session_id="child",
            success=False,
        )
    assert status == "failed"


@pytest.mark.unit
async def test_successful_session_child_stays_running() -> None:
    orchestrator = SimpleNamespace(
        get_spawn_record=AsyncMock(
            return_value=SimpleNamespace(mode=SpawnMode.SESSION, status="running")
        )
    )
    with patch(
        "src.infrastructure.plugins.v2.agent_worker_runtime.current_agent_orchestrator_v2",
        return_value=orchestrator,
    ):
        status = await execution._resolve_child_terminal_status(
            child_session_id="child",
            success=True,
        )
    assert status == "running"


@pytest.mark.unit
async def test_bootstrap_failure_names_the_cause_for_the_parent() -> None:
    finalize = AsyncMock()
    error = RuntimeV2Error("route_generation_unavailable", "route table missing")
    with (
        patch.object(execution, "_finalize_child_session_result", new=finalize),
        patch(
            "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
            return_value=SimpleNamespace(),
        ),
    ):
        await execution.publish_child_bootstrap_failure(
            agent_id="child-agent",
            child_session_id="child",
            request_message_id="message",
            parent_session_id="parent",
            project_id="project",
            error=error,
        )
    kwargs = finalize.await_args.kwargs
    assert kwargs["success"] is False
    assert kwargs["parent_session_id"] == "parent"
    assert "failure_class=backend" in kwargs["error_message"]
    assert "route_generation_unavailable" in kwargs["error_message"]
    assert "60" not in kwargs["error_message"]


@pytest.mark.unit
async def test_local_bootstrap_failure_is_visible_to_the_parent() -> None:
    request = SimpleNamespace(
        conversation_id="child",
        canonical_run_id="run",
        message_id="run",
        agent_id="child-agent",
        parent_session_id="parent",
    )
    config = SimpleNamespace(tenant_id="tenant", project_id="project")
    with (
        patch.object(execution, "_settle_root_run_authority", new=AsyncMock()),
        patch.object(execution, "publish_child_bootstrap_failure", new=AsyncMock()) as publish,
    ):
        await _settle_local_bootstrap_failure(config, request, RuntimeError("admission failed"))
    publish.assert_awaited_once()
    assert publish.await_args.kwargs["parent_session_id"] == "parent"
    assert publish.await_args.kwargs["child_session_id"] == "child"
