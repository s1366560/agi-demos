"""Skill types for matching and prompt injection.

Contains shared type definitions used across the agent skill system:
- SkillProtocol: interface for Skill objects
- SkillExecutionMode: enum for execution modes
- SkillMatchResult: result of skill matching
- SkillExecutionConfig: configuration dataclass

The SkillOrchestrator class has been removed (Wave 5.1).
Matching logic is now inlined in ReActAgent._match_skill()
and ReActAgent._stream_match_skill().
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

# ============================================================================
# Protocol Definitions
# ============================================================================


class SkillProtocol(Protocol):
    """Protocol for Skill objects."""

    id: str
    name: str
    description: str
    tools: list[str]
    prompt_template: str | None
    status: Any  # SkillStatus

    def is_accessible_by_agent(self, agent_mode: str) -> bool:
        """Check if skill is accessible by agent mode."""
        ...

    def matches_query(self, query: str) -> float:
        """Calculate match score for query."""
        ...

    def record_usage(self, success: bool) -> None:
        """Record skill usage."""
        ...


# ============================================================================
# Data Classes
# ============================================================================


class SkillExecutionMode(str, Enum):
    """Modes for skill execution."""

    NONE = "none"  # No skill matched
    INJECT = "inject"  # Inject skill into LLM prompt


@dataclass
class SkillMatchResult:
    """Result of skill matching."""

    skill: SkillProtocol | None = None
    score: float = 0.0
    mode: SkillExecutionMode = SkillExecutionMode.NONE

    @property
    def matched(self) -> bool:
        """Check if a skill was matched."""
        return self.skill is not None and self.mode != SkillExecutionMode.NONE


@dataclass
class SkillExecutionConfig:
    """Configuration for skill execution."""

    match_threshold: float = 0.9  # Threshold for prompt injection
    fallback_on_error: bool = True  # Fallback to LLM on skill error
    execution_timeout: int = 300  # Timeout in seconds
