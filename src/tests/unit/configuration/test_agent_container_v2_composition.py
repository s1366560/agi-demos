"""V2 composition boundaries for the agent sub-container."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.application.use_cases.agent import ExecuteStepUseCase
from src.configuration.containers.agent_container import AgentContainer

pytestmark = pytest.mark.unit


def test_execute_step_use_case_does_not_mutate_process_tool_runtime() -> None:
    """The legacy use case must not configure tools owned by a V2 generation."""
    container = AgentContainer(redis_client=MagicMock())
    llm = MagicMock()

    with (
        patch(
            "src.infrastructure.plugins.v2.sandbox_projection."
            "current_sandbox_application_services_v2"
        ) as sandbox_projection,
        patch.object(container, "graph_orchestrator") as graph_orchestrator,
    ):
        use_case = container.execute_step_use_case(llm)

    assert isinstance(use_case, ExecuteStepUseCase)
    sandbox_projection.assert_not_called()
    graph_orchestrator.assert_not_called()
