from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import WorkspaceModel
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)
from src.infrastructure.agent.state import agent_worker_state
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


async def test_ensure_workspace_llm_conversation_invalidates_conversation_list_cache(
    db_session: AsyncSession,
    test_project_db,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = WorkspaceModel(
        id="workspace-llm-session-cache",
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

    class FakeRedis:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        async def keys(self, pattern: str) -> list[str]:
            return [f"{pattern}:cached"]

        async def delete(self, *keys: str) -> None:
            self.deleted.extend(keys)

    fake_redis = FakeRedis()

    async def fake_get_redis_client() -> FakeRedis:
        return fake_redis

    monkeypatch.setattr(
        session_conversations,
        "async_session_factory",
        fake_session_factory,
    )
    monkeypatch.setattr(agent_worker_state, "get_redis_client", fake_get_redis_client)

    persisted = await session_conversations.ensure_workspace_llm_conversation(
        conversation_id="workspace-supervisor-session-cache",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        workspace_id=workspace.id,
        agent_id="builtin:workspace-supervisor",
        title="Workspace Supervisor Decision - node-1",
        stage="supervisor_decision",
        linked_workspace_task_id="task-1",
        metadata={"current_plan_node_id": "node-1"},
    )

    assert persisted is True
    assert f"conv_list:{test_project_db.id}:*:cached" in fake_redis.deleted
    assert f"conv_count:{test_project_db.id}:*:cached" in fake_redis.deleted
