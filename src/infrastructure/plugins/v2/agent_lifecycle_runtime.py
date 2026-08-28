"""Generation-owned memory and skill-evolution Agent lifecycle effects."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, cast, runtime_checkable

from src.infrastructure.agent.memory.runtime import MemoryRuntimeProtocol
from src.infrastructure.audit.audit_log_service import get_audit_service

from .runtime import ContextV2, PluginDefinitionV2, RuntimeV2Error, generated_contract_digest_v2

AGENT_BEFORE_PROMPT_BUILD_EVENT_V2 = "agent.before_prompt_build"
AGENT_CONTEXT_OVERFLOW_EVENT_V2 = "agent.context_overflow"
AGENT_AFTER_TURN_COMPLETE_EVENT_V2 = "agent.after_turn_complete"
AGENT_SKILL_TOOL_OBSERVED_EVENT_V2 = "agent.skill_tool_observed"

MEMORY_LIFECYCLE_MODULE_V2 = "builtin://memstack/agent/memory-lifecycle"
SKILL_EVOLUTION_LIFECYCLE_MODULE_V2 = "builtin://memstack/agent/skill-evolution-lifecycle"
SKILL_EVOLUTION_SCHEDULER_INJECT_V2 = "scheduler"

type WaterfallNextV2 = Callable[[object], Awaitable[object]]

logger = logging.getLogger(__name__)


@runtime_checkable
class _SkillEvolutionSchedulerProtocolV2(Protocol):
    async def record_tool_event(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    async def capture_turn(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    def schedule_evolution(
        self,
        *,
        tenant_id: str,
        project_id: str | None = None,
        skill_name: str | None = None,
        reason: str = "manual",
    ) -> dict[str, Any]: ...


def _append_emitted_events(
    payload: Mapping[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    updated = dict(payload)
    current = updated.get("emitted_events")
    emitted_events = list(current) if isinstance(current, list) else []
    emitted_events.extend(events)
    updated["emitted_events"] = emitted_events
    return updated


async def _continue_waterfall(
    next_: WaterfallNextV2,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    result = await next_(dict(payload))
    if not isinstance(result, Mapping):
        raise RuntimeV2Error(
            "invalid_agent_lifecycle_result",
            "Agent lifecycle waterfall returned a non-object payload",
        )
    return dict(result)


def _memory_runtime(payload: Mapping[str, Any]) -> MemoryRuntimeProtocol | None:
    runtime = payload.get("memory_runtime")
    return None if runtime is None else cast("MemoryRuntimeProtocol", runtime)


async def _log_memory_audit(
    *,
    action: str,
    payload: Mapping[str, Any],
    details: dict[str, Any],
) -> None:
    from src.configuration.config import get_settings

    if not get_settings().agent_memory_failure_persistence_enabled:
        return
    try:
        await get_audit_service().log_event(
            action=action,
            resource_type="runtime_hook_v2",
            resource_id=f"memory-lifecycle:{payload.get('conversation_id') or 'unknown'}",
            actor="system",
            tenant_id=str(payload.get("tenant_id")) if payload.get("tenant_id") else None,
            details={
                "event": payload.get("lifecycle_event"),
                "project_id": payload.get("project_id"),
                "conversation_id": payload.get("conversation_id"),
                **details,
            },
        )
    except Exception:
        logger.debug("Memory lifecycle audit logging failed", exc_info=True)


async def _before_prompt_build(
    payload: Mapping[str, Any],
    next_: WaterfallNextV2,
) -> dict[str, Any]:
    runtime = _memory_runtime(payload)
    if runtime is None:
        return await _continue_waterfall(next_, payload)
    try:
        result = await runtime.recall_for_prompt(
            user_message=str(payload.get("user_message", "")),
            project_id=str(payload.get("project_id", "")),
        )
    except Exception as exc:
        await _log_memory_audit(
            action="runtime_hook.memory_recall_failed",
            payload=payload,
            details={"error": str(exc), "error_type": type(exc).__name__},
        )
        raise
    updated = dict(payload)
    updated["memory_context"] = result.memory_context
    return await _continue_waterfall(
        next_,
        _append_emitted_events(updated, result.emitted_events),
    )


async def _on_context_overflow(
    payload: Mapping[str, Any],
    next_: WaterfallNextV2,
) -> dict[str, Any]:
    runtime = _memory_runtime(payload)
    if runtime is None:
        return await _continue_waterfall(next_, payload)
    try:
        result = await runtime.flush_on_context_overflow(
            conversation_context=list(payload.get("conversation_context", [])),
            project_id=str(payload.get("project_id", "")),
            conversation_id=str(payload.get("conversation_id", "")),
        )
    except Exception as exc:
        await _log_memory_audit(
            action="runtime_hook.memory_flush_failed",
            payload=payload,
            details={"error": str(exc), "error_type": type(exc).__name__},
        )
        raise
    return await _continue_waterfall(
        next_,
        _append_emitted_events(payload, result.emitted_events),
    )


async def _capture_memory_after_turn(
    payload: Mapping[str, Any],
    next_: WaterfallNextV2,
) -> dict[str, Any]:
    runtime = _memory_runtime(payload)
    if runtime is None:
        return await _continue_waterfall(next_, payload)
    try:
        result = await runtime.capture_after_turn(
            user_message=str(payload.get("user_message", "")),
            final_content=str(payload.get("final_content", "")),
            project_id=str(payload.get("project_id", "")),
            conversation_id=str(payload.get("conversation_id", "")),
            conversation_context=list(payload.get("conversation_context", [])),
            success=bool(payload.get("success", False)),
            llm_client_override=payload.get("llm_client_override"),
        )
    except Exception as exc:
        await _log_memory_audit(
            action="runtime_hook.memory_capture_failed",
            payload=payload,
            details={"error": str(exc), "error_type": type(exc).__name__},
        )
        raise
    return await _continue_waterfall(
        next_,
        _append_emitted_events(payload, result.emitted_events),
    )


def _apply_memory_lifecycle_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config:
        raise ValueError("memory lifecycle module does not accept config")
    _ = context.on(AGENT_BEFORE_PROMPT_BUILD_EVENT_V2, _before_prompt_build)
    _ = context.on(AGENT_CONTEXT_OVERFLOW_EVENT_V2, _on_context_overflow)
    _ = context.on(AGENT_AFTER_TURN_COMPLETE_EVENT_V2, _capture_memory_after_turn)


def _apply_skill_evolution_lifecycle_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config:
        raise ValueError("skill evolution lifecycle module does not accept config")
    scheduler = context.require(SKILL_EVOLUTION_SCHEDULER_INJECT_V2)
    if not isinstance(scheduler, _SkillEvolutionSchedulerProtocolV2):
        raise RuntimeV2Error(
            "invalid_skill_evolution_scheduler",
            "Skill Evolution lifecycle scheduler inject has an invalid implementation",
        )

    async def record_tool_event(payload: Mapping[str, Any]) -> None:
        _ = await scheduler.record_tool_event(payload)

    async def capture_turn(
        payload: Mapping[str, Any],
        next_: WaterfallNextV2,
    ) -> dict[str, Any]:
        updated = await scheduler.capture_turn(payload)
        return await _continue_waterfall(next_, updated)

    _ = context.on(AGENT_SKILL_TOOL_OBSERVED_EVENT_V2, record_tool_event)
    _ = context.on(AGENT_AFTER_TURN_COMPLETE_EVENT_V2, capture_turn)


def agent_lifecycle_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    return (
        PluginDefinitionV2(
            module_ref=SKILL_EVOLUTION_LIFECYCLE_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SKILL_EVOLUTION_LIFECYCLE_MODULE_V2),
            apply=_apply_skill_evolution_lifecycle_v2,
        ),
        PluginDefinitionV2(
            module_ref=MEMORY_LIFECYCLE_MODULE_V2,
            contract_digest=generated_contract_digest_v2(MEMORY_LIFECYCLE_MODULE_V2),
            apply=_apply_memory_lifecycle_v2,
        ),
    )


__all__ = [
    "AGENT_AFTER_TURN_COMPLETE_EVENT_V2",
    "AGENT_BEFORE_PROMPT_BUILD_EVENT_V2",
    "AGENT_CONTEXT_OVERFLOW_EVENT_V2",
    "AGENT_SKILL_TOOL_OBSERVED_EVENT_V2",
    "MEMORY_LIFECYCLE_MODULE_V2",
    "SKILL_EVOLUTION_LIFECYCLE_MODULE_V2",
    "SKILL_EVOLUTION_SCHEDULER_INJECT_V2",
    "agent_lifecycle_definitions_v2",
]
