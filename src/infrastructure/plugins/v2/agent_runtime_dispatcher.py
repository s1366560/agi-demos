"""Adapter from processor lifecycle hooks to the pinned protocol-v2 event bus."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol, cast, runtime_checkable

from .agent_events import (
    AGENT_AFTER_TURN_COMPLETE_EVENT_V2,
    AGENT_BEFORE_PROMPT_BUILD_EVENT_V2,
    AGENT_BEFORE_REQUEST_EVENT_V2,
    AGENT_CONTEXT_OVERFLOW_EVENT_V2,
    AGENT_SESSION_START_EVENT_V2,
    AGENT_SKILL_TOOL_OBSERVED_EVENT_V2,
    TOOLS_AFTER_EXECUTE_EVENT_V2,
)
from .runtime import OperationContextV2, RuntimeV2Error

AGENT_RUNTIME_DISPATCHER_SERVICE_V2 = "service:agent-runtime-dispatcher"


@runtime_checkable
class AgentRuntimeDispatcherProtocolV2(Protocol):
    """Generation-owned seam used by the Agent processor lifecycle."""

    async def dispatch(
        self,
        hook_name: str,
        payload: Mapping[str, Any] | None = None,
    ) -> AgentRuntimeDispatchResultV2: ...


@dataclass(frozen=True, kw_only=True)
class AgentRuntimeDispatchResultV2:
    """Effective internal payload after generation-owned event contributions."""

    payload: dict[str, Any]
    diagnostics: tuple[object, ...] = ()
    denied: bool = False


_V2_EVENT_BY_PROCESSOR_HOOK = MappingProxyType(
    {
        "on_session_start": AGENT_SESSION_START_EVENT_V2,
        "before_response": AGENT_BEFORE_REQUEST_EVENT_V2,
        "after_tool_execution": TOOLS_AFTER_EXECUTE_EVENT_V2,
        "before_prompt_build": AGENT_BEFORE_PROMPT_BUILD_EVENT_V2,
        "on_context_overflow": AGENT_CONTEXT_OVERFLOW_EVENT_V2,
        "after_turn_complete": AGENT_AFTER_TURN_COMPLETE_EVENT_V2,
    }
)
_WORKSPACE_SESSION_ROLES = frozenset({"leader", "worker", "contract"})


@dataclass(frozen=True, kw_only=True)
class PinnedAgentRuntimeDispatcherV2:
    """Dispatch declared hooks through the immutable operation generation."""

    async def dispatch(
        self,
        hook_name: str,
        payload: Mapping[str, Any] | None = None,
    ) -> AgentRuntimeDispatchResultV2:
        effective_payload = dict(payload or {})
        event = _V2_EVENT_BY_PROCESSOR_HOOK.get(hook_name)
        if event is None:
            return AgentRuntimeDispatchResultV2(payload=effective_payload)

        from .boundary import current_operation_context_v2

        operation = current_operation_context_v2()
        event_payload = _build_event_payload_v2(
            operation,
            event=event,
            payload=effective_payload,
        )
        raw_results = await _dispatch_migrated_event_v2(
            operation,
            event=event,
            payload=event_payload,
        )
        if event == TOOLS_AFTER_EXECUTE_EVENT_V2:
            await _dispatch_migrated_event_v2(
                operation,
                event=AGENT_SKILL_TOOL_OBSERVED_EVENT_V2,
                payload=_build_event_payload_v2(
                    operation,
                    event=AGENT_SKILL_TOOL_OBSERVED_EVENT_V2,
                    payload=effective_payload,
                ),
            )
        if event in {
            AGENT_SESSION_START_EVENT_V2,
            AGENT_BEFORE_REQUEST_EVENT_V2,
            TOOLS_AFTER_EXECUTE_EVENT_V2,
        }:
            resolved_payload = _merge_instruction_contributions(effective_payload, raw_results)
        elif isinstance(raw_results, Mapping):
            resolved_payload = dict(raw_results)
        else:
            raise RuntimeV2Error(
                "invalid_agent_event_result",
                f"Agent lifecycle event {event} did not return an object payload",
            )
        return AgentRuntimeDispatchResultV2(payload=resolved_payload)


async def _dispatch_migrated_event_v2(
    operation: OperationContextV2,
    *,
    event: str,
    payload: Mapping[str, object],
) -> object:
    if event == AGENT_SESSION_START_EVENT_V2:
        result = await operation.dispatch("agent.session.start", payload)
    elif event == AGENT_BEFORE_REQUEST_EVENT_V2:
        result = await operation.dispatch("agent.before_request", payload)
    elif event == TOOLS_AFTER_EXECUTE_EVENT_V2:
        result = await operation.dispatch("tools.after_execute", payload)
    elif event == AGENT_BEFORE_PROMPT_BUILD_EVENT_V2:
        result = await operation.dispatch("agent.before_prompt_build", payload)
    elif event == AGENT_CONTEXT_OVERFLOW_EVENT_V2:
        result = await operation.dispatch("agent.context_overflow", payload)
    elif event == AGENT_AFTER_TURN_COMPLETE_EVENT_V2:
        result = await operation.dispatch("agent.after_turn_complete", payload)
    elif event == AGENT_SKILL_TOOL_OBSERVED_EVENT_V2:
        result = await operation.dispatch("agent.skill_tool_observed", payload)
    else:
        raise RuntimeV2Error(
            "undeclared_agent_event",
            f"Agent processor event {event} is not declared by the V2 dispatcher",
        )
    return result


def _build_event_payload_v2(
    operation: OperationContextV2,
    *,
    event: str,
    payload: Mapping[str, Any],
) -> dict[str, object]:
    scope = operation.context.scope
    _validate_event_scope_v2(
        payload,
        required_scope={
            "tenant_id": scope.tenant_id,
            "project_id": scope.project_id,
            "session_id": scope.session_id,
        },
    )

    event_id = f"{operation.operation_id}:{event}:{uuid.uuid4().hex}"
    event_payload: dict[str, object] = {
        "conversation_id": scope.session_id,
        "event_id": event_id,
        "generation_digest": operation.generation.digest,
        "operation_id": operation.operation_id,
        "project_id": scope.project_id,
        "session_id": scope.session_id,
        "tenant_id": scope.tenant_id,
    }
    if event in {
        AGENT_BEFORE_PROMPT_BUILD_EVENT_V2,
        AGENT_CONTEXT_OVERFLOW_EVENT_V2,
        AGENT_AFTER_TURN_COMPLETE_EVENT_V2,
    }:
        event_payload = {**payload, **event_payload}
    _add_workspace_event_context_v2(event_payload, payload)
    if event in {TOOLS_AFTER_EXECUTE_EVENT_V2, AGENT_SKILL_TOOL_OBSERVED_EVENT_V2}:
        _add_tool_event_context_v2(
            event_payload,
            payload,
            event_id=event_id,
            include_result=event == AGENT_SKILL_TOOL_OBSERVED_EVENT_V2,
        )
    return event_payload


def _validate_event_scope_v2(
    payload: Mapping[str, Any],
    *,
    required_scope: Mapping[str, str | None],
) -> None:
    for field, expected in required_scope.items():
        if not isinstance(expected, str) or not expected:
            raise RuntimeV2Error(
                "invalid_agent_event_scope",
                f"pinned Agent operation has no {field}",
            )
        supplied = payload.get(field)
        if supplied is not None and supplied != expected:
            raise RuntimeV2Error(
                "agent_event_scope_mismatch",
                f"Agent event {field} differs from the pinned operation",
            )


def _add_workspace_event_context_v2(
    event_payload: dict[str, object],
    payload: Mapping[str, Any],
) -> None:
    if payload.get("task_authority") == "workspace":
        event_payload["task_authority"] = "workspace"
    workspace_id = payload.get("workspace_id")
    if isinstance(workspace_id, str) and workspace_id:
        event_payload["workspace_id"] = workspace_id
    workspace_role = payload.get("workspace_session_role")
    if isinstance(workspace_role, str) and workspace_role:
        if workspace_role not in _WORKSPACE_SESSION_ROLES:
            raise RuntimeV2Error(
                "invalid_agent_event_context",
                "workspace_session_role is not declared by the Agent event contract",
            )
        event_payload["workspace_session_role"] = workspace_role


def _add_tool_event_context_v2(
    event_payload: dict[str, object],
    payload: Mapping[str, Any],
    *,
    event_id: str,
    include_result: bool,
) -> None:
    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name:
        raise RuntimeV2Error(
            "invalid_agent_event_context",
            "tool lifecycle event requires a non-empty tool_name",
        )
    event_payload["tool_name"] = tool_name
    call_id = payload.get("call_id")
    event_payload["tool_result_event_id"] = (
        call_id if isinstance(call_id, str) and call_id else event_id
    )
    if not include_result:
        return
    if isinstance(call_id, str) and call_id:
        event_payload["call_id"] = call_id
    error = payload.get("error")
    if error:
        event_payload["error"] = str(error)[:500]
    metadata = payload.get("result_metadata")
    if isinstance(metadata, Mapping):
        event_payload["result_metadata"] = _json_safe_mapping(metadata)
    result = payload.get("result")
    if result is not None:
        event_payload["tool_result_text"] = str(result)[:1200]


def _json_safe_mapping(value: Mapping[object, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            continue
        normalized = _json_safe_value(item)
        if normalized is not _UNSAFE_VALUE:
            result[key] = normalized
    return result


_UNSAFE_VALUE = object()


def _json_safe_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return _json_safe_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        normalized: list[object] = []
        for item in value:
            safe_item = _json_safe_value(item)
            if safe_item is not _UNSAFE_VALUE:
                normalized.append(safe_item)
        return normalized
    return _UNSAFE_VALUE


def _merge_instruction_contributions(
    payload: dict[str, Any],
    raw_results: object,
) -> dict[str, Any]:
    if not isinstance(raw_results, tuple):
        raise RuntimeV2Error(
            "invalid_agent_event_result",
            "serial Agent event dispatch did not return an ordered result tuple",
        )
    merged = dict(payload)
    for field in ("session_instructions", "response_instructions"):
        current = merged.get(field)
        values = (
            [item for item in cast(list[object], current) if isinstance(item, str)]
            if isinstance(current, list)
            else []
        )
        for raw_result in cast(tuple[object, ...], raw_results):
            if raw_result is None:
                continue
            if not isinstance(raw_result, Mapping):
                raise RuntimeV2Error(
                    "invalid_agent_event_result",
                    "Agent event contribution must be an object or null",
                )
            contribution = cast(Mapping[str, object], raw_result).get(field)
            if not isinstance(contribution, list):
                continue
            for item in cast(list[object], contribution):
                if isinstance(item, str) and item not in values:
                    values.append(item)
        merged[field] = values
    return merged


__all__ = [
    "AGENT_RUNTIME_DISPATCHER_SERVICE_V2",
    "AgentRuntimeDispatchResultV2",
    "AgentRuntimeDispatcherProtocolV2",
    "PinnedAgentRuntimeDispatcherV2",
]
