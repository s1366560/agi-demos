"""Glue between :func:`build_trace_run_digest` and the agent runtime.

Mirrors :mod:`src.application.services.lane_experience_runtime`: append a
deterministic guidance block to ``processor._session_instructions``. The
processor stays oblivious to digest semantics.

The expensive part — fetching trace events from Redis / DB — is the caller's
responsibility. This module only owns the injection contract.
"""

from __future__ import annotations

from typing import Protocol

from src.domain.model.trace.trace_run_digest import TraceRunDigest


class _SupportsSessionInstructions(Protocol):
    _session_instructions: list[str]


def inject_trace_digest(
    processor: _SupportsSessionInstructions,
    digest: TraceRunDigest,
) -> str:
    """Append the rendered digest as a runtime guidance block. Idempotent."""
    rendered = digest.render()
    if rendered and rendered not in processor._session_instructions:
        processor._session_instructions.append(rendered)
    return rendered


__all__ = ["inject_trace_digest"]
