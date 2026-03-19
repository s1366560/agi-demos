"""Context segment value object for assembled context."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.domain.shared_kernel import ValueObject


@dataclass(frozen=True)
class ContextSegment(ValueObject):
    """An injected context segment from memory, knowledge graph, or other sources.

    Attributes:
        source: origin identifier (e.g. "memory", "knowledge_graph", "subagent_result").
        content: the textual content to inject.
        token_count: estimated token count for budget tracking.
        metadata: arbitrary metadata about the segment origin.
    """

    source: str
    content: str
    token_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("ContextSegment.source must not be empty")

    @property
    def is_empty(self) -> bool:
        return len(self.content) == 0
