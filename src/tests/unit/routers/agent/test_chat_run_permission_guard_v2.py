"""Invocation and recovery boundaries for canonical chat permissions."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.chat_run_tool_permission_v2 import (
    approved_chat_tool_call_v2,
    claim_chat_tool_invocation_v2,
    decision_for_current_chat_tool_v2,
    prepare_chat_run_guard_v2,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import Conversation, UserProject
from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
    ensure_chat_run_authority,
)
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


@pytest.fixture
def chat_guard_case(test_db, test_engine, test_user, test_project_db, monkeypatch, staged):  # noqa: F811
    @asynccontextmanager
    async def case(mode="ask"):
        policy = {"revision": 5, "permission_mode": mode}
        monkeypatch.setattr(
            "src.application.services.chat_permission_admission_v2.load_workspace_policy",
            AsyncMock(side_effect=lambda _: dict(policy)),
        )
        conversation = Conversation(
            id="chat-guard-cid",
            tenant_id=test_project_db.tenant_id,
            project_id=test_project_db.id,
            user_id=test_user.id,
            workspace_id="chat-guard-workspace",
            title="Guard",
        )
        test_db.add(conversation)
        await test_db.commit()
        row = await ensure_chat_run_authority(
            test_db,
            conversation=conversation,
            run_id="chat-guard-run",
            request_message="Guard without model",
            client_message_id="chat-guard-turn",
            app_model_context=None,
            permission_mode=mode,
        )
        manager, _ = staged
        async with pin_operation_context_v2(
            manager,
            operation_id="chat-guard-operation",
            scope=ScopeV2(
                kind=ScopeKindV2.SESSION,
                tenant_id=conversation.tenant_id,
                project_id=conversation.project_id,
                session_id=conversation.id,
            ),
            services={
                OPERATION_IDENTITY_SERVICE_V2: {
                    "tenant_id": conversation.tenant_id,
                    "project_id": conversation.project_id,
                    "user_id": test_user.id,
                },
                OPERATION_METADATA_SERVICE_V2: {
                    "kind": "agent-turn",
                    "run_id": row.id,
                    "conversation_id": conversation.id,
                },
            },
        ) as operation:
            await prepare_chat_run_guard_v2(
                operation, row.id, sessions=async_sessionmaker(test_engine, expire_on_commit=False)
            )
            yield row, policy

    return case


@pytest.mark.unit
async def test_chat_approval_is_exact_invocation_and_never_an_always_rule(chat_guard_case):
    async with chat_guard_case():
        assert await decision_for_current_chat_tool_v2("write", "opaque", {"value": 1}) == "ask"
        with approved_chat_tool_call_v2("opaque", {"value": 1}):
            assert (
                await decision_for_current_chat_tool_v2("write", "opaque", {"value": 1}) == "allow"
            )
            assert await decision_for_current_chat_tool_v2("write", "opaque", {"value": 2}) == "ask"
            assert await decision_for_current_chat_tool_v2("write", "other", {"value": 1}) == "ask"
            assert await decision_for_current_chat_tool_v2(None, "opaque", {"value": 1}) == "deny"
        assert await decision_for_current_chat_tool_v2("write", "opaque", {"value": 1}) == "ask"
        assert await decision_for_current_chat_tool_v2("read", "opaque", {}) == "allow"


@pytest.mark.unit
async def test_chat_approval_cannot_be_reused_after_actual_invocation(chat_guard_case):
    async with chat_guard_case():
        with approved_chat_tool_call_v2("opaque", {}):
            assert await decision_for_current_chat_tool_v2("write", "opaque", {}) == "allow"
            claim_chat_tool_invocation_v2("opaque", {})
            assert await decision_for_current_chat_tool_v2("write", "opaque", {}) == "ask"
            with pytest.raises(RuntimeV2Error):
                claim_chat_tool_invocation_v2("opaque", {})


@pytest.mark.unit
async def test_policy_await_cannot_hide_run_cancellation(chat_guard_case, test_db, monkeypatch):
    async with chat_guard_case("full_access") as (row, policy):

        async def cancel_during_policy(_conversation):
            row.status = "cancelled"
            await test_db.commit()
            return dict(policy)

        monkeypatch.setattr(
            "src.application.services.chat_permission_admission_v2.load_workspace_policy",
            cancel_during_policy,
        )
        with pytest.raises(RuntimeV2Error):
            await decision_for_current_chat_tool_v2("write", "opaque", {})


@pytest.mark.unit
async def test_chat_current_policy_cannot_restore_a_previously_broader_grant(chat_guard_case):
    async with chat_guard_case("full_access") as (_row, policy):
        assert await decision_for_current_chat_tool_v2("write", "opaque", {}) == "allow"
        policy.update(revision=6, permission_mode="ask")
        with pytest.raises(RuntimeV2Error, match="exceed workspace policy"):
            await decision_for_current_chat_tool_v2("write", "opaque", {})


@pytest.mark.unit
@pytest.mark.parametrize("revocation", ["membership", "cancelled", "legacy_snapshot", "inactive"])
async def test_confirmed_chat_call_freshly_rechecks_authority(
    chat_guard_case, test_db, test_user, revocation
):
    async with chat_guard_case() as (row, _policy):
        assert await decision_for_current_chat_tool_v2("write", "opaque", {}) == "ask"
        with approved_chat_tool_call_v2("opaque", {}):
            if revocation == "membership":
                await test_db.execute(
                    delete(UserProject).where(UserProject.user_id == test_user.id)
                )
            elif revocation == "cancelled":
                row.status = "cancelled"
            elif revocation == "inactive":
                from src.infrastructure.adapters.secondary.persistence.models import User

                user = await test_db.get(User, test_user.id)
                user.is_active = False
            else:
                row.authorization_snapshot = {**row.authorization_snapshot, "schema_version": 0}
            await test_db.commit()
            with pytest.raises(RuntimeV2Error):
                await decision_for_current_chat_tool_v2("write", "opaque", {})


@pytest.mark.unit
async def test_required_chat_guard_never_tolerates_a_missing_operation():
    assert await decision_for_current_chat_tool_v2("read", "opaque", {}, required=True) == "deny"


@pytest.mark.unit
async def test_automatic_accepts_only_formal_workspace_write_category(chat_guard_case):
    async with chat_guard_case("automatic"):
        assert (
            await decision_for_current_chat_tool_v2("workspace_task_write", "opaque", {}) == "allow"
        )
        assert (
            await decision_for_current_chat_tool_v2("workspace_file_write", "opaque", {}) == "allow"
        )
        assert await decision_for_current_chat_tool_v2("write", "opaque", {}) == "deny"
        assert (
            await decision_for_current_chat_tool_v2("conversation_progress", "opaque", {})
            == "allow"
        )


@pytest.mark.unit
async def test_real_permission_coordinator_publishes_request_before_waiting_for_response(
    chat_guard_case, monkeypatch, tmp_path
):
    from src.domain.events.agent_events import AgentPermissionAskedEvent
    from src.infrastructure.agent.core.message import Message, MessageRole, ToolPart, ToolState
    from src.infrastructure.agent.hitl.coordinator import HITLCoordinator, ResolveResult
    from src.infrastructure.agent.processor.processor import (
        ProcessorConfig,
        SessionProcessor,
        ToolDefinition,
    )

    monkeypatch.setattr(
        "src.infrastructure.agent.hitl.coordinator._persist_hitl_request", AsyncMock()
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.processor.processor.complete_hitl_request", AsyncMock()
    )
    destination = tmp_path / "confirmed-write"

    async def write(**_kwargs):
        destination.write_text("User explicitly approved")
        return "written"

    async with chat_guard_case() as (row, _policy):
        coordinator = HITLCoordinator(row.conversation_id, row.tenant_id, row.project_id, row.id)
        tool = ToolDefinition(
            name="opaque_confirmed",
            description="Declared write",
            parameters={},
            permission="write",
            execute=write,
        )
        processor = SessionProcessor(
            config=ProcessorConfig(model="never-called", run_id=row.id, chat_run_required=True),
            tools=[tool],
        )
        processor._get_hitl_coordinator = lambda: coordinator
        part = ToolPart(call_id="confirmed-call", tool=tool.name, status=ToolState.RUNNING)
        processor._current_message = Message(role=MessageRole.ASSISTANT, parts=[part])
        processor._pending_tool_calls[part.call_id] = part
        iterator = processor._execute_tool(row.conversation_id, part.call_id, tool.name, {})
        try:
            event = await asyncio.wait_for(anext(iterator), timeout=0.5)
            assert isinstance(event, AgentPermissionAskedEvent)
            assert not destination.exists()
            outcome = coordinator.resolve(
                event.request_id,
                {"action": "allow", "granted": True, "scope": "once"},
                tenant_id=row.tenant_id,
                project_id=row.project_id,
                conversation_id=row.conversation_id,
                message_id=row.id,
            )
            assert outcome == ResolveResult.RESOLVED
            _events = [event async for event in iterator]
            assert destination.exists()
        finally:
            await iterator.aclose()
            for request_id in list(coordinator._pending):
                coordinator._cleanup_pending_request(request_id)
