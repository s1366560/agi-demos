"""Glue between :class:`LaneExperienceService` and the agent runtime.

The ``SessionProcessor`` already exposes ``_session_instructions``, a list of
strings that get rendered into the ``[Runtime Guidance]`` system message at
the start of every LLM step. We funnel the lane JIT context through that
hook so the integration stays non-invasive and the processor itself stays
unaware of lane semantics.

Per Agent-First: this helper only *transports* deterministic structural
output. Verdicts (sever, allow, escalate) still come from agent tool-calls.
"""

from __future__ import annotations

from typing import Protocol

from src.application.services.lane_experience_service import LaneJitContext


class _SupportsSessionInstructions(Protocol):
    """Structural protocol satisfied by ``SessionProcessor``."""

    _session_instructions: list[str]


def inject_lane_jit_context(
    processor: _SupportsSessionInstructions,
    context: LaneJitContext,
) -> str:
    """Append the rendered JIT context to the processor's runtime guidance.

    Idempotent: identical guidance strings are not duplicated. Returns the
    rendered string so callers can log / surface it on the workbench.
    """
    rendered = context.render()
    if rendered and rendered not in processor._session_instructions:
        processor._session_instructions.append(rendered)
    return rendered


__all__ = ["inject_lane_jit_context"]
