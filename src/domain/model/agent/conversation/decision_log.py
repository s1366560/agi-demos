"""Decision log value object (Track B P2-3 phase-2).

Every judgmental tool-call — the 7 multi-agent action tools, plus the
supervisor ``verdict`` — must leave an audit record on the decision log.
This is the **forensic mechanism** backing the Agent First top-level
rule: subjective decisions happen in agents, and the audit trail proves
no hardcoded heuristic crept back in.

The value object is intentionally flat: a single row per decision,
human-readable, queryable by agent / tool / conversation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

__all__ = ["DecisionLogEntry"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class DecisionLogEntry:
    """One audit row for a judgmental tool-call.

    Attributes:
        id: Primary key (server-generated if empty).
        conversation_id: Scope.
        agent_id: The agent that made the call.
        tool_name: Canonical tool name (``assign_task``, ``verdict``, ...).
        input_payload: Tool inputs, JSON-serializable.
        output_summary: Short prose describing the outcome.
        rationale: Verbatim rationale from the agent (never
            summarized or paraphrased).
        latency_ms: Tool execution latency in milliseconds (``-1`` if
            unknown).
        created_at: UTC timestamp.
        metadata: Optional structured extras (trigger, counters, etc.).
    """

    conversation_id: str
    agent_id: str
    tool_name: str
    input_payload: dict[str, Any]
    output_summary: str = ""
    rationale: str = ""
    latency_ms: int = -1
    id: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)
