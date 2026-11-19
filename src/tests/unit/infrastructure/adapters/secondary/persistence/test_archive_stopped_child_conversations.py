"""Persistence tests for archiving stopped child conversations."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import Conversation, ConversationStatus
from src.domain.model.agent.agent_mode import AgentMode
from src.domain.model.agent.spawn_mode import SpawnMode
from src.domain.model.agent.spawn_record import SpawnRecord
from src.infrastructure.adapters.secondary.persistence.archive_stopped_child_conversations import (
    archive_stopped_child_conversations,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation as DBConversation,
)
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)
from src.infrastructure.agent.orchestration.orchestrator import AgentOrchestrator
from src.infrastructure.agent.orchestration.session_registry import AgentSessionRegistry
from src.infrastructure.agent.orchestration.spawn_manager import SpawnManager


def _conversation(**overrides: object) -> Conversation:
    payload: dict[str, object] = {
        "id": "conv-root",
        "project_id": "proj-1",
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "title": "Root conversation",
        "status": ConversationStatus.ACTIVE,
        "message_count": 1,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "current_mode": AgentMode.BUILD,
    }
    payload.update(overrides)
    return Conversation(**payload)  # type: ignore[arg-type]


async def _save(session: AsyncSession, *conversations: Conversation) -> None:
    repo = SqlConversationRepository(session)
    for conversation in conversations:
        await repo.save(conversation)
    await session.commit()


@pytest.mark.asyncio
async def test_archives_active_child_and_leaves_parent_active(
    db_session: AsyncSession,
) -> None:
    parent = _conversation(id="parent-1", title="Parent")
    child = _conversation(
        id="child-1",
        title="Child",
        parent_conversation_id="parent-1",
    )
    await _save(db_session, parent, child)

    archived = await archive_stopped_child_conversations(db_session, ["child-1", "parent-1"])

    assert archived == ["child-1"]
    assert (await db_session.get(DBConversation, "child-1")).status == "archived"
    assert (await db_session.get(DBConversation, "parent-1")).status == "active"


@pytest.mark.asyncio
async def test_archive_is_idempotent_and_skips_deleted(
    db_session: AsyncSession,
) -> None:
    parent = _conversation(id="parent-2", title="Parent")
    archived_child = _conversation(
        id="child-archived",
        title="Already archived",
        parent_conversation_id="parent-2",
        status=ConversationStatus.ARCHIVED,
    )
    deleted_child = _conversation(
        id="child-deleted",
        title="Deleted",
        parent_conversation_id="parent-2",
        status=ConversationStatus.DELETED,
    )
    await _save(db_session, parent, archived_child, deleted_child)

    first = await archive_stopped_child_conversations(
        db_session, ["child-archived", "child-deleted", "missing-child"]
    )
    second = await archive_stopped_child_conversations(
        db_session, ["child-archived", "child-deleted"]
    )

    assert first == ["child-archived"]
    assert second == ["child-archived"]
    assert (await db_session.get(DBConversation, "child-archived")).status == "archived"
    assert (await db_session.get(DBConversation, "child-deleted")).status == "deleted"
    assert (await db_session.get(DBConversation, "parent-2")).status == "active"


@pytest.mark.asyncio
async def test_refuses_to_write_illegal_or_unknown_status(
    db_session: AsyncSession,
) -> None:
    parent = _conversation(id="parent-3", title="Parent")
    child = _conversation(
        id="child-unknown",
        title="Unknown status",
        parent_conversation_id="parent-3",
    )
    await _save(db_session, parent, child)
    row = await db_session.get(DBConversation, "child-unknown")
    assert row is not None
    # Simulate a unexpected persisted value without going through the enum.
    row.status = "paused"
    await db_session.commit()

    archived = await archive_stopped_child_conversations(db_session, ["child-unknown"])

    assert archived == []
    assert (await db_session.get(DBConversation, "child-unknown")).status == "paused"


@pytest.mark.asyncio
async def test_stop_agent_archives_child_on_retry_after_redis_stop(
    db_session: AsyncSession,
) -> None:
    """If spawn records are already stopped, a later stop still archives the row."""
    parent = _conversation(id="parent-4", title="Parent")
    child = _conversation(
        id="child-4",
        title="Sisyphus session",
        parent_conversation_id="parent-4",
    )
    sibling_already_archived = _conversation(
        id="child-4-old",
        title="Previous child",
        parent_conversation_id="parent-4",
        status=ConversationStatus.ARCHIVED,
    )
    await _save(db_session, parent, child, sibling_already_archived)

    spawn_manager = AsyncMock(spec=SpawnManager)
    spawn_manager.cascade_stop = AsyncMock(return_value=[])
    spawn_manager.find_descendants = AsyncMock(
        return_value=[
            SpawnRecord(
                parent_agent_id="parent-agent",
                child_agent_id="child-agent",
                child_session_id="child-4",
                project_id="proj-1",
                mode=SpawnMode.SESSION,
                status="stopped",
            )
        ]
    )
    orchestrator = AgentOrchestrator(
        agent_registry=AsyncMock(),
        session_registry=AsyncMock(spec=AgentSessionRegistry),
        spawn_manager=spawn_manager,
        message_bus=AsyncMock(),
        db_session=db_session,
    )

    result = await orchestrator.stop_agent(
        agent_id="parent-agent",
        session_id="child-4",
        project_id="proj-1",
        cascade=True,
    )

    assert result == []
    assert (await db_session.get(DBConversation, "child-4")).status == "archived"
    assert (await db_session.get(DBConversation, "parent-4")).status == "active"
    assert (await db_session.get(DBConversation, "child-4-old")).status == "archived"

    # A second stop (recovery / restart) stays idempotent.
    again = await orchestrator.stop_agent(
        agent_id="parent-agent",
        session_id="child-4",
        project_id="proj-1",
        cascade=True,
    )
    assert again == []
    assert (await db_session.get(DBConversation, "child-4")).status == "archived"
