# pyright: reportUninitializedInstanceVariable=false
"""Hook mixin extracted from ``react_agent.py``.

Hosts runtime-hook dispatch helpers (``_notify_runtime_hook``,
``_apply_before_prompt_build_hook``, ``_notify_context_overflow_hook``,
``_notify_after_turn_complete_hook``). All of them route through the
shared plugin registry on ``self.config``.

``ReActAgent`` composes this mixin via multiple inheritance — the move
is pure code relocation with zero behavior change.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, cast

from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.skill import Skill

logger = logging.getLogger(__name__)


class _HookAgent(Protocol):
    """Subset of ``ReActAgent`` state used by :class:`HookMixin`."""

    config: Any
    _memory_runtime: Any
    _stream_memory_context: Any

    async def _notify_runtime_hook(
        self, hook_name: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...


class HookMixin:
    """Runtime-hook dispatch helpers (notify / before_prompt_build / overflow / after_turn)."""

    async def _notify_runtime_hook(
        self: _HookAgent,
        hook_name: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Dispatch one runtime hook via the shared plugin registry."""
        effective_payload = dict(payload or {})
        plugin_registry = getattr(self.config, "plugin_registry", None)
        if plugin_registry is None:
            return effective_payload

        try:
            result = await plugin_registry.apply_hook(
                hook_name,
                payload=effective_payload,
                runtime_overrides=getattr(self.config, "runtime_hook_overrides", []),
            )
            for diagnostic in result.diagnostics:
                log_level = logging.ERROR if diagnostic.level == "error" else logging.WARNING
                logger.log(
                    log_level,
                    "[ReActAgent] Runtime hook %s diagnostic [%s]: %s",
                    hook_name,
                    diagnostic.plugin_name,
                    diagnostic.message,
                )
            return dict(result.payload)
        except Exception:
            logger.warning("[ReActAgent] Runtime hook %r failed", hook_name, exc_info=True)
            return effective_payload

    async def _apply_before_prompt_build_hook(
        self: _HookAgent,
        *,
        processed_user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        effective_mode: str,
        matched_skill: Skill | None,
        selected_agent: Agent,
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Allow runtime hooks to refine prompt-bound memory context."""
        hook_payload = await self._notify_runtime_hook(
            "before_prompt_build",
            {
                "project_id": project_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "mode": effective_mode,
                "user_message": processed_user_message,
                "conversation_context": list(conversation_context),
                "memory_context": self._stream_memory_context,
                "memory_runtime": self._memory_runtime,
                "matched_skill_name": matched_skill.name if matched_skill else None,
                "selected_agent_id": selected_agent.id,
                "selected_agent_name": selected_agent.name,
            },
        )
        memory_context = hook_payload.get("memory_context", self._stream_memory_context)
        if memory_context is not None and not isinstance(memory_context, str):
            memory_context = self._stream_memory_context
        self._stream_memory_context = cast(str | None, memory_context)
        emitted_events = hook_payload.get("emitted_events")
        return self._stream_memory_context, (
            list(emitted_events) if isinstance(emitted_events, list) else []
        )

    async def _notify_context_overflow_hook(
        self: _HookAgent,
        *,
        tenant_id: str,
        project_id: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        context_result: Any,
    ) -> list[dict[str, Any]]:
        """Emit a runtime hook when context overflow causes compression."""
        hook_payload = await self._notify_runtime_hook(
            "on_context_overflow",
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "conversation_id": conversation_id,
                "conversation_context": list(conversation_context),
                "memory_runtime": self._memory_runtime,
                "compression_level": context_result.compression_strategy.value,
                "summary_text": context_result.summary,
                "original_message_count": context_result.original_message_count,
                "final_message_count": context_result.final_message_count,
                "summarized_message_count": context_result.summarized_message_count,
                "estimated_tokens": context_result.estimated_tokens,
            },
        )
        emitted_events = hook_payload.get("emitted_events")
        return list(emitted_events) if isinstance(emitted_events, list) else []

    async def _notify_after_turn_complete_hook(
        self: _HookAgent,
        *,
        processed_user_message: str,
        final_content: str,
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        matched_skill: Skill | None,
        success: bool,
        execution_time_ms: int = 0,
        tool_call_count: int = 0,
        llm_client_override: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Emit a runtime hook after turn completion side effects finish."""
        hook_payload = await self._notify_runtime_hook(
            "after_turn_complete",
            {
                "project_id": project_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "conversation_context": list(conversation_context),
                "user_message": processed_user_message,
                "final_content": final_content,
                "memory_runtime": self._memory_runtime,
                "matched_skill_name": matched_skill.name if matched_skill else None,
                "success": success,
                "execution_time_ms": execution_time_ms,
                "tool_call_count": tool_call_count,
                "llm_client_override": llm_client_override,
            },
        )
        emitted_events = hook_payload.get("emitted_events")
        return list(emitted_events) if isinstance(emitted_events, list) else []
