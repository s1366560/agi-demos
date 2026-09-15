"""No-model reproduction of ordinary chat permission-mode enforcement gaps."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.chat_run_tool_permission_v2 import prepare_chat_run_guard_v2
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import Conversation
from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
    ensure_chat_run_authority,
)
from src.infrastructure.agent.core.message import Message, MessageRole, ToolPart, ToolState
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)
from src.infrastructure.agent.tools.hooks import ToolHookRegistry
from src.infrastructure.agent.tools.pipeline import ToolPipeline
from src.infrastructure.agent.tools.truncation import OutputTruncator
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_operation_context_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.tests.unit.infrastructure.plugins.v2.test_wasm_tool_runtime import (  # noqa: F401
    staged,
    verified,
)


@pytest.mark.unit
@pytest.mark.parametrize("pipeline", [False, True])
@pytest.mark.parametrize(
    "outcome", ["read", "allow", "reject", "timeout", "cancel", "cancelled_run", "changed_args"]
)
async def test_ordinary_chat_ask_requires_confirmation_before_declared_write(
    test_db,
    test_user,
    test_project_db,
    tmp_path,
    pipeline,
    test_engine,
    staged,  # noqa: F811
    monkeypatch,
    outcome,
):
    monkeypatch.setattr(
        "src.application.services.chat_permission_admission_v2.load_workspace_policy",
        AsyncMock(return_value={"revision": 3, "permission_mode": "ask"}),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.processor.processor.complete_hitl_request", AsyncMock()
    )
    conversation = Conversation(
        id="ordinary-ask-conversation",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        title="Ask boundary",
        current_mode="build",
        workspace_id="ordinary-workspace",
    )
    test_db.add(conversation)
    await test_db.commit()
    run = await ensure_chat_run_authority(
        test_db,
        conversation=conversation,
        run_id="ordinary-ask-run",
        request_message="Request a write with confirmation",
        client_message_id="ordinary-turn",
        app_model_context=None,
        permission_mode="ask",
    )
    assert run.run_kind == "chat"
    assert run.permission_profile == "read_only"
    assert run.authorization_snapshot["effective_permission_mode"] == "ask"
    destination = tmp_path / "ordinary-write.txt"

    async def write_fixture(**_kwargs):
        destination.write_text("Tool executed before any approval")
        return "written"

    tool = ToolDefinition(
        name="opaque_chat_operation",
        description="Declared write",
        parameters={},
        permission="read" if outcome == "read" else "write",
        execute=write_fixture,
    )
    processor = SessionProcessor(
        config=ProcessorConfig(model="never-called", run_id=run.id, chat_run_required=True),
        tools=[tool],
    )
    coordinator = SimpleNamespace(
        prepare_request=AsyncMock(return_value="permission-request"),
        wait_for_response=AsyncMock(return_value=outcome in {"allow", "changed_args"}),
    )
    if outcome in {"timeout", "cancel"}:
        coordinator.wait_for_response.side_effect = (
            TimeoutError() if outcome == "timeout" else asyncio.CancelledError()
        )
    if outcome == "cancelled_run":

        async def cancel_then_allow(**_kwargs):
            run.status = "cancelled"
            await test_db.commit()
            return True

        coordinator.wait_for_response.side_effect = cancel_then_allow
    processor._get_hitl_coordinator = lambda: coordinator
    if outcome == "changed_args":

        async def replace_arguments(name, payload):
            if name == "before_tool_execution":
                return {**payload, "arguments": {"different_target": True}}
            return payload

        processor._notify_plugin_hook = replace_arguments
    permission_requests = []

    async def reject_permission(event):
        permission_requests.append(event)
        await processor.permission_manager.reply(event["data"]["request_id"], "reject")

    processor.permission_manager.set_event_publisher(reject_permission)
    if pipeline:
        processor._tool_pipeline = ToolPipeline(
            permission_manager=processor.permission_manager,
            doom_detector=processor.doom_loop_detector,
            truncator=OutputTruncator(),
            hooks=ToolHookRegistry(),
        )
    part = ToolPart(call_id="call", tool=tool.name, status=ToolState.RUNNING)
    processor._current_message = Message(role=MessageRole.ASSISTANT, parts=[part])
    processor._pending_tool_calls["call"] = part
    manager, _catalog = staged
    async with pin_operation_context_v2(
        manager,
        operation_id="ordinary-chat-permission",
        scope=ScopeV2(
            kind=ScopeKindV2.SESSION,
            tenant_id=test_project_db.tenant_id,
            project_id=test_project_db.id,
            session_id=conversation.id,
        ),
        services={
            OPERATION_METADATA_SERVICE_V2: {
                "kind": "agent-turn",
                "run_id": run.id,
                "conversation_id": conversation.id,
            },
            OPERATION_IDENTITY_SERVICE_V2: {
                "user_id": test_user.id,
                "tenant_id": test_project_db.tenant_id,
                "project_id": test_project_db.id,
            },
        },
    ) as operation:
        await prepare_chat_run_guard_v2(
            operation,
            run.id,
            sessions=async_sessionmaker(test_engine, expire_on_commit=False),
        )
        try:
            _events = [
                event
                async for event in processor._execute_tool(conversation.id, "call", tool.name, {})
            ]
        except asyncio.CancelledError:
            assert outcome == "cancel"
    assert destination.exists() == (outcome in {"read", "allow"})
    # Ask means a real confirmation path, not unconditional read-only denial.
    assert bool(coordinator.prepare_request.await_count or permission_requests) == (
        outcome != "read"
    )


@pytest.mark.unit
async def test_chat_automatic_must_not_exceed_its_persisted_workspace_policy_ceiling(
    test_db,
    test_user,
    test_project_db,
    monkeypatch,
):
    monkeypatch.setattr(
        "src.application.services.chat_permission_admission_v2.load_workspace_policy",
        AsyncMock(return_value={"revision": 3, "permission_mode": "ask"}),
    )
    conversation = Conversation(
        id="ordinary-automatic-conversation",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        title="Workspace ceiling",
        workspace_id="ordinary-workspace",
        current_mode="build",
    )
    test_db.add(conversation)
    await test_db.commit()
    with pytest.raises(RuntimeV2Error, match="exceed workspace policy"):
        await ensure_chat_run_authority(
            test_db,
            conversation=conversation,
            run_id="ordinary-automatic-run",
            request_message="Automatic bounded by workspace policy",
            client_message_id="automatic-turn",
            app_model_context=None,
            permission_mode="automatic",
        )
