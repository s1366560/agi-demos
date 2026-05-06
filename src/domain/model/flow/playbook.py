"""Playbook — a reusable recipe distilled from past friction patterns.

A playbook captures *how the agent should respond next time it sees a similar
situation*. Created/reinforced/deprecated by the reflector agent (NOT by
heuristics — Agent-First rule applies).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from src.domain.shared_kernel import Entity, ValueObject


class PlaybookStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


@dataclass(frozen=True)
class PlaybookStep(ValueObject):
    """Single instruction inside a playbook."""

    order: int
    instruction: str
    rationale: str | None = None


@dataclass(frozen=True)
class TriggerPattern(ValueObject):
    """Describes when a playbook should be considered applicable.

    The pattern is *intentionally* a structured record (not a regex) so the
    matching decision can be delegated to an agent tool-call later — keeping
    semantic judgment out of code.
    """

    """Free-form description, e.g. "code_diff fails lint repeatedly"."""
    description: str
    """Optional friction kinds that commonly precede the pattern."""
    friction_kinds: tuple[str, ...] = ()
    """Optional lane transitions (source -> target) the pattern correlates with."""
    lane_transitions: tuple[tuple[str, str], ...] = ()


@dataclass(kw_only=True)
class Playbook(Entity):
    """A reusable recipe agents can apply when a trigger pattern fires."""

    project_id: str
    name: str
    trigger: TriggerPattern
    steps: tuple[PlaybookStep, ...] = ()
    status: PlaybookStatus = PlaybookStatus.DRAFT
    hit_count: int = 0
    last_used_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
