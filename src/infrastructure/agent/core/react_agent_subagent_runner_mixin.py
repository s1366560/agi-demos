# pyright: reportUninitializedInstanceVariable=false
"""SubAgent runner mixin extracted from ``react_agent.py``.

Hosts the SubAgent execution / lifecycle / launch / cancel helpers that
delegate to ``SubAgentSessionRunner``. ``ReActAgent`` composes this mixin
via multiple inheritance — the move is pure code relocation with zero
behavior change.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any, Protocol, cast

from src.domain.model.agent.subagent import SubAgent

from .subagent_runner import SubAgentSessionRunner

logger = logging.getLogger(__name__)


class _RunnerAgent(Protocol):
    """Subset of ``ReActAgent`` state used by :class:`SubAgentRunnerMixin`."""

    _session_runner: Any


class SubAgentRunnerMixin:
    """SubAgent runtime helpers (execution, launch, lifecycle, cancellation)."""

    async def _execute_subagent(
        self: _RunnerAgent,
        subagent: SubAgent,
        user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str = "",
        abort_signal: asyncio.Event | None = None,
        delegation_depth: int = 0,
        model_override: str | None = None,
        thinking_override: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute a SubAgent in an independent ReAct loop."""
        async for evt in self._session_runner.execute_subagent(
            subagent=subagent,
            user_message=user_message,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            abort_signal=abort_signal,
            delegation_depth=delegation_depth,
            model_override=model_override,
            thinking_override=thinking_override,
        ):
            yield evt

    async def _execute_parallel(
        self: _RunnerAgent,
        subtasks: list[Any],
        user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str | None = None,
        route_id: str | None = None,
        abort_signal: asyncio.Event | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute multiple SubAgents in parallel."""
        async for evt in self._session_runner.execute_parallel(
            subtasks=subtasks,
            user_message=user_message,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            route_id=route_id,
            abort_signal=abort_signal,
        ):
            yield evt

    async def _execute_chain(
        self: _RunnerAgent,
        subtasks: list[Any],
        user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str | None = None,
        route_id: str | None = None,
        abort_signal: asyncio.Event | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute SubAgents as a sequential chain."""
        async for evt in self._session_runner.execute_chain(
            subtasks=subtasks,
            user_message=user_message,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            route_id=route_id,
            abort_signal=abort_signal,
        ):
            yield evt

    async def _execute_background(
        self: _RunnerAgent,
        subagent: SubAgent,
        user_message: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Launch a SubAgent for background execution."""
        async for evt in self._session_runner.execute_background(
            subagent=subagent,
            user_message=user_message,
            conversation_id=conversation_id,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
        ):
            yield evt

    async def _emit_subagent_lifecycle_hook(
        self: _RunnerAgent,
        event: dict[str, Any],
    ) -> None:
        """Emit detached SubAgent lifecycle hook event."""
        await self._session_runner.emit_subagent_lifecycle_hook(event)

    def _get_subagent_observability_stats(self: _RunnerAgent) -> dict[str, int]:
        """Return subagent lifecycle observability counters."""
        return cast(dict[str, int], self._session_runner.get_subagent_observability_stats())

    def _runner_resolve_overrides(
        self: _RunnerAgent,
        conversation_id: str,
        run_id: str,
        requested_model: str | None,
        requested_thinking: str | None,
        normalized_spawn_mode: str,
        thread_requested: bool,
        normalized_cleanup: str,
    ) -> tuple[str | None, str | None, float]:
        """Resolve model/thinking overrides."""
        return cast(tuple[str | None, str | None, float], self._session_runner.runner_resolve_overrides(
            conversation_id=conversation_id,
            run_id=run_id,
            requested_model=requested_model,
            requested_thinking=requested_thinking,
            normalized_spawn_mode=normalized_spawn_mode,
            thread_requested=thread_requested,
            normalized_cleanup=normalized_cleanup,
        ))

    def _runner_mark_completion(
        self: _RunnerAgent,
        conversation_id: str,
        run_id: str,
        result_success: bool,
        result_error: str | None,
        summary: str,
        tokens_used: int | None,
        execution_time_ms: int | None,
        started_at: float,
    ) -> None:
        """Mark a SubAgent run as completed or failed."""
        self._session_runner.runner_mark_completion(
            conversation_id=conversation_id,
            run_id=run_id,
            result_success=result_success,
            result_error=result_error,
            summary=summary,
            tokens_used=tokens_used,
            execution_time_ms=execution_time_ms,
            started_at=started_at,
        )

    def _runner_mark_timeout(
        self: _RunnerAgent,
        conversation_id: str,
        run_id: str,
        configured_timeout: float,
    ) -> None:
        """Handle TimeoutError for a SubAgent runner."""
        self._session_runner.runner_mark_timeout(
            conversation_id=conversation_id,
            run_id=run_id,
            configured_timeout=configured_timeout,
        )

    def _runner_mark_cancelled(
        self: _RunnerAgent,
        conversation_id: str,
        run_id: str,
    ) -> None:
        """Handle CancelledError for a SubAgent runner."""
        self._session_runner.runner_mark_cancelled(
            conversation_id=conversation_id,
            run_id=run_id,
        )

    def _runner_mark_error(
        self: _RunnerAgent,
        conversation_id: str,
        run_id: str,
        exc: Exception,
        started_at: float,
    ) -> None:
        """Handle generic Exception for a SubAgent runner."""
        self._session_runner.runner_mark_error(
            conversation_id=conversation_id,
            run_id=run_id,
            exc=exc,
            started_at=started_at,
        )

    async def _runner_finalize(  # noqa: PLR0913
        self: _RunnerAgent,
        *,
        conversation_id: str,
        run_id: str,
        project_id: str,
        tenant_id: str,
        subagent: SubAgent,
        cancelled_by_control: bool,
        summary: str,
        tokens_used: int | None,
        execution_time_ms: int | None,
        normalized_spawn_mode: str,
        thread_requested: bool,
        normalized_cleanup: str,
        resolved_model_override: str | None,
        resolved_thinking_override: str | None,
    ) -> None:
        """Finalize a SubAgent runner."""
        await self._session_runner.runner_finalize(
            conversation_id=conversation_id,
            run_id=run_id,
            project_id=project_id,
            tenant_id=tenant_id,
            subagent=subagent,
            cancelled_by_control=cancelled_by_control,
            summary=summary,
            tokens_used=tokens_used,
            execution_time_ms=execution_time_ms,
            normalized_spawn_mode=normalized_spawn_mode,
            thread_requested=thread_requested,
            normalized_cleanup=normalized_cleanup,
            resolved_model_override=resolved_model_override,
            resolved_thinking_override=resolved_thinking_override,
        )

    async def _launch_emit_lifecycle_hooks(
        self: _RunnerAgent,
        *,
        conversation_id: str,
        run_id: str,
        project_id: str,
        tenant_id: str,
        subagent: SubAgent,
        normalized_spawn_mode: str,
        thread_requested: bool,
        normalized_cleanup: str,
        requested_model_override: str | None,
        requested_thinking_override: str | None,
    ) -> None:
        """Emit spawning + spawned lifecycle hooks."""
        await self._session_runner.launch_emit_lifecycle_hooks(
            conversation_id=conversation_id,
            run_id=run_id,
            project_id=project_id,
            tenant_id=tenant_id,
            subagent=subagent,
            normalized_spawn_mode=normalized_spawn_mode,
            thread_requested=thread_requested,
            normalized_cleanup=normalized_cleanup,
            requested_model_override=requested_model_override,
            requested_thinking_override=requested_thinking_override,
        )

    @staticmethod
    def _normalize_launch_params(
        spawn_mode: str,
        cleanup: str,
        model_override: str | None,
        thinking_override: str | None,
    ) -> tuple[str, str, str | None, str | None]:
        """Normalize input parameters for subagent session launch."""
        return SubAgentSessionRunner.normalize_launch_params(
            spawn_mode,
            cleanup,
            model_override,
            thinking_override,
        )

    async def _runner_consume_and_extract(
        self: _RunnerAgent,
        *,
        subagent: SubAgent,
        user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        abort_signal: asyncio.Event | None,
        model_override: str | None,
        thinking_override: str | None,
    ) -> tuple[str, int | None, int | None, bool, str | None]:
        """Consume subagent events and extract completion results."""
        result = await self._session_runner.runner_consume_and_extract(
            subagent=subagent,
            user_message=user_message,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            abort_signal=abort_signal,
            model_override=model_override,
            thinking_override=thinking_override,
        )
        return cast(tuple[str, int | None, int | None, bool, str | None], result)

    async def _launch_subagent_session(  # noqa: PLR0913
        self: _RunnerAgent,
        run_id: str,
        subagent: SubAgent,
        user_message: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        abort_signal: asyncio.Event | None = None,
        model_override: str | None = None,
        thinking_override: str | None = None,
        spawn_mode: str = "run",
        thread_requested: bool = False,
        cleanup: str = "keep",
        run_metadata: dict[str, str] | None = None,
    ) -> None:
        """Launch a detached SubAgent session tied to a run_id."""
        await self._session_runner.launch_subagent_session(
            run_id=run_id,
            subagent=subagent,
            user_message=user_message,
            conversation_id=conversation_id,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            abort_signal=abort_signal,
            model_override=model_override,
            thinking_override=thinking_override,
            spawn_mode=spawn_mode,
            thread_requested=thread_requested,
            cleanup=cleanup,
            run_metadata=run_metadata,
        )

    @staticmethod
    def _resolve_subagent_completion_outcome(
        status: str,
    ) -> tuple[str, str]:
        """Map terminal run status to announce outcome labels."""
        return SubAgentSessionRunner.resolve_subagent_completion_outcome(
            status,
        )

    def _append_capped_announce_event(
        self: _RunnerAgent,
        events: list[dict[str, Any]],
        dropped_count: int,
        event: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int]:
        """Append announce event while enforcing bounded history size."""
        return cast(tuple[list[dict[str, Any]], int], self._session_runner.append_capped_announce_event(
            events,
            dropped_count,
            event,
        ))

    @classmethod
    def _build_subagent_completion_payload(
        cls,
        *,
        run: Any,
        fallback_summary: str,
        fallback_tokens_used: int | None,
        fallback_execution_time_ms: int | None,
        spawn_mode: str,
        thread_requested: bool,
        cleanup: str,
        model_override: str | None,
        thinking_override: str | None,
    ) -> dict[str, Any]:
        """Build normalized completion announce payload."""
        return SubAgentSessionRunner.build_subagent_completion_payload(
            run=run,
            fallback_summary=fallback_summary,
            fallback_tokens_used=fallback_tokens_used,
            fallback_execution_time_ms=fallback_execution_time_ms,
            spawn_mode=spawn_mode,
            thread_requested=thread_requested,
            cleanup=cleanup,
            model_override=model_override,
            thinking_override=thinking_override,
        )

    async def _persist_subagent_completion_announce(
        self: _RunnerAgent,
        *,
        conversation_id: str,
        run_id: str,
        fallback_summary: str,
        fallback_tokens_used: int | None,
        fallback_execution_time_ms: int | None,
        spawn_mode: str,
        thread_requested: bool,
        cleanup: str,
        model_override: str | None,
        thinking_override: str | None,
        max_retries: int,
    ) -> None:
        """Persist terminal announce payload with retry/backoff."""
        await self._session_runner.persist_subagent_completion_announce(
            conversation_id=conversation_id,
            run_id=run_id,
            fallback_summary=fallback_summary,
            fallback_tokens_used=fallback_tokens_used,
            fallback_execution_time_ms=fallback_execution_time_ms,
            spawn_mode=spawn_mode,
            thread_requested=thread_requested,
            cleanup=cleanup,
            model_override=model_override,
            thinking_override=thinking_override,
            max_retries=max_retries,
        )

    async def _cancel_subagent_session(self: _RunnerAgent, run_id: str) -> bool:
        """Cancel a detached SubAgent session by run_id."""
        cancelled = await self._session_runner.cancel_subagent_session(run_id)
        return cast(bool, cancelled)

    @staticmethod
    def _topological_sort_subtasks(
        subtasks: list[Any],
    ) -> list[Any]:
        """Sort subtasks by dependency order."""
        return SubAgentSessionRunner.topological_sort_subtasks(subtasks)
