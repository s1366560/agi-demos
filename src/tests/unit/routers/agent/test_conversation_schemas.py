from datetime import UTC, datetime

from src.domain.model.agent.conversation.conversation import Conversation
from src.domain.model.agent.conversation.conversation_mode import ConversationMode
from src.infrastructure.adapters.primary.web.routers.agent.schemas import (
    ConversationResponse,
)


def test_conversation_response_from_domain_includes_participation_projection() -> None:
    conversation = Conversation(
        id="conv-1",
        project_id="proj-1",
        tenant_id="tenant-1",
        user_id="user-1",
        title="Conversation",
        participant_agents=["agent-a", "agent-b"],
        coordinator_agent_id="agent-a",
        focused_agent_id="agent-b",
        conversation_mode=ConversationMode.MULTI_AGENT_ISOLATED,
        workspace_id="ws-1",
        linked_workspace_task_id="task-1",
        created_at=datetime.now(UTC),
    )

    response = ConversationResponse.from_domain(conversation)

    assert response.participant_agents == ["agent-a", "agent-b"]
    assert response.coordinator_agent_id == "agent-a"
    assert response.focused_agent_id == "agent-b"


def test_conversation_response_from_domain_includes_workspace_projection() -> None:
    conversation = Conversation(
        id="workspace-verifier:ws-from-id:task-from-id:agent-a:attempt-1",
        project_id="proj-1",
        tenant_id="tenant-1",
        user_id="user-1",
        title="Workspace Verification Gate - task-from-id",
        created_at=datetime.now(UTC),
    )

    response = ConversationResponse.from_domain(
        conversation,
        workspace_id="ws-from-id",
        linked_workspace_task_id="task-from-id",
        workspace_name="Workspace From API",
    )

    assert response.workspace_id == "ws-from-id"
    assert response.linked_workspace_task_id == "task-from-id"
    assert response.workspace_name == "Workspace From API"


def test_conversation_response_from_domain_includes_child_session_markers() -> None:
    conversation = Conversation(
        id="child-session",
        project_id="proj-1",
        tenant_id="tenant-1",
        user_id="user-1",
        title="Agent session",
        metadata={"spawned_by_agent_id": "agent-a", "spawned_agent_id": "agent-b"},
        parent_conversation_id="parent-session",
        branch_point_message_id="message-1",
        created_at=datetime.now(UTC),
    )

    response = ConversationResponse.from_domain(conversation)

    assert response.parent_conversation_id == "parent-session"
    assert response.branch_point_message_id == "message-1"
    assert response.metadata == {
        "spawned_by_agent_id": "agent-a",
        "spawned_agent_id": "agent-b",
    }
