"""Real permission preparation, persistence and public session projection contract."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

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
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)
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
        "src.infrastructure.agent.processor.processor.complete_hitl_request", AsyncMock()
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
