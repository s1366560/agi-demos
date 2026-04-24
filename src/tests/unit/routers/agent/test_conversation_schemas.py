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
