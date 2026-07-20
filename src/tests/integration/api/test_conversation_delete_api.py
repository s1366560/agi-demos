from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.agent import (
    conversations as conversations_router,
)
from src.infrastructure.adapters.secondary.persistence.models import Conversation


class _ConversationDeleteService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_conversation(
        self,
        *,
        conversation_id: str,
        project_id: str,
        user_id: str,
    ) -> Conversation | None:
        conversation = await self._db.get(Conversation, conversation_id)
        if (
            conversation is None
            or conversation.project_id != project_id
            or conversation.user_id != user_id
        ):
            return None
        return conversation

    async def delete_conversation(
        self,
        *,
        conversation_id: str,
        project_id: str,
        user_id: str,
    ) -> bool:
        conversation = await self.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=user_id,
        )
        assert conversation is not None
        await self._db.delete(conversation)
        await self._db.flush()
        return True


class _DeleteContainer:
    def __init__(self, db: AsyncSession) -> None:
        self._service = _ConversationDeleteService(db)

    def agent_service(self, _llm: object) -> _ConversationDeleteService:
        return self._service


async def test_delete_conversation_commits_before_returning_no_content(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
    monkeypatch,
) -> None:
    conversation = Conversation(
        id="conversation-delete-commit",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Delete me",
        status="active",
    )
    test_db.add(conversation)
    await test_db.commit()
    conversation_id = conversation.id

    monkeypatch.setattr(
        conversations_router,
        "create_llm_client",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(
        conversations_router,
        "get_container_with_db",
        lambda _request, db: _DeleteContainer(db),
    )

    response = await authenticated_async_client.delete(
        f"/api/v1/agent/conversations/{conversation_id}",
        params={"project_id": test_project_db.id},
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    test_db.expire_all()
    assert await test_db.get(Conversation, conversation_id) is None
