"""RunContext - Per-invocation mutable state bag for processor execution.

Each processor invocation (main agent run or SubAgent run) gets its own
RunContext carrying per-run isolation state.  This is NOT the processor
config or the factory -- it is the *mutable* counterpart that travels
with a single execution.

Wave 4 introduced RunContext as a data structure.
Wave 6 plumbs it through SessionProcessor.process() for full per-invocation isolation.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass
class RunContext:
    """Per-invocation mutable state bag.

    Carries run-specific state that must NOT be shared across concurrent
    processor instances.

    Attributes:
        abort_signal: Cancellation signal for this run.
        conversation_id: Conversation scope for this run.
        agent_id: Agent identity for multi-agent isolation (Phase 3).
            When set, scopes workspace files and events to a specific agent.
        trace_id: Distributed tracing identifier.
        start_time: Run start timestamp (epoch seconds).
        langfuse_context: Optional observability context for Langfuse tracing.
            Contains conversation_id, user_id, tenant_id, project_id, extra.
        session_factory: Optional injected async sessionmaker for components that
            must open their own short-lived session (HITL handlers, background
            persistence claims) instead of importing the global module-level
            factory. When None, callers must fall back to the global factory
            with a one-shot deprecation log.
    """

    abort_signal: asyncio.Event | None = None
    conversation_id: str | None = None
    agent_id: str | None = None
    trace_id: str | None = None
    start_time: float = field(default_factory=time.time)
    langfuse_context: dict[str, Any] | None = None
    session_factory: async_sessionmaker[AsyncSession] | None = None

    @classmethod
    def current(cls) -> RunContext | None:
        """Return the RunContext active on the current async task, if any.

        Cached tool wrappers (constructed once per tool-set hash, see
        :mod:`src.infrastructure.agent.core.tool_converter`) cannot capture
        the per-invocation RunContext at construction time, so they look it
        up here at execution time. Returns ``None`` when called outside of
        a processor run.
        """
        return _current_run_context.get()


_current_run_context: ContextVar[RunContext | None] = ContextVar("agent_run_context", default=None)


@contextmanager
def bind_run_context(run_ctx: RunContext) -> Iterator[RunContext]:
    """Bind ``run_ctx`` as the active RunContext for the enclosed block.

    Restores the previous binding (if any) on exit. Designed for use in
    :class:`SessionProcessor.process` so cached tool wrappers can read the
    live RunContext via :meth:`RunContext.current`.
    """
    token = _current_run_context.set(run_ctx)
    try:
        yield run_ctx
    finally:
        _current_run_context.reset(token)


def set_current_run_context(run_ctx: RunContext) -> None:
    """Publish ``run_ctx`` on the current asyncio task's context.

    Fire-and-forget counterpart to :func:`bind_run_context`. ContextVars
    set inside an asyncio task are task-local and auto-clean when the
    task ends, so this is the right primitive when the binding should
    live for the rest of the calling coroutine and there is no clean
    enclosing scope to restore on (e.g. inside an async generator that
    spans many ``yield``s).
    """
    _current_run_context.set(run_ctx)
