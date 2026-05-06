"""ReflectionVerdict — the structured output of the reflector agent.

The reflector consumes a window of FrictionSignals + existing Playbooks and
returns one ReflectionVerdict per recommended change. This is what the
service layer applies to the playbook repository.

The verdict MUST come from an agent tool-call (Agent-First rule). The
service layer never derives a verdict from heuristics.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.domain.shared_kernel import ValueObject


class ReflectionAction(str, Enum):
    """What to do with the referenced playbook."""

    CREATE = "create"
    REINFORCE = "reinforce"
    DEPRECATE = "deprecate"
    NOOP = "noop"


@dataclass(frozen=True)
class ReflectionVerdict(ValueObject):
    """One recommendation from the reflector agent."""

    action: ReflectionAction
    """Existing playbook id when action is reinforce/deprecate; None for create."""
    playbook_id: str | None
    """Human-readable rationale supplied by the reflector. Logged for audit."""
    rationale: str
    """For CREATE actions: the proposed playbook payload (name, trigger, steps)."""
    proposed_playbook: dict[str, object] | None = None
