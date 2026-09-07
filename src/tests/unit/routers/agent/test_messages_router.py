"""Tests for agent message endpoints."""

from contextlib import asynccontextmanager
from inspect import getsource, signature
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from src.domain.model.agent.skill.tool_execution_record import ToolExecutionRecord
from src.infrastructure.adapters.primary.web.agent_execution_query_application_authority_v2 import (
    agent_execution_query_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.agent_message_history_http_application_authority_v2 import (
    agent_message_history_http_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.agent import messages as messages_router
from src.infrastructure.adapters.primary.web.routers.agent.messages import (
    _get_recovery_info,
    get_conversation_execution,
    get_conversation_execution_status,
    get_conversation_messages,
    get_conversation_tool_executions,
    get_execution_stats,
    get_message_replies,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Message,
    Project,
    Tenant,
    UserProject,
    UserTenant,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.session_event_log_types import SessionEventCursorV2


@pytest.mark.unit
class TestAgentMessagesRouter:
    @pytest.fixture(autouse=True)
    def _clear_router_monkeypatches(self, monkeypatch: pytest.MonkeyPatch):
        self.monkeypatch = monkeypatch

    def test_execution_queries_have_no_static_llm_or_agent_service_composition(self) -> None:
        source = getsource(get_conversation_execution) + getsource(get_execution_stats)

        assert "create_llm_client" not in source
        assert "get_container_with_db" not in source
        assert ".agent_service(" not in source

    @pytest.mark.parametrize("handler", (get_conversation_execution, get_execution_stats))
    def test_execution_queries_require_v2_application_authority(self, handler: object) -> None:
        parameters = signature(handler).parameters

        assert "request" not in parameters
        assert (
            parameters["execution_query"].default.dependency
            is agent_execution_query_application_authority_dependency_v2
        )

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
    @pytest.mark.parametrize(
        "route_name",
        ["execution", "status", "execution_stats"],
    )
    async def test_rest_conversation_routes_enforce_complete_scope_before_data_access(
        self,
        route_name: str,
        test_db,
        test_user,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        guard = AsyncMock(side_effect=HTTPException(status_code=403, detail="Access denied"))
        monkeypatch.setattr(messages_router, "_verify_conversation_access", guard)
        request = MagicMock()
        common = {
            "conversation_id": "conversation-complete-scope",
            "request": request,
            "project_id": "project-complete-scope",
            "current_user": test_user,
            "tenant_id": "tenant-complete-scope",
            "db": test_db,
        }
        query_common = {key: value for key, value in common.items() if key != "request"}
        route_calls = {
            "execution": lambda: get_conversation_execution(
                **query_common,
                limit=50,
                status_filter=None,
                tool_filter=None,
            ),
            "status": lambda: get_conversation_execution_status(
                **common,
                include_recovery_info=False,
                from_time_us=0,
            ),
            "execution_stats": lambda: get_execution_stats(**query_common),
        }

        with pytest.raises(HTTPException) as exc_info:
            await route_calls[route_name]()

        assert exc_info.value.status_code == 403
        guard.assert_awaited_once_with(
            "conversation-complete-scope",
            test_user,
            test_db,
            tenant_id="tenant-complete-scope",
            project_id="project-complete-scope",
        )

    @pytest.mark.parametrize(
        "handler",
        (get_conversation_messages, get_conversation_tool_executions),
    )
    def test_message_history_routes_require_v2_application_authority(
        self,
        handler: object,
    ) -> None:
        parameters = signature(handler).parameters

        assert "request" not in parameters
        assert "project_id" not in parameters
        assert "current_user" not in parameters
        assert "tenant_id" not in parameters
        assert "db" not in parameters
        assert (
            parameters["history"].default.dependency
            is agent_message_history_http_application_authority_dependency_v2
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("membership_model", [UserProject, UserTenant])
    async def test_conversation_scope_requires_current_project_and_tenant_memberships(
        self,
        membership_model,
        test_db,
        test_project_db,
        test_tenant_db,
        test_user,
    ) -> None:
        conversation = Conversation(
            id=f"conversation-missing-{membership_model.__tablename__}",
            project_id=test_project_db.id,
            tenant_id=test_tenant_db.id,
            user_id=test_user.id,
            title="Former membership",
            status="active",
            agent_config={},
            meta={},
            message_count=0,
            current_mode="build",
            merge_strategy="result_only",
            participant_agents=[],
        )
        test_db.add(conversation)
        await test_db.flush()

        membership_filter = (
            membership_model.project_id == test_project_db.id
            if membership_model is UserProject
            else membership_model.tenant_id == test_tenant_db.id
        )
        await test_db.execute(
            delete(membership_model).where(
                membership_model.user_id == test_user.id,
                membership_filter,
            )
        )
        await test_db.flush()

        with pytest.raises(HTTPException) as exc_info:
            await messages_router._verify_conversation_access(
                conversation.id,
                test_user,
                test_db,
                tenant_id=test_tenant_db.id,
                project_id=test_project_db.id,
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access denied"

    @pytest.mark.asyncio
    async def test_conversation_scope_requires_project_to_belong_to_conversation_tenant(
        self,
        test_db,
        test_tenant_db,
        test_user,
    ) -> None:
        project_tenant = Tenant(
            id="tenant-project-owner",
            name="Project owner tenant",
            slug="project-owner-tenant",
            owner_id=test_user.id,
        )
        project = Project(
            id="project-wrong-conversation-tenant",
            tenant_id=project_tenant.id,
            name="Wrong tenant project",
            owner_id=test_user.id,
            memory_rules={},
            graph_config={},
        )
        conversation = Conversation(
            id="conversation-wrong-project-tenant",
            project_id=project.id,
            tenant_id=test_tenant_db.id,
            user_id=test_user.id,
            title="Mismatched project tenant",
            status="active",
            agent_config={},
            meta={},
            message_count=0,
            current_mode="build",
            merge_strategy="result_only",
            participant_agents=[],
        )
        project_membership = UserProject(
            id="up-wrong-conversation-tenant",
            user_id=test_user.id,
            project_id=project.id,
            role="owner",
        )
        test_db.add_all([project_tenant, project, conversation, project_membership])
        await test_db.flush()

        with pytest.raises(HTTPException) as exc_info:
            await messages_router._verify_conversation_access(
                conversation.id,
                test_user,
                test_db,
                tenant_id=test_tenant_db.id,
                project_id=project.id,
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access denied"

    @pytest.mark.asyncio
    async def test_conversation_scope_requires_requested_project_id(
        self,
        test_db,
        test_project_db,
        test_tenant_db,
        test_user,
    ) -> None:
        conversation = Conversation(
            id="conversation-requested-project",
            project_id=test_project_db.id,
            tenant_id=test_tenant_db.id,
            user_id=test_user.id,
            title="Requested project scope",
            status="active",
            agent_config={},
            meta={},
            message_count=0,
            current_mode="build",
            merge_strategy="result_only",
            participant_agents=[],
        )
        test_db.add(conversation)
        await test_db.flush()

        with pytest.raises(HTTPException) as exc_info:
            await messages_router._verify_conversation_access(
                conversation.id,
                test_user,
                test_db,
                tenant_id=test_tenant_db.id,
                project_id="project-other",
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access denied"

        await messages_router._verify_conversation_access(
            conversation.id,
            test_user,
            test_db,
            tenant_id=test_tenant_db.id,
            project_id=test_project_db.id,
        )

    @pytest.mark.asyncio
    async def test_tool_executions_delegates_message_filter_to_v2_history(self):
        allowed_record = ToolExecutionRecord(
            id="record-allowed",
            conversation_id="conversation-tools",
            message_id="shared-message-id",
            call_id="call-allowed",
            tool_name="terminal",
        )
        history_service = SimpleNamespace(
            list_tool_executions=AsyncMock(return_value=[allowed_record]),
        )

        response = await get_conversation_tool_executions(
            "conversation-tools",
            message_id="shared-message-id",
            limit=100,
            history=SimpleNamespace(service=history_service),
        )

        assert response["total"] == 1
        assert response["tool_executions"][0]["id"] == "record-allowed"
        history_service.list_tool_executions.assert_awaited_once_with(
            conversation_id="conversation-tools",
            message_id="shared-message-id",
            limit=100,
        )

    @pytest.mark.asyncio
    async def test_conversation_messages_sanitizes_internal_errors(self):
        history = SimpleNamespace(
            service=SimpleNamespace(
                get_last_event_time=AsyncMock(side_effect=RuntimeError("internal stream secret"))
            )
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_messages(
                "conversation-secret",
                limit=50,
                from_time_us=None,
                from_counter=None,
                before_time_us=None,
                before_counter=None,
                history=history,
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to get messages"
        assert "internal" not in exc_info.value.detail
        assert "conversation-secret" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_conversation_execution_sanitizes_internal_errors(self, test_db, test_user):
        execution_query = SimpleNamespace(
            services=SimpleNamespace(
                get_execution_history=AsyncMock(side_effect=RuntimeError("internal exec secret"))
            )
        )
        self.monkeypatch.setattr(
            messages_router,
            "_verify_conversation_access",
            AsyncMock(return_value=None),
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_execution(
                "conversation-secret",
                project_id="project-1",
                limit=50,
                status_filter=None,
                tool_filter=None,
                current_user=test_user,
                tenant_id="tenant-secret",
                db=test_db,
                execution_query=execution_query,
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
        execution_query = SimpleNamespace(
            services=SimpleNamespace(
                get_execution_history=AsyncMock(side_effect=ValueError("secret conversation id"))
            )
        )
        self.monkeypatch.setattr(
            messages_router,
            "_verify_conversation_access",
            AsyncMock(return_value=None),
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_execution(
                "conversation-secret",
                project_id="project-1",
                limit=50,
                status_filter=None,
                tool_filter=None,
                current_user=test_user,
                tenant_id="tenant-secret",
                db=test_db,
                execution_query=execution_query,
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Conversation not found"
        assert "secret" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_tool_executions_sanitizes_internal_errors(self):
        history = SimpleNamespace(
            service=SimpleNamespace(
                list_tool_executions=AsyncMock(
                    side_effect=RuntimeError("internal tool repo secret")
                )
            )
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_tool_executions(
                "conversation-secret",
                message_id=None,
                limit=100,
                history=history,
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to get tool execution history"
        assert "internal" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_execution_status_sanitizes_internal_errors(self, test_db, test_user):
        @asynccontextmanager
        async def operation_context(**_kwargs: object):
            yield None

        class FailingRedis:
            async def exists(self, _key: str) -> int:
                raise RuntimeError("internal status secret")

        self.monkeypatch.setattr(
            messages_router,
            "_verify_conversation_access",
            AsyncMock(return_value=None),
        )
        self.monkeypatch.setattr(
            messages_router,
            "pin_agent_turn_operation_v2",
            operation_context,
        )
        self.monkeypatch.setattr(
            messages_router,
            "current_agent_worker_redis_client_v2",
            lambda: FailingRedis(),
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
        monkeypatch.setattr(
            messages_router,
            "_verify_conversation_access",
            AsyncMock(side_effect=HTTPException(status_code=404, detail="Conversation not found")),
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation_execution_status(
                "conversation-status-cross-tenant",
                request=MagicMock(),
                project_id="project-status",
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

        event_log = SimpleNamespace(
            last_cursor=AsyncMock(
                return_value=SessionEventCursorV2(event_time_us=123_456, event_counter=7)
            )
        )
        monkeypatch.setattr("redis.asyncio.Redis", FakeRedis)
        monkeypatch.setattr("redis.asyncio.ResponseError", ResponseError)
        monkeypatch.setattr(
            messages_router,
            "_session_event_log_service_v2",
            lambda: event_log,
            raising=False,
        )

        result = await _get_recovery_info(
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
        event_log.last_cursor.assert_awaited_once_with(conversation_id="conversation-1")

    @pytest.mark.asyncio
    async def test_recovery_info_propagates_missing_v2_log_authority(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeRedis:
            async def xinfo_stream(self, _stream_key: str):
                raise ResponseError

        class ResponseError(Exception):
            pass

        def missing_event_log() -> None:
            raise RuntimeV2Error(
                "session_event_log_unavailable",
                "internal event-log diagnostic",
            )

        monkeypatch.setattr("redis.asyncio.Redis", FakeRedis)
        monkeypatch.setattr("redis.asyncio.ResponseError", ResponseError)
        monkeypatch.setattr(
            messages_router,
            "_session_event_log_service_v2",
            missing_event_log,
            raising=False,
        )

        with pytest.raises(RuntimeV2Error) as error:
            await _get_recovery_info(
                redis_client=FakeRedis(),
                conversation_id="conversation-1",
                message_id="message-1",
                from_time_us=0,
            )

        assert error.value.code == "session_event_log_unavailable"

    @pytest.mark.asyncio
    async def test_execution_stats_sanitizes_internal_errors(self, test_db, test_user):
        execution_query = SimpleNamespace(
            services=SimpleNamespace(
                get_execution_history=AsyncMock(side_effect=RuntimeError("internal stats secret"))
            )
        )
        self.monkeypatch.setattr(
            messages_router,
            "_verify_conversation_access",
            AsyncMock(return_value=None),
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_execution_stats(
                "conversation-secret",
                project_id="project-1",
                current_user=test_user,
                tenant_id="tenant-secret",
                db=test_db,
                execution_query=execution_query,
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to get execution statistics"
        assert "internal" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_execution_stats_not_found_errors_are_sanitized(self, test_db, test_user):
        execution_query = SimpleNamespace(
            services=SimpleNamespace(
                get_execution_history=AsyncMock(side_effect=ValueError("secret conversation id"))
            )
        )
        self.monkeypatch.setattr(
            messages_router,
            "_verify_conversation_access",
            AsyncMock(return_value=None),
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_execution_stats(
                "conversation-secret",
                project_id="project-1",
                current_user=test_user,
                tenant_id="tenant-secret",
                db=test_db,
                execution_query=execution_query,
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Conversation not found"
        assert "secret" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_message_replies_sanitizes_internal_errors(self, test_db, test_user, monkeypatch):
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
