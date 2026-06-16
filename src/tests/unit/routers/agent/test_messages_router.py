"""Tests for agent message endpoints."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.domain.model.agent.conversation.conversation import Conversation as DomainConversation
from src.domain.model.agent.skill.tool_execution_record import ToolExecutionRecord
from src.infrastructure.adapters.primary.web.routers.agent.messages import (
    _get_recovery_info,
    get_conversation_execution,
    get_conversation_execution_status,
    get_conversation_messages,
    get_conversation_tool_executions,
    get_execution_stats,
    get_message_replies,
)
from src.infrastructure.adapters.secondary.persistence.models import Conversation, Message


@pytest.mark.unit
class TestAgentMessagesRouter:
    @pytest.fixture(autouse=True)
    def _clear_router_monkeypatches(self, monkeypatch: pytest.MonkeyPatch):
        self.monkeypatch = monkeypatch

    @pytest.mark.asyncio
    async def test_get_message_replies_rejects_non_owner(
        self,
        test_db,
        test_project_db,
        test_tenant_db,
        test_user,
        another_user,
    ) -> None:
        conversation = Conversation(
            id="conversation-replies",
            project_id=test_project_db.id,
            tenant_id=test_tenant_db.id,
            user_id=test_user.id,
            title="Replies",
            status="active",
            agent_config={},
            meta={},
            message_count=2,
            current_mode="build",
            merge_strategy="result_only",
            participant_agents=[],
        )
        parent = Message(
            id="message-parent",
            conversation_id=conversation.id,
            role="assistant",
            content="Parent",
            message_type="text",
        )
        reply = Message(
            id="message-reply",
            conversation_id=conversation.id,
            role="user",
            content="Private reply",
            message_type="text",
            reply_to_id=parent.id,
        )
        test_db.add_all([conversation, parent, reply])
        await test_db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await get_message_replies(
                conversation.id,
                parent.id,
                current_user=another_user,
                tenant_id=test_tenant_db.id,
                db=test_db,
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access denied"

    @pytest.mark.asyncio
    async def test_tool_executions_message_filter_stays_in_conversation(
        self, test_db, test_user, monkeypatch
    ):
        conversation = DomainConversation(
            id="conversation-tools",
            project_id="project-tools",
            tenant_id="tenant-tools",
            user_id=test_user.id,
            title="Tool executions",
        )
        allowed_record = ToolExecutionRecord(
            id="record-allowed",
            conversation_id=conversation.id,
            message_id="shared-message-id",
            call_id="call-allowed",
            tool_name="terminal",
        )
        other_conversation_record = ToolExecutionRecord(
            id="record-other",
            conversation_id="other-conversation",
            message_id="shared-message-id",
            call_id="call-other",
            tool_name="terminal",
        )
        conversation_repo = SimpleNamespace(
            find_by_id=AsyncMock(return_value=conversation),
        )
        tool_execution_repo = SimpleNamespace(
            list_by_message=AsyncMock(return_value=[allowed_record, other_conversation_record]),
        )
        container = SimpleNamespace(
            conversation_repository=lambda: conversation_repo,
            tool_execution_record_repository=lambda: tool_execution_repo,
        )
        request = MagicMock()
        monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.messages.get_container_with_db",
            lambda _request, _db: container,
        )

        response = await get_conversation_tool_executions(
            conversation.id,
            request=request,
            project_id=conversation.project_id,
            message_id="shared-message-id",
            limit=100,
            current_user=test_user,
            tenant_id=conversation.tenant_id,
            db=test_db,
        )

        assert response["total"] == 1
        assert response["tool_executions"][0]["id"] == "record-allowed"
        tool_execution_repo.list_by_message.assert_awaited_once_with(
            "shared-message-id", limit=100
        )

    @pytest.mark.asyncio
    async def test_tool_executions_rejects_cross_tenant_conversation(
        self, test_db, test_user, monkeypatch
    ):
        conversation = DomainConversation(
            id="conversation-tools-cross-tenant",
            project_id="project-tools",
            tenant_id="tenant-other",
            user_id=test_user.id,
            title="Tool executions",
        )
        conversation_repo = SimpleNamespace(
            find_by_id=AsyncMock(return_value=conversation),
        )
        tool_execution_repo = SimpleNamespace(list_by_conversation=AsyncMock(return_value=[]))
        container = SimpleNamespace(
            conversation_repository=lambda: conversation_repo,
            tool_execution_record_repository=lambda: tool_execution_repo,
        )
        request = MagicMock()
        monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.messages.get_container_with_db",
            lambda _request, _db: container,
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_tool_executions(
                conversation.id,
                request=request,
                project_id=conversation.project_id,
                message_id=None,
                limit=100,
                current_user=test_user,
                tenant_id="tenant-current",
                db=test_db,
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Conversation not found"
        tool_execution_repo.list_by_conversation.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_conversation_messages_sanitizes_internal_errors(self, test_db, test_user):
        container = SimpleNamespace(
            agent_service=lambda _llm: SimpleNamespace(
                get_conversation=AsyncMock(side_effect=RuntimeError("internal stream secret"))
            )
        )
        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.messages.get_container_with_db",
            lambda _request, _db: container,
        )
        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.messages.create_llm_client",
            AsyncMock(return_value=object()),
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_messages(
                "conversation-secret",
                request=MagicMock(),
                project_id="project-1",
                limit=50,
                from_time_us=None,
                from_counter=None,
                before_time_us=None,
                before_counter=None,
                current_user=test_user,
                tenant_id="tenant-secret",
                db=test_db,
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to get messages"
        assert "internal" not in exc_info.value.detail
        assert "tenant-secret" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_conversation_execution_sanitizes_internal_errors(self, test_db, test_user):
        container = SimpleNamespace(
            agent_service=lambda _llm: SimpleNamespace(
                get_execution_history=AsyncMock(side_effect=RuntimeError("internal exec secret"))
            )
        )
        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.messages.get_container_with_db",
            lambda _request, _db: container,
        )
        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.messages.create_llm_client",
            AsyncMock(return_value=object()),
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_execution(
                "conversation-secret",
                request=MagicMock(),
                project_id="project-1",
                limit=50,
                status_filter=None,
                tool_filter=None,
                current_user=test_user,
                tenant_id="tenant-secret",
                db=test_db,
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to get execution history"
        assert "internal" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_conversation_execution_not_found_errors_are_sanitized(
        self,
        test_db,
        test_user,
    ):
        container = SimpleNamespace(
            agent_service=lambda _llm: SimpleNamespace(
                get_execution_history=AsyncMock(side_effect=ValueError("secret conversation id"))
            )
        )
        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.messages.get_container_with_db",
            lambda _request, _db: container,
        )
        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.messages.create_llm_client",
            AsyncMock(return_value=object()),
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_execution(
                "conversation-secret",
                request=MagicMock(),
                project_id="project-1",
                limit=50,
                status_filter=None,
                tool_filter=None,
                current_user=test_user,
                tenant_id="tenant-secret",
                db=test_db,
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Conversation not found"
        assert "secret" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_tool_executions_sanitizes_internal_errors(self, test_db, test_user):
        conversation_repo = SimpleNamespace(
            find_by_id=AsyncMock(side_effect=RuntimeError("internal tool repo secret"))
        )
        container = SimpleNamespace(conversation_repository=lambda: conversation_repo)
        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.messages.get_container_with_db",
            lambda _request, _db: container,
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_tool_executions(
                "conversation-secret",
                request=MagicMock(),
                project_id="project-1",
                message_id=None,
                limit=100,
                current_user=test_user,
                tenant_id="tenant-secret",
                db=test_db,
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to get tool execution history"
        assert "internal" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_execution_status_sanitizes_internal_errors(self, test_db, test_user):
        conversation_repo = SimpleNamespace(
            find_by_id=AsyncMock(side_effect=RuntimeError("internal status secret"))
        )
        container = SimpleNamespace(conversation_repository=lambda: conversation_repo)
        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.messages.get_container_with_db",
            lambda _request, _db: container,
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_execution_status(
                "conversation-secret",
                request=MagicMock(),
                project_id="project-1",
                include_recovery_info=False,
                from_time_us=0,
                current_user=test_user,
                tenant_id="tenant-secret",
                db=test_db,
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to get execution status"
        assert "internal" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_execution_status_rejects_cross_tenant_conversation(
        self, test_db, test_user, monkeypatch
    ):
        conversation = DomainConversation(
            id="conversation-status-cross-tenant",
            project_id="project-status",
            tenant_id="tenant-other",
            user_id=test_user.id,
            title="Status",
        )
        conversation_repo = SimpleNamespace(find_by_id=AsyncMock(return_value=conversation))
        container = SimpleNamespace(
            conversation_repository=lambda: conversation_repo,
            redis_client=None,
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.messages.get_container_with_db",
            lambda _request, _db: container,
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_execution_status(
                conversation.id,
                request=MagicMock(),
                project_id=conversation.project_id,
                include_recovery_info=False,
                from_time_us=0,
                current_user=test_user,
                tenant_id="tenant-current",
                db=test_db,
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Conversation not found"

    @pytest.mark.asyncio
    async def test_recovery_info_falls_back_to_database_after_malformed_stream_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        class FakeRedis:
            async def xinfo_stream(self, _stream_key: str):
                return {"length": 1}

            async def xrevrange(self, _stream_key: str, count: int = 1):
                return [(b"1-0", {b"data": b"{not-json"})]

        class ResponseError(Exception):
            pass

        event_repo = SimpleNamespace(
            get_last_event_time=AsyncMock(return_value=(123_456, 7))
        )
        container = SimpleNamespace(agent_execution_event_repository=lambda: event_repo)
        monkeypatch.setattr("redis.asyncio.Redis", FakeRedis)
        monkeypatch.setattr("redis.asyncio.ResponseError", ResponseError)

        result = await _get_recovery_info(
            container=container,
            redis_client=FakeRedis(),
            conversation_id="conversation-1",
            message_id="message-1",
            from_time_us=0,
        )

        assert result == {
            "can_recover": True,
            "last_event_time_us": 123_456,
            "last_event_counter": 7,
            "stream_exists": False,
            "recovery_source": "database",
        }

    @pytest.mark.asyncio
    async def test_execution_stats_sanitizes_internal_errors(self, test_db, test_user):
        container = SimpleNamespace(
            agent_service=lambda _llm: SimpleNamespace(
                get_execution_history=AsyncMock(side_effect=RuntimeError("internal stats secret"))
            )
        )
        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.messages.get_container_with_db",
            lambda _request, _db: container,
        )
        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.messages.create_llm_client",
            AsyncMock(return_value=object()),
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_execution_stats(
                "conversation-secret",
                request=MagicMock(),
                project_id="project-1",
                current_user=test_user,
                tenant_id="tenant-secret",
                db=test_db,
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to get execution statistics"
        assert "internal" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_execution_stats_not_found_errors_are_sanitized(self, test_db, test_user):
        container = SimpleNamespace(
            agent_service=lambda _llm: SimpleNamespace(
                get_execution_history=AsyncMock(side_effect=ValueError("secret conversation id"))
            )
        )
        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.messages.get_container_with_db",
            lambda _request, _db: container,
        )
        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.messages.create_llm_client",
            AsyncMock(return_value=object()),
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_execution_stats(
                "conversation-secret",
                request=MagicMock(),
                project_id="project-1",
                current_user=test_user,
                tenant_id="tenant-secret",
                db=test_db,
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Conversation not found"
        assert "secret" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_message_replies_sanitizes_internal_errors(
        self, test_db, test_user, monkeypatch
    ):
        async def allow_access(*_args, **_kwargs):
            return None

        self.monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.agent.messages._verify_conversation_access",
            allow_access,
        )
        test_db.execute = AsyncMock(side_effect=RuntimeError("internal replies secret"))

        with pytest.raises(HTTPException) as exc_info:
            await get_message_replies(
                "conversation-secret",
                "message-secret",
                current_user=test_user,
                tenant_id="tenant-secret",
                db=test_db,
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to get message replies"
        assert "internal" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_message_replies_rejects_cross_tenant_owner(
        self,
        test_db,
        test_project_db,
        test_tenant_db,
        test_user,
    ) -> None:
        conversation = Conversation(
            id="conversation-replies-cross-tenant",
            project_id=test_project_db.id,
            tenant_id=test_tenant_db.id,
            user_id=test_user.id,
            title="Replies",
            status="active",
            agent_config={},
            meta={},
            message_count=0,
            current_mode="build",
            merge_strategy="result_only",
            participant_agents=[],
        )
        test_db.add(conversation)
        await test_db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await get_message_replies(
                conversation.id,
                "message-parent",
                current_user=test_user,
                tenant_id="tenant-other",
                db=test_db,
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Conversation not found"
