"""Adapter from processor lifecycle hooks to the pinned protocol-v2 event bus."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol, cast

from .agent_events import (
    AGENT_BEFORE_REQUEST_EVENT_V2,
    AGENT_SESSION_START_EVENT_V2,
    TOOLS_AFTER_EXECUTE_EVENT_V2,
)
from .boundary import current_operation_context_v2
from .runtime import OperationContextV2, RuntimeV2Error


class _DispatchResultLike(Protocol):
    payload: Mapping[str, Any]
    diagnostics: Sequence[object]
    denied: bool


class _FallbackDispatcher(Protocol):
    async def dispatch(
        self,
        hook_name: str,
        payload: Mapping[str, Any] | None = None,
        *,
        runtime_hook_overrides: list[dict[str, Any]] | None = None,
    ) -> _DispatchResultLike: ...


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
    }
)
_WORKSPACE_SESSION_ROLES = frozenset({"leader", "worker", "contract"})


@dataclass(frozen=True, kw_only=True)
class PinnedAgentRuntimeDispatcherV2:
    """Dispatch migrated hooks through the immutable operation generation.

    A fallback is explicit and is used only for hook names that do not yet have
    a public V2 event contract. Once the remaining hooks have V2 modules, the
    fallback can be removed without changing processor call sites.
    """

    fallback: _FallbackDispatcher | None = None

    async def dispatch(
        self,
        hook_name: str,
        payload: Mapping[str, Any] | None = None,
        *,
        runtime_hook_overrides: list[dict[str, Any]] | None = None,
    ) -> AgentRuntimeDispatchResultV2:
        effective_payload = dict(payload or {})
        event = _V2_EVENT_BY_PROCESSOR_HOOK.get(hook_name)
        if event is None:
            return await self._dispatch_fallback(
                hook_name,
                effective_payload,
                runtime_hook_overrides=runtime_hook_overrides,
            )

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
        return AgentRuntimeDispatchResultV2(
            payload=_merge_instruction_contributions(effective_payload, raw_results),
        )

    async def _dispatch_fallback(
        self,
        hook_name: str,
        payload: dict[str, Any],
        *,
        runtime_hook_overrides: list[dict[str, Any]] | None,
    ) -> AgentRuntimeDispatchResultV2:
        if self.fallback is None:
            return AgentRuntimeDispatchResultV2(payload=payload)
        result = await self.fallback.dispatch(
            hook_name,
            payload=payload,
            runtime_hook_overrides=runtime_hook_overrides,
        )
        return AgentRuntimeDispatchResultV2(
            payload=dict(result.payload),
            diagnostics=tuple(result.diagnostics),
            denied=bool(result.denied),
        )


async def _dispatch_migrated_event_v2(
    operation: OperationContextV2,
    *,
    event: str,
    payload: Mapping[str, object],
) -> object:
    if event == AGENT_SESSION_START_EVENT_V2:
        return await operation.dispatch("agent.session.start", payload)
    if event == AGENT_BEFORE_REQUEST_EVENT_V2:
        return await operation.dispatch("agent.before_request", payload)
    if event == TOOLS_AFTER_EXECUTE_EVENT_V2:
        return await operation.dispatch("tools.after_execute", payload)
    raise RuntimeV2Error(
        "undeclared_agent_event",
        f"Agent processor event {event} is not declared by the V2 dispatcher",
    )


def _build_event_payload_v2(
    operation: OperationContextV2,
    *,
    event: str,
    payload: Mapping[str, Any],
) -> dict[str, object]:
    scope = operation.context.scope
    required_scope = {
        "tenant_id": scope.tenant_id,
        "project_id": scope.project_id,
        "session_id": scope.session_id,
    }
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

    if event == TOOLS_AFTER_EXECUTE_EVENT_V2:
        tool_name = payload.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name:
            raise RuntimeV2Error(
                "invalid_agent_event_context",
                "tools.after_execute requires a non-empty tool_name",
            )
        event_payload["tool_name"] = tool_name
        call_id = payload.get("call_id")
        event_payload["tool_result_event_id"] = (
            call_id if isinstance(call_id, str) and call_id else event_id
        )
    return event_payload


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


__all__ = ["AgentRuntimeDispatchResultV2", "PinnedAgentRuntimeDispatcherV2"]
