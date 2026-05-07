"""Unit tests for HITL tool handler answered events."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.events.agent_events import (
    AgentA2UIActionAnsweredEvent,
    AgentA2UIActionAskedEvent,
    AgentCanvasUpdatedEvent,
    AgentClarificationAnsweredEvent,
    AgentClarificationAskedEvent,
    AgentDecisionAnsweredEvent,
    AgentDecisionAskedEvent,
    AgentEnvVarProvidedEvent,
    AgentEnvVarRequestedEvent,
    AgentObserveEvent,
)
from src.domain.model.agent.hitl_types import HITLType
from src.infrastructure.agent.canvas.manager import CanvasManager
from src.infrastructure.agent.canvas.tools import configure_canvas
from src.infrastructure.agent.core.message import ToolPart, ToolState
from src.infrastructure.agent.processor.hitl_tool_handler import (
    handle_a2ui_action_tool,
    handle_clarification_tool,
    handle_decision_tool,
    handle_env_var_tool,
)
from src.tests.unit.agent.canvas.a2ui_contract_fixtures import (
    contract_case_jsonl,
    get_a2ui_contract_case,
)


def _make_tool_part(call_id: str, tool_name: str) -> ToolPart:
    return ToolPart(
        call_id=call_id,
        tool=tool_name,
        status=ToolState.RUNNING,
        input={},
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clarification_answered_event_uses_original_request_id() -> None:
    coordinator = MagicMock()
    coordinator.prepare_request = AsyncMock(return_value="clar-req-1")
    coordinator.wait_for_response = AsyncMock(return_value="PostgreSQL")
    tool_part = _make_tool_part("call-clar", "ask_clarification")

    events = [
        event
        async for event in handle_clarification_tool(
            coordinator=coordinator,
            call_id="call-clar",
            tool_name="ask_clarification",
            arguments={
                "question": "Which DB?",
                "clarification_type": "approach",
                "options": [{"id": "pg", "label": "PostgreSQL"}],
            },
            tool_part=tool_part,
        )
    ]

    answered_event = next(e for e in events if isinstance(e, AgentClarificationAnsweredEvent))
    assert answered_event.request_id == "clar-req-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clarification_tool_supports_multi_select_answers() -> None:
    coordinator = MagicMock()
    coordinator.prepare_request = AsyncMock(return_value="clar-req-multi")
    coordinator.wait_for_response = AsyncMock(return_value=["pg", "mysql"])
    tool_part = _make_tool_part("call-clar-multi", "ask_clarification")

    events = [
        event
        async for event in handle_clarification_tool(
            coordinator=coordinator,
            call_id="call-clar-multi",
            tool_name="ask_clarification",
            arguments={
                "question": "Choose databases",
                "options": [{"id": "pg", "label": "PostgreSQL"}, {"id": "mysql", "label": "MySQL"}],
            },
            tool_part=tool_part,
        )
    ]

    answered_event = next(
        event for event in events if isinstance(event, AgentClarificationAnsweredEvent)
    )
    assert answered_event.answer == ["pg", "mysql"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_decision_answered_event_uses_original_request_id() -> None:
    coordinator = MagicMock()
    coordinator.prepare_request = AsyncMock(return_value="dec-req-1")
    coordinator.wait_for_response = AsyncMock(return_value="option_a")
    tool_part = _make_tool_part("call-dec", "request_decision")

    events = [
        event
        async for event in handle_decision_tool(
            coordinator=coordinator,
            call_id="call-dec",
            tool_name="request_decision",
            arguments={
                "question": "Choose option",
                "decision_type": "method",
                "options": [{"id": "a", "label": "Option A"}],
            },
            tool_part=tool_part,
        )
    ]

    answered_event = next(e for e in events if isinstance(e, AgentDecisionAnsweredEvent))
    assert answered_event.request_id == "dec-req-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_decision_tool_normalizes_string_options() -> None:
    coordinator = MagicMock()
    coordinator.prepare_request = AsyncMock(return_value="dec-req-str")
    coordinator.wait_for_response = AsyncMock(return_value="option_a")
    tool_part = _make_tool_part("call-dec-str", "request_decision")

    _ = [
        event
        async for event in handle_decision_tool(
            coordinator=coordinator,
            call_id="call-dec-str",
            tool_name="request_decision",
            arguments={
                "question": "Choose option",
                "decision_type": "method",
                "options": ["Option A", "Option B"],
            },
            tool_part=tool_part,
        )
    ]

    prepared_request = coordinator.prepare_request.call_args.args[1]
    assert prepared_request["options"] == [
        {
            "id": "0",
            "label": "Option A",
            "description": None,
            "recommended": False,
            "risk_level": None,
            "estimated_time": None,
            "estimated_cost": None,
            "risks": [],
        },
        {
            "id": "1",
            "label": "Option B",
            "description": None,
            "recommended": False,
            "risk_level": None,
            "estimated_time": None,
            "estimated_cost": None,
            "risks": [],
        },
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_decision_tool_normalizes_mixed_option_types() -> None:
    coordinator = MagicMock()
    coordinator.prepare_request = AsyncMock(return_value="dec-req-mixed")
    coordinator.wait_for_response = AsyncMock(return_value="option_b")
    tool_part = _make_tool_part("call-dec-mixed", "request_decision")

    _ = [
        event
        async for event in handle_decision_tool(
            coordinator=coordinator,
            call_id="call-dec-mixed",
            tool_name="request_decision",
            arguments={
                "question": "Choose option",
                "options": [
                    "Option A",
                    {"id": "custom-id", "label": "Option B", "recommended": True},
                    42,
                ],
            },
            tool_part=tool_part,
        )
    ]

    prepared_request = coordinator.prepare_request.call_args.args[1]
    assert prepared_request["options"] == [
        {
            "id": "0",
            "label": "Option A",
            "description": None,
            "recommended": False,
            "risk_level": None,
            "estimated_time": None,
            "estimated_cost": None,
            "risks": [],
        },
        {
            "id": "custom-id",
            "label": "Option B",
            "description": None,
            "recommended": True,
            "risk_level": None,
            "estimated_time": None,
            "estimated_cost": None,
            "risks": [],
        },
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_decision_tool_sanitizes_invalid_option_fields() -> None:
    coordinator = MagicMock()
    coordinator.prepare_request = AsyncMock(return_value="dec-req-bad-fields")
    coordinator.wait_for_response = AsyncMock(return_value="option_a")
    tool_part = _make_tool_part("call-dec-bad-fields", "request_decision")

    _ = [
        event
        async for event in handle_decision_tool(
            coordinator=coordinator,
            call_id="call-dec-bad-fields",
            tool_name="request_decision",
            arguments={
                "question": "Choose option",
                "options": [
                    {"id": "bad", "label": 0, "description": 0, "risks": ["data loss", 42]},
                    {
                        "id": "a",
                        "label": "Option A",
                        "description": 0,
                        "risk_level": "not-a-risk",
                        "estimated_time": 5,
                        "risks": ["rollback", 42, ""],
                    },
                ],
            },
            tool_part=tool_part,
        )
    ]

    prepared_request = coordinator.prepare_request.call_args.args[1]
    assert prepared_request["options"] == [
        {
            "id": "a",
            "label": "Option A",
            "description": None,
            "recommended": False,
            "risk_level": None,
            "estimated_time": None,
            "estimated_cost": None,
            "risks": ["rollback"],
        }
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_decision_tool_event_options_match_prepared_request_after_sanitization() -> None:
    coordinator = MagicMock()
    coordinator.prepare_request = AsyncMock(return_value="dec-req-aligned")
    coordinator.wait_for_response = AsyncMock(return_value="0")
    tool_part = _make_tool_part("call-dec-aligned", "request_decision")

    events = [
        event
        async for event in handle_decision_tool(
            coordinator=coordinator,
            call_id="call-dec-aligned",
            tool_name="request_decision",
            arguments={
                "question": "Choose option",
                "options": ["   ", "Deploy & Review"],
            },
            tool_part=tool_part,
        )
    ]

    asked_event = next(event for event in events if isinstance(event, AgentDecisionAskedEvent))
    prepared_request = coordinator.prepare_request.call_args.args[1]
    assert prepared_request["options"] == asked_event.options
    assert prepared_request["options"] == [
        {
            "id": "0",
            "label": "Deploy &amp; Review",
            "description": None,
            "recommended": False,
            "risk_level": None,
            "estimated_time": None,
            "estimated_cost": None,
            "risks": [],
        }
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_decision_tool_supports_multi_select_answers() -> None:
    coordinator = MagicMock()
    coordinator.prepare_request = AsyncMock(return_value="dec-req-multi")
    coordinator.wait_for_response = AsyncMock(return_value=["a", "b"])
    tool_part = _make_tool_part("call-dec-multi", "request_decision")

    events = [
        event
        async for event in handle_decision_tool(
            coordinator=coordinator,
            call_id="call-dec-multi",
            tool_name="request_decision",
            arguments={
                "question": "Choose options",
                "selection_mode": "multiple",
                "options": [
                    {"id": "a", "label": "Option A"},
                    {"id": "b", "label": "Option B"},
                ],
            },
            tool_part=tool_part,
        )
    ]

    answered_event = next(
        event for event in events if isinstance(event, AgentDecisionAnsweredEvent)
    )
    assert answered_event.decision == ["a", "b"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clarification_tool_preserves_default_value() -> None:
    coordinator = MagicMock()
    coordinator.prepare_request = AsyncMock(return_value="clar-req-default")
    coordinator.wait_for_response = AsyncMock(return_value="fallback")
    tool_part = _make_tool_part("call-clar-default", "ask_clarification")

    events = [
        event
        async for event in handle_clarification_tool(
            coordinator=coordinator,
            call_id="call-clar-default",
            tool_name="ask_clarification",
            arguments={
                "question": "Choose database",
                "options": ["PostgreSQL", "MySQL"],
                "default_value": "fallback",
            },
            tool_part=tool_part,
        )
    ]

    asked_event = next(event for event in events if isinstance(event, AgentClarificationAskedEvent))
    prepared_request = coordinator.prepare_request.call_args.args[1]
    assert prepared_request["default_value"] == "fallback"
    assert getattr(asked_event, "default_value", None) == "fallback"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_decision_tool_clears_invalid_default_option_after_sanitization() -> None:
    coordinator = MagicMock()
    coordinator.prepare_request = AsyncMock(return_value="dec-req-default")
    coordinator.wait_for_response = AsyncMock(return_value="0")
    tool_part = _make_tool_part("call-dec-default", "request_decision")

    _ = [
        event
        async for event in handle_decision_tool(
            coordinator=coordinator,
            call_id="call-dec-default",
            tool_name="request_decision",
            arguments={
                "question": "Choose option",
                "options": [{"label": "   "}, {"label": "Keep me"}],
                "default_option": "1",
            },
            tool_part=tool_part,
        )
    ]

    prepared_request = coordinator.prepare_request.call_args.args[1]
    assert prepared_request["options"] == [
        {
            "id": "0",
            "label": "Keep me",
            "description": None,
            "recommended": False,
            "risk_level": None,
            "estimated_time": None,
            "estimated_cost": None,
            "risks": [],
        }
    ]
    assert prepared_request["default_option"] is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clarification_tool_normalizes_string_options() -> None:
    coordinator = MagicMock()
    coordinator.prepare_request = AsyncMock(return_value="clar-req-str")
    coordinator.wait_for_response = AsyncMock(return_value="postgresql")
    tool_part = _make_tool_part("call-clar-str", "ask_clarification")

    _ = [
        event
        async for event in handle_clarification_tool(
            coordinator=coordinator,
            call_id="call-clar-str",
            tool_name="ask_clarification",
            arguments={
                "question": "Choose database",
                "clarification_type": "approach",
                "options": ["PostgreSQL", "MySQL"],
            },
            tool_part=tool_part,
        )
    ]

    prepared_request = coordinator.prepare_request.call_args.args[1]
    assert prepared_request["options"] == [
        {
            "id": "0",
            "label": "PostgreSQL",
            "description": None,
            "recommended": False,
        },
        {
            "id": "1",
            "label": "MySQL",
            "description": None,
            "recommended": False,
        },
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_env_var_provided_event_uses_original_request_id(monkeypatch) -> None:
    from src.infrastructure.agent.processor import hitl_tool_handler as handler_mod

    coordinator = MagicMock()
    coordinator.tenant_id = "tenant-1"
    coordinator.project_id = "project-1"
    coordinator.prepare_request = AsyncMock(return_value="env-req-1")
    coordinator.wait_for_response = AsyncMock(return_value={"values": {"API_KEY": "secret"}})
    monkeypatch.setattr(handler_mod, "_save_env_vars", AsyncMock(return_value=["API_KEY"]))
    tool_part = _make_tool_part("call-env", "request_env_var")

    events = [
        event
        async for event in handle_env_var_tool(
            coordinator=coordinator,
            call_id="call-env",
            tool_name="request_env_var",
            arguments={
                "tool_name": "web_search",
                "fields": [{"name": "API_KEY", "description": "Key"}],
            },
            tool_part=tool_part,
        )
    ]

    provided_event = next(e for e in events if isinstance(e, AgentEnvVarProvidedEvent))
    assert provided_event.request_id == "env-req-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_env_var_tool_prepare_request_forwards_context_and_save_scope() -> None:
    coordinator = MagicMock()
    coordinator.conversation_id = "conv-env"
    coordinator.tenant_id = "tenant-1"
    coordinator.project_id = "project-1"
    coordinator.message_id = "msg-env"
    coordinator.prepare_request = AsyncMock(return_value="env-req-2")
    coordinator.wait_for_response = AsyncMock(return_value={"cancelled": True})
    tool_part = _make_tool_part("call-env", "request_env_var")

    _ = [
        event
        async for event in handle_env_var_tool(
            coordinator=coordinator,
            call_id="call-env",
            tool_name="request_env_var",
            arguments={
                "tool_name": "web_search",
                "fields": [{"name": "API_KEY", "description": "Key"}],
                "context": {"reason": "Need credentials"},
                "save_to_project": True,
            },
            tool_part=tool_part,
        )
    ]

    request_args = coordinator.prepare_request.await_args
    assert request_args.args[0] == HITLType.ENV_VAR
    assert request_args.args[1]["context"] == {"reason": "Need credentials"}
    assert request_args.kwargs["save_project_id"] == "project-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_env_var_requested_event_uses_sanitized_metadata() -> None:
    coordinator = MagicMock()
    coordinator.conversation_id = "conv-env-sanitize"
    coordinator.tenant_id = "tenant-1"
    coordinator.project_id = ""
    coordinator.message_id = "msg-env-sanitize"
    coordinator.prepare_request = AsyncMock(return_value="env-req-sanitize")
    coordinator.wait_for_response = AsyncMock(return_value={"cancelled": True})
    tool_part = _make_tool_part("call-env", "request_env_var")

    events = [
        event
        async for event in handle_env_var_tool(
            coordinator=coordinator,
            call_id="call-env",
            tool_name="request_env_var",
            arguments={
                "tool_name": "web_search<script>",
                "fields": [
                    {
                        "name": "API_KEY",
                        "label": "<b>API Key</b>",
                        "description": "Bearer&amp;#32;sk&amp;#45;1234567890abcdefghijklmnop",
                        "default_value": "A&amp;B",
                        "placeholder": "<paste here>",
                        "is_secret": False,
                    }
                ],
                "context": {
                    "tool_name": "fake_tool",
                    "requested_variables": ["WRONG"],
                    "save_scope": "project",
                    "project_id": "fake-project",
                    "reason": "<img src=x onerror=1>",
                },
            },
            tool_part=tool_part,
        )
    ]

    asked_event = next(e for e in events if isinstance(e, AgentEnvVarRequestedEvent))
    assert asked_event.tool_name == "web_search&lt;script&gt;"
    assert asked_event.fields[0]["label"] == "&lt;b&gt;API Key&lt;/b&gt;"
    assert asked_event.fields[0]["description"] is None
    assert asked_event.fields[0]["default_value"] == "A&amp;B"
    assert asked_event.fields[0]["placeholder"] == "&lt;paste here&gt;"
    assert asked_event.context["tool_name"] == "web_search&lt;script&gt;"
    assert asked_event.context["requested_variables"] == ["&lt;b&gt;API Key&lt;/b&gt;"]
    assert asked_event.context["save_scope"] == "tenant"
    assert "project_id" not in asked_event.context
    assert asked_event.context["reason"] == "&lt;img src=x onerror=1&gt;"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_env_var_tool_saves_using_captured_coordinator_scope(monkeypatch) -> None:
    from src.infrastructure.agent.processor import hitl_tool_handler as handler_mod

    coordinator = MagicMock()
    coordinator.conversation_id = "conv-env-save"
    coordinator.tenant_id = "tenant-coordinator"
    coordinator.project_id = "project-coordinator"
    coordinator.message_id = "msg-env-save"
    coordinator.prepare_request = AsyncMock(return_value="env-req-save")
    coordinator.wait_for_response = AsyncMock(return_value={"values": {"API_KEY": "secret"}})
    save_mock = AsyncMock(return_value=["API_KEY"])
    monkeypatch.setattr(handler_mod, "_save_env_vars", save_mock)
    tool_part = _make_tool_part("call-env", "request_env_var")

    _ = [
        event
        async for event in handle_env_var_tool(
            coordinator=coordinator,
            call_id="call-env",
            tool_name="request_env_var",
            arguments={
                "tool_name": "web_search",
                "fields": [{"name": "API_KEY", "description": "Key"}],
                "save_to_project": True,
            },
            tool_part=tool_part,
            langfuse_context={"tenant_id": "tenant-stale", "project_id": "project-stale"},
        )
    ]

    assert save_mock.await_args.kwargs["tenant_id"] == "tenant-coordinator"
    assert save_mock.await_args.kwargs["project_id"] == "project-coordinator"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_env_var_tool_fails_closed_for_invalid_required_response() -> None:
    coordinator = MagicMock()
    coordinator.conversation_id = "conv-env-invalid"
    coordinator.tenant_id = "tenant-1"
    coordinator.project_id = "project-1"
    coordinator.message_id = "msg-env-invalid"
    coordinator.prepare_request = AsyncMock(return_value="env-req-invalid")
    coordinator.wait_for_response = AsyncMock(return_value={"API_KEY": "   "})
    tool_part = _make_tool_part("call-env", "request_env_var")

    events = [
        event
        async for event in handle_env_var_tool(
            coordinator=coordinator,
            call_id="call-env",
            tool_name="request_env_var",
            arguments={
                "tool_name": "web_search",
                "fields": [{"name": "API_KEY", "description": "Key"}],
            },
            tool_part=tool_part,
        )
    ]

    assert not any(isinstance(e, AgentEnvVarProvidedEvent) for e in events)
    observe_event = next(e for e in events if isinstance(e, AgentObserveEvent))
    assert observe_event.error == "Missing required environment variables: API_KEY"
    assert tool_part.status == ToolState.ERROR
    assert tool_part.error == "Missing required environment variables: API_KEY"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_env_var_tool_treats_explicit_cancel_as_cancelled() -> None:
    coordinator = MagicMock()
    coordinator.conversation_id = "conv-env-empty"
    coordinator.tenant_id = "tenant-1"
    coordinator.project_id = "project-1"
    coordinator.message_id = "msg-env-empty"
    coordinator.prepare_request = AsyncMock(return_value="env-req-empty")
    coordinator.wait_for_response = AsyncMock(return_value={"cancelled": True})
    tool_part = _make_tool_part("call-env", "request_env_var")

    events = [
        event
        async for event in handle_env_var_tool(
            coordinator=coordinator,
            call_id="call-env",
            tool_name="request_env_var",
            arguments={
                "tool_name": "web_search",
                "fields": [{"name": "API_KEY", "description": "Key"}],
            },
            tool_part=tool_part,
        )
    ]

    assert not any(isinstance(e, AgentEnvVarProvidedEvent) for e in events)
    observe_event = next(e for e in events if isinstance(e, AgentObserveEvent))
    assert observe_event.result == {
        "success": False,
        "cancelled": True,
        "tool_name": "web_search",
        "saved_variables": [],
        "message": "User did not provide the requested environment variables",
    }
    assert tool_part.status == ToolState.COMPLETED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_env_var_tool_allows_empty_values_when_all_fields_optional() -> None:
    coordinator = MagicMock()
    coordinator.conversation_id = "conv-env-optional"
    coordinator.tenant_id = "tenant-1"
    coordinator.project_id = "project-1"
    coordinator.message_id = "msg-env-optional"
    coordinator.prepare_request = AsyncMock(return_value="env-req-optional")
    coordinator.wait_for_response = AsyncMock(return_value={"values": {}})
    tool_part = _make_tool_part("call-env", "request_env_var")

    events = [
        event
        async for event in handle_env_var_tool(
            coordinator=coordinator,
            call_id="call-env",
            tool_name="request_env_var",
            arguments={
                "tool_name": "web_search",
                "fields": [{"name": "OPTIONAL_TOKEN", "description": "Key", "required": False}],
            },
            tool_part=tool_part,
        )
    ]

    provided_event = next(e for e in events if isinstance(e, AgentEnvVarProvidedEvent))
    observe_event = next(e for e in events if isinstance(e, AgentObserveEvent))
    assert provided_event.saved_variables == []
    assert observe_event.result == {
        "success": True,
        "tool_name": "web_search",
        "saved_variables": [],
        "message": "Successfully saved 0 environment variable(s)",
    }
    assert tool_part.status == ToolState.COMPLETED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_env_var_tool_fails_closed_when_save_errors(monkeypatch) -> None:
    from src.infrastructure.agent.processor import hitl_tool_handler as handler_mod

    coordinator = MagicMock()
    coordinator.conversation_id = "conv-env-save-error"
    coordinator.tenant_id = "tenant-1"
    coordinator.project_id = "project-1"
    coordinator.message_id = "msg-env-save-error"
    coordinator.prepare_request = AsyncMock(return_value="env-req-save-error")
    coordinator.wait_for_response = AsyncMock(return_value={"values": {"API_KEY": "secret"}})
    monkeypatch.setattr(
        handler_mod,
        "_save_env_vars",
        AsyncMock(side_effect=RuntimeError("db write failed")),
    )
    tool_part = _make_tool_part("call-env", "request_env_var")

    events = [
        event
        async for event in handle_env_var_tool(
            coordinator=coordinator,
            call_id="call-env",
            tool_name="request_env_var",
            arguments={
                "tool_name": "web_search",
                "fields": [{"name": "API_KEY", "description": "Key"}],
            },
            tool_part=tool_part,
        )
    ]

    assert not any(isinstance(e, AgentEnvVarProvidedEvent) for e in events)
    observe_event = next(e for e in events if isinstance(e, AgentObserveEvent))
    assert observe_event.error == "Failed to save environment variables: db write failed"
    assert tool_part.status == ToolState.ERROR
    assert tool_part.error == "Failed to save environment variables: db write failed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a2ui_tool_infers_surface_id_for_canvas_metadata() -> None:
    coordinator = MagicMock()
    coordinator.conversation_id = "conv-a2ui"
    coordinator.prepare_request = AsyncMock(return_value="a2ui-req-1")
    coordinator.wait_for_response = AsyncMock(
        return_value={
            "action_name": "submit",
            "source_component_id": "button-1",
            "context": {"approved": True},
        }
    )
    tool_part = _make_tool_part("call-a2ui", "canvas_create_interactive")
    configure_canvas(CanvasManager())

    components = "\n".join(
        [
            '{"beginRendering":{"surfaceId":"surface-99","root":"button-1"}}',
            '{"surfaceUpdate":{"surfaceId":"surface-99","components":[{"id":"label-1","component":{"Text":{"text":{"literalString":"Approve"}}}},{"id":"button-1","component":{"Button":{"child":"label-1","action":{"name":"submit"}}}}]}}',
        ]
    )

    events = [
        event
        async for event in handle_a2ui_action_tool(
            coordinator=coordinator,
            call_id="call-a2ui",
            tool_name="canvas_create_interactive",
            arguments={"title": "Review", "components": components},
            tool_part=tool_part,
        )
    ]

    canvas_event = next(e for e in events if isinstance(e, AgentCanvasUpdatedEvent))
    asked_event = next(e for e in events if isinstance(e, AgentA2UIActionAskedEvent))

    assert canvas_event.block is not None
    assert canvas_event.block["metadata"]["surface_id"] == "surface-99"
    assert canvas_event.block["metadata"]["hitl_request_id"] == "a2ui-req-1"
    assert asked_event.block_id == canvas_event.block_id

    configure_canvas(None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a2ui_tool_uses_shared_fixture_identity_contract() -> None:
    case = get_a2ui_contract_case("identity_interactive_request")
    identity = case["identity"]
    coordinator = MagicMock()
    coordinator.conversation_id = "conv-a2ui"
    coordinator.prepare_request = AsyncMock(return_value=identity["hitlRequestId"])
    coordinator.wait_for_response = AsyncMock(
        return_value={
            "action_name": "approve",
            "source_component_id": "button-1",
            "context": {"approved": True},
        }
    )
    tool_part = _make_tool_part("call-a2ui", "canvas_create_interactive")
    configure_canvas(CanvasManager())

    events = [
        event
        async for event in handle_a2ui_action_tool(
            coordinator=coordinator,
            call_id="call-a2ui",
            tool_name="canvas_create_interactive",
            arguments={"title": "Review", "components": contract_case_jsonl(case)},
            tool_part=tool_part,
        )
    ]

    canvas_event = next(e for e in events if isinstance(e, AgentCanvasUpdatedEvent))
    asked_event = next(e for e in events if isinstance(e, AgentA2UIActionAskedEvent))

    assert canvas_event.block is not None
    assert canvas_event.block["metadata"]["surface_id"] == identity["metadataSurfaceId"]
    assert canvas_event.block["metadata"]["hitl_request_id"] == identity["hitlRequestId"]
    assert asked_event.request_id == identity["hitlRequestId"]
    assert asked_event.block_id == canvas_event.block_id

    configure_canvas(None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a2ui_tool_preserves_surface_metadata_and_action_result_after_interaction() -> None:
    case = get_a2ui_contract_case("identity_interactive_request")
    identity = case["identity"]
    coordinator = MagicMock()
    coordinator.conversation_id = "conv-a2ui"
    coordinator.prepare_request = AsyncMock(return_value=identity["hitlRequestId"])
    coordinator.wait_for_response = AsyncMock(
        return_value={
            "action_name": "approve",
            "source_component_id": "button-1",
            "context": {"approved": True, "reason": "fixture"},
        }
    )
    tool_part = _make_tool_part("call-a2ui", "canvas_create_interactive")
    manager = CanvasManager()
    configure_canvas(manager)

    events = [
        event
        async for event in handle_a2ui_action_tool(
            coordinator=coordinator,
            call_id="call-a2ui",
            tool_name="canvas_create_interactive",
            arguments={"title": "Review", "components": contract_case_jsonl(case)},
            tool_part=tool_part,
        )
    ]

    canvas_events = [event for event in events if isinstance(event, AgentCanvasUpdatedEvent)]
    asked_event = next(event for event in events if isinstance(event, AgentA2UIActionAskedEvent))
    answered_event = next(
        event for event in events if isinstance(event, AgentA2UIActionAnsweredEvent)
    )
    observe_event = next(event for event in events if isinstance(event, AgentObserveEvent))

    assert len(canvas_events) == 2
    assert canvas_events[0].block is not None
    assert canvas_events[0].block["metadata"] == {
        "surface_id": identity["metadataSurfaceId"],
        "hitl_request_id": identity["hitlRequestId"],
    }
    assert canvas_events[1].block is not None
    assert canvas_events[1].block["metadata"] == {
        "surface_id": identity["metadataSurfaceId"],
        "hitl_request_id": "",
    }

    assert asked_event.request_id == identity["hitlRequestId"]
    assert asked_event.block_id == canvas_events[0].block_id
    assert answered_event.request_id == identity["hitlRequestId"]
    assert answered_event.action_name == "approve"
    assert answered_event.source_component_id == "button-1"
    assert answered_event.context == {"approved": True, "reason": "fixture"}

    assert observe_event.result == {
        "action_name": "approve",
        "source_component_id": "button-1",
        "context": {"approved": True, "reason": "fixture"},
        "cancelled": False,
        "block_id": canvas_events[0].block_id,
    }
    assert tool_part.status == ToolState.COMPLETED
    assert json.loads(tool_part.output or "{}") == observe_event.result

    persisted_block = manager.get_block("conv-a2ui", canvas_events[0].block_id)
    assert persisted_block.metadata == {
        "surface_id": identity["metadataSurfaceId"],
        "hitl_request_id": "",
    }
    assert persisted_block.content == contract_case_jsonl(case)

    configure_canvas(None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a2ui_tool_reuses_existing_canvas_block() -> None:
    coordinator = MagicMock()
    coordinator.conversation_id = "conv-a2ui"
    coordinator.prepare_request = AsyncMock(return_value="a2ui-req-2")
    coordinator.wait_for_response = AsyncMock(
        return_value={
            "action_name": "submit",
            "source_component_id": "button-1",
            "context": {"approved": True},
        }
    )
    manager = CanvasManager()
    existing = manager.create_block(
        conversation_id="conv-a2ui",
        block_type="a2ui_surface",
        title="Existing",
        content=(
            '{"beginRendering":{"surfaceId":"surface-1","root":"button-1"}}\n'
            '{"surfaceUpdate":{"surfaceId":"surface-1","components":['
            '{"id":"label-1","component":{"Text":{"text":{"literalString":"Approve"}}}},'
            '{"id":"button-1","component":{"Button":{"child":"label-1","action":{"name":"submit"}}}}]}}'
        ),
        metadata={"surface_id": "surface-1"},
    )
    configure_canvas(manager)
    tool_part = _make_tool_part("call-a2ui", "canvas_create_interactive")

    components = "\n".join(
        [
            '{"beginRendering":{"surfaceId":"surface-1","root":"button-2"}}',
            '{"surfaceUpdate":{"surfaceId":"surface-1","components":[{"id":"label-2","component":{"Text":{"text":{"literalString":"Updated"}}}},{"id":"button-2","component":{"Button":{"child":"label-2","action":{"name":"submit"}}}}]}}',
        ]
    )

    events = [
        event
        async for event in handle_a2ui_action_tool(
            coordinator=coordinator,
            call_id="call-a2ui",
            tool_name="canvas_create_interactive",
            arguments={"title": "Review", "components": components, "block_id": existing.id},
            tool_part=tool_part,
        )
    ]

    canvas_events = [e for e in events if isinstance(e, AgentCanvasUpdatedEvent)]
    assert canvas_events[0].action == "updated"
    assert canvas_events[0].block_id == existing.id
    assert canvas_events[0].block is not None
    assert canvas_events[0].block["metadata"]["hitl_request_id"] == "a2ui-req-2"
    assert canvas_events[-1].block is not None
    assert canvas_events[-1].block["metadata"]["hitl_request_id"] == ""

    configure_canvas(None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a2ui_tool_rejects_existing_update_when_payload_omits_surface_id() -> None:
    coordinator = MagicMock()
    coordinator.conversation_id = "conv-a2ui"
    coordinator.prepare_request = AsyncMock(return_value="a2ui-req-3")
    coordinator.wait_for_response = AsyncMock(
        return_value={
            "action_name": "submit",
            "source_component_id": "button-1",
            "context": {"approved": True},
        }
    )
    manager = CanvasManager()
    existing = manager.create_block(
        conversation_id="conv-a2ui",
        block_type="a2ui_surface",
        title="Existing",
        content=(
            '{"beginRendering":{"surfaceId":"surface-1","root":"button-1"}}\n'
            '{"surfaceUpdate":{"surfaceId":"surface-1","components":['
            '{"id":"label-1","component":{"Text":{"text":{"literalString":"Approve"}}}},'
            '{"id":"button-1","component":{"Button":{"child":"label-1","action":{"name":"submit"}}}}]}}'
        ),
        metadata={"surface_id": "surface-1"},
    )
    configure_canvas(manager)
    tool_part = _make_tool_part("call-a2ui", "canvas_create_interactive")

    events = [
        event
        async for event in handle_a2ui_action_tool(
            coordinator=coordinator,
            call_id="call-a2ui",
            tool_name="canvas_create_interactive",
            arguments={
                "title": "Review",
                "components": '{"surfaceUpdate":{"components":[]}}',
                "block_id": existing.id,
            },
            tool_part=tool_part,
        )
    ]

    observe_event = next(e for e in events if isinstance(e, AgentObserveEvent))
    assert "must include surfaceId on every envelope" in (observe_event.error or "")
    coordinator.prepare_request.assert_not_awaited()
    assert tool_part.status == ToolState.ERROR
    assert manager.get_block("conv-a2ui", existing.id).content == existing.content
    assert not any(isinstance(event, AgentCanvasUpdatedEvent) for event in events)
    assert not any(isinstance(event, AgentA2UIActionAskedEvent) for event in events)

    configure_canvas(None)


class _FailingAttachCoordinator:
    def __init__(self) -> None:
        self.conversation_id = "conv-a2ui"
        self._pending: dict[str, asyncio.Future[object]] = {}

    async def prepare_request(self, *_args, **_kwargs) -> str:
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        self._pending["a2ui-req-4"] = future
        return "a2ui-req-4"

    @property
    def pending_request_ids(self) -> list[str]:
        return list(self._pending.keys())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a2ui_tool_rejects_non_actionable_existing_update() -> None:
    coordinator = MagicMock()
    coordinator.conversation_id = "conv-a2ui"
    coordinator.prepare_request = AsyncMock(return_value="a2ui-req-invalid-update")
    coordinator.pending_request_ids = []
    manager = CanvasManager()
    existing = manager.create_block(
        conversation_id="conv-a2ui",
        block_type="a2ui_surface",
        title="Existing",
        content=(
            '{"beginRendering":{"surfaceId":"surface-1","root":"button-1"}}\n'
            '{"surfaceUpdate":{"surfaceId":"surface-1","components":['
            '{"id":"label-1","component":{"Text":{"text":{"literalString":"Approve"}}}},'
            '{"id":"button-1","component":{"Button":{"child":"label-1","action":{"name":"submit"}}}}]}}'
        ),
        metadata={"surface_id": "surface-1"},
    )
    configure_canvas(manager)
    tool_part = _make_tool_part("call-a2ui", "canvas_create_interactive")

    events = [
        event
        async for event in handle_a2ui_action_tool(
            coordinator=coordinator,
            call_id="call-a2ui",
            tool_name="canvas_create_interactive",
            arguments={
                "title": "Review",
                "components": (
                    '{"surfaceUpdate":{"surfaceId":"surface-1","components":['
                    '{"id":"button-1","component":{"Text":{"text":{"literalString":"Updated"}}}}]}}'
                ),
                "block_id": existing.id,
            },
            tool_part=tool_part,
        )
    ]

    observe_event = next(e for e in events if isinstance(e, AgentObserveEvent))
    assert "interactive updates must still resolve" in (observe_event.error or "")
    coordinator.prepare_request.assert_not_awaited()
    assert tool_part.status == ToolState.ERROR
    assert manager.get_block("conv-a2ui", existing.id).content == existing.content
    assert not any(isinstance(event, AgentCanvasUpdatedEvent) for event in events)
    assert not any(isinstance(event, AgentA2UIActionAskedEvent) for event in events)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a2ui_tool_rejects_existing_update_with_drifted_surface_id() -> None:
    coordinator = MagicMock()
    coordinator.conversation_id = "conv-a2ui"
    coordinator.prepare_request = AsyncMock(return_value="a2ui-req-invalid-surface")
    coordinator.pending_request_ids = []
    manager = CanvasManager()
    existing = manager.create_block(
        conversation_id="conv-a2ui",
        block_type="a2ui_surface",
        title="Existing",
        content=(
            '{"beginRendering":{"surfaceId":"surface-1","root":"button-1"}}\n'
            '{"surfaceUpdate":{"surfaceId":"surface-1","components":['
            '{"id":"label-1","component":{"Text":{"text":{"literalString":"Approve"}}}},'
            '{"id":"button-1","component":{"Button":{"child":"label-1","action":{"name":"submit"}}}}]}}'
        ),
        metadata={"surface_id": "surface-1"},
    )
    configure_canvas(manager)
    tool_part = _make_tool_part("call-a2ui", "canvas_create_interactive")

    events = [
        event
        async for event in handle_a2ui_action_tool(
            coordinator=coordinator,
            call_id="call-a2ui",
            tool_name="canvas_create_interactive",
            arguments={
                "title": "Review",
                "components": (
                    '{"surfaceUpdate":{"surfaceId":"surface-2","components":['
                    '{"id":"label-2","component":{"Text":{"text":{"literalString":"Updated"}}}},'
                    '{"id":"button-2","component":{"Button":{"child":"label-2","action":{"name":"submit"}}}}]}}'
                ),
                "block_id": existing.id,
            },
            tool_part=tool_part,
        )
    ]

    observe_event = next(e for e in events if isinstance(e, AgentObserveEvent))
    assert "must use surfaceId 'surface-1'" in (observe_event.error or "")
    coordinator.prepare_request.assert_not_awaited()
    assert tool_part.status == ToolState.ERROR
    assert manager.get_block("conv-a2ui", existing.id).content == existing.content
    assert not any(isinstance(event, AgentCanvasUpdatedEvent) for event in events)
    assert not any(isinstance(event, AgentA2UIActionAskedEvent) for event in events)

    configure_canvas(None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a2ui_tool_cleans_prepared_request_when_metadata_attach_fails(monkeypatch) -> None:
    coordinator = _FailingAttachCoordinator()
    manager = CanvasManager()
    configure_canvas(manager)
    tool_part = _make_tool_part("call-a2ui", "canvas_create_interactive")
    cancelled_request_ids: list[str] = []

    def _raise_attach(*_args, **_kwargs):
        raise RuntimeError("attach failed")

    class _FakeSession:
        async def commit(self) -> None:
            return None

    class _FakeSessionFactory:
        async def __aenter__(self) -> _FakeSession:
            return _FakeSession()

        async def __aexit__(self, *_args) -> None:
            return None

    class _FakeRepo:
        def __init__(self, _session: _FakeSession) -> None:
            self._session = _session

        async def mark_cancelled(self, request_id: str) -> object:
            cancelled_request_ids.append(request_id)
            return object()

    monkeypatch.setattr(
        "src.infrastructure.agent.processor.hitl_tool_handler._attach_hitl_request_metadata",
        _raise_attach,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.processor.hitl_tool_handler.async_session_factory",
        _FakeSessionFactory,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.processor.hitl_tool_handler.SqlHITLRequestRepository",
        _FakeRepo,
    )

    events = [
        event
        async for event in handle_a2ui_action_tool(
            coordinator=coordinator,
            call_id="call-a2ui",
            tool_name="canvas_create_interactive",
            arguments={
                "title": "Review",
                "components": (
                    '{"beginRendering":{"surfaceId":"surface-1","root":"button-1"}}\n'
                    '{"surfaceUpdate":{"surfaceId":"surface-1","components":['
                    '{"id":"label-1","component":{"Text":{"text":{"literalString":"Approve"}}}},'
                    '{"id":"button-1","component":{"Button":{"child":"label-1","action":{"name":"submit"}}}}]}}'
                ),
            },
            tool_part=tool_part,
        )
    ]

    observe_event = next(e for e in events if isinstance(e, AgentObserveEvent))
    # Generic internal exceptions are redacted (P0-2 secret-leak fix); the
    # original RuntimeError is still logged via ``logger.exception``.
    assert observe_event.error is not None
    assert "see server logs" in observe_event.error
    assert "call_id=call-a2ui" in observe_event.error
    assert coordinator.pending_request_ids == []
    assert cancelled_request_ids == ["a2ui-req-4"]
    assert manager.get_blocks("conv-a2ui") == []

    configure_canvas(None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a2ui_tool_errors_when_reusing_non_a2ui_block() -> None:
    coordinator = MagicMock()
    coordinator.conversation_id = "conv-a2ui"
    manager = CanvasManager()
    existing = manager.create_block(
        conversation_id="conv-a2ui",
        block_type="markdown",
        title="Notes",
        content="# notes",
    )
    configure_canvas(manager)
    tool_part = _make_tool_part("call-a2ui", "canvas_create_interactive")

    events = [
        event
        async for event in handle_a2ui_action_tool(
            coordinator=coordinator,
            call_id="call-a2ui",
            tool_name="canvas_create_interactive",
            arguments={
                "title": "Review",
                "components": '{"beginRendering":{"surfaceId":"surface-1","root":"root-1"}}',
                "block_id": existing.id,
            },
            tool_part=tool_part,
        )
    ]

    observe_event = next(e for e in events if isinstance(e, AgentObserveEvent))
    assert "not an A2UI surface" in (observe_event.error or "")

    configure_canvas(None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a2ui_tool_rejects_flat_surface_object_before_waiting() -> None:
    coordinator = MagicMock()
    coordinator.conversation_id = "conv-a2ui"
    coordinator.prepare_request = AsyncMock(return_value="a2ui-req-invalid")
    coordinator.pending_request_ids = []
    manager = CanvasManager()
    configure_canvas(manager)
    tool_part = _make_tool_part("call-a2ui", "canvas_create_interactive")

    events = [
        event
        async for event in handle_a2ui_action_tool(
            coordinator=coordinator,
            call_id="call-a2ui",
            tool_name="canvas_create_interactive",
            arguments={
                "title": "Review",
                "components": (
                    '{"surfaceId":"surface-1","components":['
                    '{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}'
                ),
            },
            tool_part=tool_part,
        )
    ]

    observe_event = next(e for e in events if isinstance(e, AgentObserveEvent))
    assert "beginRendering/surfaceUpdate envelopes" in (observe_event.error or "")
    coordinator.prepare_request.assert_not_awaited()
    assert tool_part.status == ToolState.ERROR
    assert manager.get_blocks("conv-a2ui") == []
    assert not any(isinstance(event, AgentCanvasUpdatedEvent) for event in events)
    assert not any(isinstance(event, AgentA2UIActionAskedEvent) for event in events)

    configure_canvas(None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a2ui_tool_rejects_malformed_json_before_waiting() -> None:
    coordinator = MagicMock()
    coordinator.conversation_id = "conv-a2ui"
    coordinator.prepare_request = AsyncMock(return_value="a2ui-req-invalid")
    coordinator.pending_request_ids = []
    manager = CanvasManager()
    configure_canvas(manager)
    tool_part = _make_tool_part("call-a2ui", "canvas_create_interactive")

    events = [
        event
        async for event in handle_a2ui_action_tool(
            coordinator=coordinator,
            call_id="call-a2ui",
            tool_name="canvas_create_interactive",
            arguments={
                "title": "Review",
                "components": "\n".join(
                    [
                        '{"beginRendering":{"surfaceId":"surface-1","root":"button-1"}}',
                        '{"broken":',
                        '{"surfaceUpdate":{"surfaceId":"surface-1","components":['
                        '{"id":"label-1","component":{"Text":{"text":{"literalString":"Approve"}}}},'
                        '{"id":"button-1","component":{"Button":{"child":"label-1","action":{"name":"submit"}}}}]}}',
                    ]
                ),
            },
            tool_part=tool_part,
        )
    ]

    observe_event = next(e for e in events if isinstance(e, AgentObserveEvent))
    assert "malformed JSON" in (observe_event.error or "")
    coordinator.prepare_request.assert_not_awaited()
    assert tool_part.status == ToolState.ERROR
    assert manager.get_blocks("conv-a2ui") == []
    assert not any(isinstance(event, AgentCanvasUpdatedEvent) for event in events)
    assert not any(isinstance(event, AgentA2UIActionAskedEvent) for event in events)

    configure_canvas(None)
