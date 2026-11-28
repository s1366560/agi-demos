"""Real permission preparation, persistence and public session projection contract."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from plugins.business.agent.engine.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)
from src.application.services.conversation_session_projection_service import (
    ConversationSessionProjectionService,
)
from src.domain.events.agent_events import AgentPermissionAskedEvent
from src.infrastructure.adapters.secondary.persistence.models import HITLRequest
from src.infrastructure.adapters.secondary.persistence.sql_conversation_session_projection_reader import (
    SqlConversationSessionProjectionReader,
)
from src.infrastructure.agent.core.message import Message, MessageRole, ToolPart, ToolState
from src.infrastructure.agent.hitl.coordinator import HITLCoordinator
from src.infrastructure.agent.tools.hooks import ToolHookRegistry
from src.infrastructure.agent.tools.pipeline import ToolPipeline
from src.infrastructure.agent.tools.truncation import OutputTruncator
from src.tests.unit.routers.agent.test_chat_run_permission_guard_v2 import (  # noqa: F401
    chat_guard_case,
    staged,
    verified,
)


@pytest.mark.parametrize("pipeline", [False, True])
async def test_real_chat_permission_is_reviewable_after_sql_hydration(
    chat_guard_case,  # noqa: F811
    test_db,
    test_engine,
    test_user,
    monkeypatch,
    pipeline,
    tmp_path,
):
    monkeypatch.setattr(
        "src.infrastructure.agent.hitl.coordinator.async_session_factory",
        async_sessionmaker(test_engine, expire_on_commit=False),
    )
    monkeypatch.setattr(
        "plugins.business.agent.engine.processor.processor.complete_hitl_request", AsyncMock()
    )
    async with chat_guard_case() as (run, _policy):
        coordinator = HITLCoordinator(run.conversation_id, run.tenant_id, run.project_id, run.id)
        tool = ToolDefinition(
            name="opaque_reviewed_operation",
            description="Update the explicitly selected fixture record",
            parameters={},
            permission="write",
            execute=AsyncMock(return_value="written"),
        )
        processor = SessionProcessor(
            config=ProcessorConfig(model="never-called", run_id=run.id, chat_run_required=True),
            tools=[tool],
        )
        processor._get_hitl_coordinator = lambda: coordinator
        if pipeline:
            processor._tool_pipeline = ToolPipeline(
                permission_manager=processor.permission_manager,
                doom_detector=processor.doom_loop_detector,
                truncator=OutputTruncator(),
                hooks=ToolHookRegistry(),
            )
        part = ToolPart(call_id="review-call", tool=tool.name, status=ToolState.RUNNING)
        processor._current_message = Message(role=MessageRole.ASSISTANT, parts=[part])
        processor._pending_tool_calls[part.call_id] = part
        iterator = processor._execute_tool(
            run.conversation_id, part.call_id, tool.name, {"password": "private-fixture-value"}
        )
        try:
            event = await asyncio.wait_for(anext(iterator), timeout=2)
            assert isinstance(event, AgentPermissionAskedEvent), getattr(event, "error", None)
            record = await test_db.scalar(
                select(HITLRequest).where(HITLRequest.id == event.request_id)
            )
            assert record is not None
            reader = SqlConversationSessionProjectionReader(test_db, SimpleNamespace())
            items, blocked = await reader._load_pending_hitl(
                conversation=SimpleNamespace(
                    id=run.conversation_id, tenant_id=run.tenant_id, project_id=run.project_id
                ),
                user_id=test_user.id,
                now=datetime.now(UTC),
            )
            assert blocked
            assert len(items) == 1, "Persisted permission disappeared from authoritative hydration"
            payload = ConversationSessionProjectionService._hitl(items[0]).model_dump(mode="json")
            assert payload["question"] == tool.description
            assert payload["permission"] == {
                "permission": "write",
                "tool_name": tool.name,
                "action": "execute",
                "description": tool.description,
                "risk_level": "medium",
                "allow_remember": False,
            }
            assert "private-fixture-value" not in str(payload)
            (tmp_path / "permission.json").write_text(json.dumps(payload))
            tool.execute.assert_not_awaited()
            hidden, _ = await reader._load_pending_hitl(
                conversation=SimpleNamespace(
                    id=run.conversation_id, tenant_id="another-tenant", project_id=run.project_id
                ),
                user_id=test_user.id,
                now=datetime.now(UTC),
            )
            assert hidden == ()
            record.user_id = "different-owner"
            await test_db.commit()
            hidden, _ = await reader._load_pending_hitl(
                conversation=SimpleNamespace(
                    id=run.conversation_id, tenant_id=run.tenant_id, project_id=run.project_id
                ),
                user_id=test_user.id,
                now=datetime.now(UTC),
            )
            assert hidden == ()
        finally:
            await iterator.aclose()
            for request_id in list(coordinator._pending):
                coordinator._cleanup_pending_request(request_id)


@pytest.mark.parametrize(
    "field,value",
    [
        ("tool_name", ""),
        ("description", None),
        ("action", []),
        ("risk_level", {}),
        ("risk_level", "invented"),
        ("allow_remember", "true"),
    ],
)
def test_malformed_permission_metadata_is_not_an_approvable_contract(field, value):
    metadata = {
        "tool_name": "opaque",
        "description": "Declared action",
        "action": "execute",
        "risk_level": "medium",
        "allow_remember": False,
    }
    metadata[field] = value
    assert SqlConversationSessionProjectionReader._permission_review(metadata) is None


@pytest.mark.parametrize("permission", [None, "write", "read", "terminal"])
def test_permission_review_preserves_declared_permission_type(permission):
    metadata = {
        "tool_name": "opaque",
        "description": "Declared action",
        "action": "execute",
        "risk_level": "medium",
        "allow_remember": False,
    }
    if permission is not None:
        metadata["permission_type"] = permission
    review = SqlConversationSessionProjectionReader._permission_review(metadata)
    assert review is not None
    assert review.permission == permission


@pytest.mark.parametrize("binding", ["terminal", "detached", "active_retry"])
async def test_terminal_run_pending_permission_does_not_block_new_messages(
    test_db,
    test_user,
    test_project_db,
    binding,
):
    from datetime import timedelta

    from src.infrastructure.adapters.secondary.persistence.models import Conversation
    from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
        ensure_chat_run_authority,
    )

    conversation = Conversation(
        id="terminal-hitl",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        title="Terminal HITL",
        agent_config={"approval_mode": "full_access"},
    )
    test_db.add(conversation)
    await test_db.commit()
    run = await ensure_chat_run_authority(
        test_db,
        conversation=conversation,
        run_id="terminal-hitl-run",
        request_message="Read only",
        client_message_id=None,
        app_model_context=None,
    )
    run.status = "cancelled"
    run.completed_at = datetime.now(UTC)
    if binding == "active_retry":
        retry = await ensure_chat_run_authority(
            test_db,
            conversation=conversation,
            run_id="active-hitl-retry",
            request_message="Retry",
            client_message_id=None,
            app_model_context=None,
        )
        retry.message_id = run.message_id
        retry.status = "running"
    test_db.add(
        HITLRequest(
            id="terminal-permission",
            request_type="clarification",
            conversation_id=conversation.id,
            tenant_id=conversation.tenant_id,
            project_id=conversation.project_id,
            user_id=test_user.id,
            message_id=None if binding == "detached" else run.message_id,
            question="Review declared tool",
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            request_metadata={
                "hitl_type": "permission",
                "tool_name": "bash",
                "action": "execute",
                "description": "Read only",
                "risk_level": "medium",
                "allow_remember": False,
            },
        )
    )
    await test_db.commit()
    reader = SqlConversationSessionProjectionReader(test_db, SimpleNamespace())
    projection = await ConversationSessionProjectionService(reader).get_projection(
        conversation_id=conversation.id,
        tenant_id=conversation.tenant_id,
        project_id=conversation.project_id,
        workspace_id=None,
        user_id=test_user.id,
    )
    from src.infrastructure.adapters.primary.web.websocket.handlers.chat_handler import (
        _pending_hitl_requests,
    )

    admission_pending = await _pending_hitl_requests(
        SimpleNamespace(db=test_db, tenant_id=conversation.tenant_id),
        conversation_id=conversation.id,
        project_id=conversation.project_id,
    )
    assert bool(admission_pending) is bool(projection.pending_hitl)
    assert bool(projection.pending_hitl) is (binding != "terminal")
    assert projection.capabilities.can_send_message is (binding == "terminal")

    from src.infrastructure.adapters.primary.web.routers.agent.automatic_permission_response import (
        annotate_automatic_permission_response,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
        SqlHITLRequestRepository,
    )

    stored = await SqlHITLRequestRepository(test_db).get_by_id("terminal-permission")
    response = {"action": "allow", "granted": True, "scope": "once"}
    if binding == "terminal":
        with pytest.raises(ValueError):
            await annotate_automatic_permission_response(
                test_db, hitl_request=stored, approval_mode="full_access", response_data=response
            )
    else:
        accepted = await annotate_automatic_permission_response(
            test_db, hitl_request=stored, approval_mode="full_access", response_data=response
        )
        assert accepted["auto_approved"] is True
