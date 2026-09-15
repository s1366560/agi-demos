"""Latent injected execution-hook ASK contract; no production hook currently registers it."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.events.agent_events import AgentPermissionAskedEvent
from src.infrastructure.adapters.secondary.persistence.models import HITLRequest
from src.infrastructure.agent.core.message import Message, MessageRole, ToolPart, ToolState
from src.infrastructure.agent.hitl.coordinator import HITLCoordinator, ResolveResult
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)
from src.infrastructure.agent.tools.hooks import HookDecision, HookResult, ToolHookRegistry
from src.infrastructure.agent.tools.pipeline import ToolPipeline
from src.infrastructure.agent.tools.truncation import OutputTruncator
from src.tests.unit.routers.agent.test_chat_run_permission_guard_v2 import (  # noqa: F401
    chat_guard_case,
    staged,
    verified,
)


@pytest.mark.parametrize(
    "outcome",
    [
        "allow",
        "ordinary_ask",
        "deny",
        "timeout",
        "cancel",
        "cancelled_run",
        "changed_args",
        "policy_shrink",
        "manager_deny",
        "manager_ask",
    ],
)
async def test_injected_pre_hook_ask_emits_a_persisted_desktop_request(  # noqa: C901, PLR0915
    chat_guard_case,  # noqa: F811
    test_db,
    test_engine,
    monkeypatch,
    tmp_path,
    outcome,
):
    monkeypatch.setattr(
        "src.infrastructure.agent.hitl.coordinator.async_session_factory",
        async_sessionmaker(test_engine, expire_on_commit=False),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.processor.processor.complete_hitl_request", AsyncMock()
    )
    async with chat_guard_case("ask" if outcome == "ordinary_ask" else "full_access") as (
        run,
        policy,
    ):
        coordinator = HITLCoordinator(run.conversation_id, run.tenant_id, run.project_id, run.id)
        destination = tmp_path / "hook-result"

        async def actual_write(**arguments):
            destination.write_text(arguments["value"])
            return "written"

        tool = ToolDefinition(
            name="opaque_hook_review",
            description="Write the selected fixture record",
            parameters={},
            permission="write",
            execute=AsyncMock(wraps=actual_write),
        )
        processor = SessionProcessor(
            config=ProcessorConfig(model="never-called", run_id=run.id, chat_run_required=True),
            tools=[tool],
        )
        processor._get_hitl_coordinator = lambda: coordinator
        hooks = ToolHookRegistry()

        async def request_review(_name, _arguments, _context):
            return HookResult(decision=HookDecision.ASK, reason="Explicit fixture hook review")

        async def change_arguments(_name, _arguments, _context):
            return HookResult(args={"value": "after-hooks"})

        hooks.register_before(change_arguments, priority=10, name="fixture-arguments")
        hooks.register_before(request_review, name="fixture-review-only")
        processor._tool_pipeline = ToolPipeline(
            permission_manager=processor.permission_manager,
            doom_detector=processor.doom_loop_detector,
            truncator=OutputTruncator(),
            hooks=hooks,
        )
        part = ToolPart(call_id="hook-call", tool=tool.name, status=ToolState.RUNNING)
        processor._current_message = Message(role=MessageRole.ASSISTANT, parts=[part])
        processor._pending_tool_calls[part.call_id] = part
        iterator = processor._execute_tool(run.conversation_id, part.call_id, tool.name, {})
        try:
            event = await asyncio.wait_for(anext(iterator), timeout=2)
            assert isinstance(event, AgentPermissionAskedEvent)
            if outcome == "ordinary_ask":
                assert (
                    coordinator.resolve(
                        event.request_id,
                        {"action": "allow", "granted": True, "scope": "once"},
                        tenant_id=run.tenant_id,
                        project_id=run.project_id,
                        conversation_id=run.conversation_id,
                        message_id=run.id,
                    )
                    == ResolveResult.RESOLVED
                )
                async with asyncio.timeout(2):
                    event = await anext(iterator)
                assert isinstance(event, AgentPermissionAskedEvent)
            count = await test_db.scalar(
                select(func.count())
                .select_from(HITLRequest)
                .where(HITLRequest.conversation_id == run.conversation_id)
            )
            tool.execute.assert_not_awaited()
            assert event.request_id and count == (2 if outcome == "ordinary_ask" else 1), {
                "request_id": event.request_id,
                "persisted_requests": count,
            }
            record = await test_db.scalar(
                select(HITLRequest).where(HITLRequest.id == event.request_id)
            )
            assert record.request_metadata["tool_name"] == tool.name
            assert record.question == tool.description
            assert record.request_metadata["allow_remember"] is False
            assert event.metadata["input"] == {"value": "after-hooks"}
            if outcome == "cancel":
                await iterator.aclose()
                assert not destination.exists()
                return
            if outcome == "timeout":
                coordinator.wait_for_response = AsyncMock(side_effect=TimeoutError())
            else:
                granted = outcome != "deny"
                assert (
                    coordinator.resolve(
                        event.request_id,
                        {
                            "action": "allow" if granted else "deny",
                            "granted": granted,
                            "scope": "once",
                        },
                        tenant_id=run.tenant_id,
                        project_id=run.project_id,
                        conversation_id=run.conversation_id,
                        message_id=run.id,
                    )
                    == ResolveResult.RESOLVED
                )
            if outcome == "cancelled_run":
                run.status = "cancelled"
                await test_db.commit()
            if outcome == "changed_args":
                event.metadata["input"]["value"] = "not-approved"
            if outcome in {"manager_deny", "manager_ask"}:
                from src.infrastructure.agent.permission.rules import PermissionAction

                processor.permission_manager.evaluate = lambda *_: SimpleNamespace(
                    action=PermissionAction.DENY
                    if outcome == "manager_deny"
                    else PermissionAction.ASK
                )
            if outcome == "policy_shrink":
                policy["permission_mode"] = "ask"
            _events = [item async for item in iterator]
            if outcome in {"allow", "ordinary_ask", "manager_ask"}:
                tool.execute.assert_awaited_once_with(value="after-hooks")
                assert destination.read_text() == "after-hooks"
                assert part.status == ToolState.COMPLETED
            else:
                tool.execute.assert_not_awaited()
                assert not destination.exists()
        finally:
            await iterator.aclose()
            for request_id in list(coordinator._pending):
                coordinator._cleanup_pending_request(request_id)


async def test_later_hook_confirmation_does_not_restore_the_previous_approval(chat_guard_case):  # noqa: F811
    from src.application.services.chat_run_tool_permission_v2 import (
        approved_chat_tool_call_v2,
        claim_chat_tool_invocation_v2,
        decision_for_current_chat_tool_v2,
    )

    async with chat_guard_case():
        with approved_chat_tool_call_v2("opaque", {"value": "before"}):
            with approved_chat_tool_call_v2("opaque", {"value": "after"}, supersede_previous=True):
                assert (
                    await decision_for_current_chat_tool_v2("write", "opaque", {"value": "after"})
                    == "allow"
                )
                claim_chat_tool_invocation_v2("opaque", {"value": "after"}, permission="write")
            assert (
                await decision_for_current_chat_tool_v2("write", "opaque", {"value": "before"})
                == "ask"
            )


async def test_confirmation_for_another_tool_does_not_revoke_independent_approval(chat_guard_case):  # noqa: F811
    from src.application.services.chat_run_tool_permission_v2 import (
        approved_chat_tool_call_v2,
        decision_for_current_chat_tool_v2,
    )

    async with chat_guard_case():
        with approved_chat_tool_call_v2("first", {}):
            with approved_chat_tool_call_v2("second", {}):
                assert await decision_for_current_chat_tool_v2("write", "second", {}) == "allow"
            assert await decision_for_current_chat_tool_v2("write", "first", {}) == "allow"
