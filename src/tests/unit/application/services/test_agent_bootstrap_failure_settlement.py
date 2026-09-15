"""Failures before the execution loop must settle the admitted run authority."""

from unittest.mock import AsyncMock, patch

import pytest

from src.application.services.agent.runtime_bootstrapper import AgentRuntimeBootstrapper
from src.infrastructure.agent.actor.types import ProjectAgentActorConfig, ProjectChatRequest


@pytest.mark.unit
@pytest.mark.parametrize("canonical_run_id", ["run-canonical", None])
async def test_bootstrap_failure_settles_exact_run_before_publishing_error(canonical_run_id):
    bootstrapper = object.__new__(AgentRuntimeBootstrapper)
    config = ProjectAgentActorConfig(tenant_id="tenant-1", project_id="project-1")
    request = ProjectChatRequest(
        conversation_id="conversation-1",
        message_id="message-1",
        user_id="user-1",
        user_message="test",
        canonical_run_id=canonical_run_id,
    )
    order = []
    settle = AsyncMock(side_effect=lambda **_kwargs: order.append("settled"))
    publish = AsyncMock(side_effect=lambda **_kwargs: order.append("published"))
    with (
        patch(
            "src.infrastructure.agent.core.project_react_agent.ProjectReActAgent",
            side_effect=RuntimeError("snapshot staging failed"),
        ),
        patch("src.infrastructure.agent.actor.execution._settle_root_run_authority", settle),
        patch("src.infrastructure.agent.actor.execution._publish_error_event", publish),
    ):
        await bootstrapper._run_chat_local(config, request)
    settle.assert_awaited_once_with(
        tenant_id="tenant-1",
        project_id="project-1",
        conversation_id="conversation-1",
        run_id=canonical_run_id or "message-1",
        outcome="failed",
        error="Agent execution failed: snapshot staging failed",
    )
    assert order == ["settled", "published"]
