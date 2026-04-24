from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.model.agent.conversation.conversation import Conversation
from src.domain.model.agent.conversation.conversation_mode import ConversationMode
from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.infrastructure.adapters.primary.web.routers.agent.participants import (
    _roster_response,
    list_mention_candidates,
    set_focused_agent,
)


def _conversation() -> Conversation:
    return Conversation(
        id="conv-1",
        project_id="proj-1",
        tenant_id="tenant-1",
        user_id="user-1",
        title="Roster conversation",
        participant_agents=["agent-1"],
        conversation_mode=ConversationMode.MULTI_AGENT_SHARED,
        workspace_id="ws-1",
        created_at=datetime.now(UTC),
    )


def _binding() -> WorkspaceAgent:
    return WorkspaceAgent(
        id="binding-1",
        workspace_id="ws-1",
        agent_id="agent-1",
        display_name="Worker A",
        is_active=True,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_roster_response_includes_workspace_binding_projection() -> None:
    conversation = _conversation()
    workspace_agent_repo = MagicMock()
    workspace_agent_repo.find_by_workspace_and_agent_id = AsyncMock(return_value=_binding())
    container = SimpleNamespace(workspace_agent_repository=lambda: workspace_agent_repo)
    request = MagicMock()
    db = MagicMock()

    with patch(
        "src.infrastructure.adapters.primary.web.routers.agent.participants.get_container_with_db",
        return_value=container,
    ):
        response = await _roster_response(
            conversation,
            ConversationMode.MULTI_AGENT_SHARED,
            request=request,
            db=db,
        )

    assert response.participant_agents == ["agent-1"]
    assert response.participant_bindings[0].workspace_agent_id == "binding-1"
    assert response.participant_bindings[0].display_name == "Worker A"
    assert response.participant_bindings[0].source == "workspace"


@pytest.mark.asyncio
async def test_list_mention_candidates_includes_workspace_binding_projection() -> None:
    conversation = _conversation()
    project = SimpleNamespace(owner_id="user-1")
    request = MagicMock()
    db = MagicMock()
    current_user = SimpleNamespace(id="user-1")
    mention_candidate = SimpleNamespace(
        agent_id="agent-1",
        workspace_agent_id="binding-1",
        display_name="Worker A",
        label="alpha",
        status="idle",
        is_active=True,
        source="workspace",
    )
    container = SimpleNamespace(workspace_agent_repository=lambda: MagicMock())

    with (
        patch(
            "src.infrastructure.adapters.primary.web.routers.agent.participants._load_conversation_and_project",
            AsyncMock(return_value=(MagicMock(), conversation, project)),
        ),
        patch(
            "src.infrastructure.adapters.primary.web.routers.agent.participants.get_container_with_db",
            return_value=container,
        ),
        patch(
            "src.application.services.agent.workspace_mention_candidates.WorkspaceMentionCandidatesResolver",
        ) as resolver_cls,
    ):
        resolver_cls.return_value.resolve = AsyncMock(return_value=[mention_candidate])

        response = await list_mention_candidates(
            conversation_id="conv-1",
            request=request,
            include_inactive=False,
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        )

    assert response.workspace_id == "ws-1"
    assert response.source == "workspace"
    assert response.candidates[0].workspace_agent_id == "binding-1"


@pytest.mark.asyncio
async def test_set_focused_agent_updates_conversation_and_returns_roster() -> None:
    conversation = _conversation()
    project = SimpleNamespace(owner_id="user-1")
    request = MagicMock()
    db = MagicMock()
    db.commit = AsyncMock()
    current_user = SimpleNamespace(id="user-1")
    conv_repo = MagicMock()
    conv_repo.save = AsyncMock()
    workspace_agent_repo = MagicMock()
    workspace_agent_repo.find_by_workspace_and_agent_id = AsyncMock(return_value=_binding())
    container = SimpleNamespace(workspace_agent_repository=lambda: workspace_agent_repo)

    with (
        patch(
            "src.infrastructure.adapters.primary.web.routers.agent.participants._load_conversation_and_project",
            AsyncMock(return_value=(conv_repo, conversation, project)),
        ),
        patch(
            "src.infrastructure.adapters.primary.web.routers.agent.participants.get_container_with_db",
            return_value=container,
        ),
    ):
        response = await set_focused_agent(
            conversation_id="conv-1",
            data=SimpleNamespace(agent_id="agent-1"),
            request=request,
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        )

    conv_repo.save.assert_awaited_once_with(conversation)
    db.commit.assert_awaited_once()
    assert conversation.focused_agent_id == "agent-1"
    assert response.focused_agent_id == "agent-1"
