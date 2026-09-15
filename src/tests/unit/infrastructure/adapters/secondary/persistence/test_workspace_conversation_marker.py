"""The task-session protocol marker must survive repository and cache round trips."""

import pytest

from src.domain.model.agent.conversation.conversation import Conversation as DomainConversation
from src.domain.model.agent.conversation.conversation_mode import ConversationMode
from src.infrastructure.adapters.primary.web.workspace_core_task_sessions import _new_conversation
from src.infrastructure.adapters.secondary.persistence.models import Conversation
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)


@pytest.mark.unit
async def test_task_session_marker_survives_real_repository_save(
    test_db, test_project_db, test_user, caplog
):
    row = _new_conversation(
        conversation_id="workspace-marker",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        actor_id=test_user.id,
        title="Marker",
        capability_mode="work",
        workspace_id="exact-workspace",
        receipt_id="receipt",
        message_id="turn",
        payload_hash="hash",
        idempotency_key="key",
    )
    test_db.add(row)
    await test_db.commit()
    repo = SqlConversationRepository(test_db)
    domain = await repo.find_by_id(row.id)
    assert domain.conversation_mode is None
    assert domain.current_mode.value == "plan"
    assert domain.workspace_id == "exact-workspace"
    assert domain.resolve_mode(ConversationMode.SINGLE_AGENT) == ConversationMode.SINGLE_AGENT
    domain.title = "Changed title"
    await repo.save(domain)
    await test_db.commit()
    test_db.expire_all()
    persisted = await test_db.get(Conversation, "workspace-marker")
    assert persisted.conversation_mode == "workspace"
    assert persisted.current_mode == "plan"
    assert persisted.agent_config["capability_mode"] == "work"
    assert "Ignoring unknown persisted conversation mode" not in caplog.text
    payload = domain.to_dict()
    assert payload["conversation_mode"] == "workspace"
    cached = DomainConversation.from_dict(payload)
    assert cached.conversation_mode is None
    assert repo._to_db(cached).conversation_mode == "workspace"


@pytest.mark.unit
@pytest.mark.parametrize("raw", ["single_agent", "multi_agent_shared", "multi_agent_isolated"])
def test_explicit_collaboration_mode_retains_existing_semantics(raw):
    row = _new_conversation(
        conversation_id="no-db",
        tenant_id="tenant",
        project_id="project",
        actor_id="actor",
        title="Mode",
        capability_mode="work",
        workspace_id="ws",
        receipt_id="receipt",
        message_id="turn",
        payload_hash="hash",
        idempotency_key="key",
    )
    repo = object.__new__(SqlConversationRepository)
    domain = repo._to_domain(row)
    domain.conversation_mode = ConversationMode(raw)
    assert repo._to_db(domain).conversation_mode == raw
    assert domain.to_dict()["conversation_mode"] == raw


@pytest.mark.unit
def test_other_unknown_mode_is_not_accepted_as_workspace(caplog):
    row = _new_conversation(
        conversation_id="no-db",
        tenant_id="tenant",
        project_id="project",
        actor_id="actor",
        title="Mode",
        capability_mode="work",
        workspace_id="ws",
        receipt_id="receipt",
        message_id="turn",
        payload_hash="hash",
        idempotency_key="key",
    )
    row.conversation_mode = "future-unknown"
    repo = object.__new__(SqlConversationRepository)
    domain = repo._to_domain(row)
    assert domain.conversation_mode is None
    assert repo._to_db(domain).conversation_mode is None
    assert "Ignoring unknown persisted conversation mode" in caplog.text
