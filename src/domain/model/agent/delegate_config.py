"""Delegate configuration value objects for agent delegation control.

Defines the capability tier, depth limits, tool allow-lists, and budget
constraints that govern how an agent may delegate work to sub-agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.domain.shared_kernel import ValueObject


class DelegateCapabilityTier(str, Enum):
    """Capability tier controlling what a delegate may do."""

    FULL = "full"
    READ_WRITE = "read_write"
    READ_ONLY = "read_only"
    NONE = "none"


@dataclass(frozen=True)
class DelegateConfig(ValueObject):
    """Immutable policy governing agent delegation behaviour.

    Attributes:
        capability_tier: What operations a delegate is allowed to perform.
        max_delegation_depth: Maximum nesting depth (0 = no further delegation).
        allowed_tools: Explicit tool allow-list; ``None`` permits all tools
            within the capability tier.
        budget_limit_tokens: Maximum token budget for the delegation chain;
            ``None`` means no explicit cap.
    """

    capability_tier: DelegateCapabilityTier = DelegateCapabilityTier.READ_ONLY
    max_delegation_depth: int = 1
    allowed_tools: frozenset[str] | None = None
    budget_limit_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.max_delegation_depth < 0:
            raise ValueError(f"max_delegation_depth must be >= 0, got {self.max_delegation_depth}")
        if self.budget_limit_tokens is not None and self.budget_limit_tokens < 1:
            raise ValueError(
                f"budget_limit_tokens must be positive, got {self.budget_limit_tokens}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary."""
        return {
            "capability_tier": self.capability_tier.value,
            "max_delegation_depth": self.max_delegation_depth,
            "allowed_tools": (
                sorted(self.allowed_tools) if self.allowed_tools is not None else None
            ),
            "budget_limit_tokens": self.budget_limit_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DelegateConfig:
        """Deserialize from a plain dictionary."""
        raw_tools = data.get("allowed_tools")
        return cls(
            capability_tier=DelegateCapabilityTier(data.get("capability_tier", "read_only")),
            max_delegation_depth=data.get("max_delegation_depth", 1),
            allowed_tools=(frozenset(raw_tools) if raw_tools is not None else None),
            budget_limit_tokens=data.get("budget_limit_tokens"),
        )
