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
from typing import Any


@dataclass
class RunContext:
    """Per-invocation mutable state bag.

    Carries run-specific state that must NOT be shared across concurrent
    processor instances.

    Attributes:
        abort_signal: Cancellation signal for this run.
        conversation_id: Conversation scope for this run.
        trace_id: Distributed tracing identifier.
        start_time: Run start timestamp (epoch seconds).
        langfuse_context: Optional observability context for Langfuse tracing.
            Contains conversation_id, user_id, tenant_id, project_id, extra.
    """

    abort_signal: asyncio.Event | None = None
    conversation_id: str | None = None
    trace_id: str | None = None
    start_time: float = field(default_factory=time.time)
    langfuse_context: dict[str, Any] | None = None
