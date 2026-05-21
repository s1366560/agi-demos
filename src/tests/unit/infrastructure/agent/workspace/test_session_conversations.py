from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import WorkspaceModel
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)
from src.infrastructure.agent.workspace import session_conversations

pytestmark = pytest.mark.unit


async def test_ensure_workspace_llm_conversation_creates_workspace_linked_session(
    db_session: AsyncSession,
    test_project_db,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = WorkspaceModel(
        id="workspace-llm-session-1",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        name="LLM Session Workspace",
        created_by=test_user.id,
    )
    db_session.add(workspace)
    await db_session.commit()

    @asynccontextmanager
    async def fake_session_factory():
        yield db_session

    monkeypatch.setattr(
        session_conversations,
        "async_session_factory",
        fake_session_factory,
    )

    persisted = await session_conversations.ensure_workspace_llm_conversation(
        conversation_id="workspace-gate-session-1",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        workspace_id=workspace.id,
        agent_id="builtin:workspace-verifier",
        title="Workspace Verification Gate - node-1",
        stage="verification_judge",
        linked_workspace_task_id="task-1",
        metadata={"current_plan_node_id": "node-1"},
    )

    conversation = await SqlConversationRepository(db_session).find_by_id(
        "workspace-gate-session-1"
    )

    assert persisted is True
    assert conversation is not None
    assert conversation.workspace_id == workspace.id
    assert conversation.linked_workspace_task_id == "task-1"
    assert conversation.agent_config["selected_agent_id"] == "builtin:workspace-verifier"
    assert conversation.metadata["workspace_llm_stage"] == "verification_judge"
    assert conversation.metadata["current_plan_node_id"] == "node-1"
