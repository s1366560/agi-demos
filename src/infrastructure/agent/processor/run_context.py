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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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
