"""Glue between :class:`LaneExperienceService` and the agent runtime.

The ``SessionProcessor`` exposes the public ``add_runtime_guidance(text)``
coroutine which appends to ``_session_instructions`` under an asyncio lock
and de-duplicates idempotently. We funnel the lane JIT context through that
hook so the integration stays non-invasive and the processor itself stays
unaware of lane semantics.

Per Agent-First: this helper only *transports* deterministic structural
output. Verdicts (sever, allow, escalate) still come from agent tool-calls.
"""

from __future__ import annotations

from typing import Protocol

from src.application.services.lane_experience_service import LaneJitContext


class _SupportsRuntimeGuidance(Protocol):
    """Structural protocol satisfied by ``SessionProcessor``.

    Any object exposing an async ``add_runtime_guidance(text)`` returning
    a truthy value when the block was newly appended satisfies this.
    """

    async def add_runtime_guidance(self, text: str) -> bool: ...


async def inject_lane_jit_context(
    processor: _SupportsRuntimeGuidance,
    context: LaneJitContext,
) -> str:
    """Append the rendered JIT context to the processor's runtime guidance.

    Idempotent: identical guidance strings are not duplicated. Returns the
    rendered string so callers can log / surface it on the workbench.
    """
    rendered = context.render()
    if rendered:
        await processor.add_runtime_guidance(rendered)
    return rendered


__all__ = ["inject_lane_jit_context"]
