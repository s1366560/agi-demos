"""Skill loading as a standard tool.

Skills are loaded via the @tool_define decorator, making them first-class
tools in the LLM's tool selection pipeline. This replaces the need for a
separate SkillOrchestrator dispatch path.

Usage::

    # Configure the skill loader at startup:
    configure_skill_loader(my_loader)

    # The tool is then available to the agent as "skill"
    # LLM calls: skill(name="git-master")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Skill loader protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class SkillLoaderProtocol(Protocol):
    """Protocol for loading skill content."""

    async def load(self, name: str) -> SkillData | None:
        """Load a skill by name. Returns None if not found."""
        ...

    async def list_available(self) -> list[SkillSummary]:
        """List all available skills (name + description only)."""
        ...


@dataclass(frozen=True)
class SkillData:
    """Loaded skill content."""

    name: str
    description: str
    content: str
    scope: str = "project"


@dataclass(frozen=True)
class SkillSummary:
    """Summary for skill listing."""

    name: str
    description: str


# ---------------------------------------------------------------------------
# Module-level loader reference
# ---------------------------------------------------------------------------

_skill_loader: SkillLoaderProtocol | None = None


def configure_skill_loader(loader: SkillLoaderProtocol) -> None:
    """Configure the skill loader used by the skill tool.

    Called at agent startup to inject the skill loading implementation.
    """
    global _skill_loader
    _skill_loader = loader


def get_skill_loader() -> SkillLoaderProtocol | None:
    """Get the configured skill loader (for testing)."""
    return _skill_loader


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@tool_define(
    name="skill",
    description=(
        "Load a skill to get specialized instructions for a task. "
        "Skills provide domain-specific knowledge and patterns that "
        "guide your behavior for particular types of work."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Name of the skill to load (e.g., 'git-master', 'python-testing')."
                ),
            },
            "user_message": {
                "type": "string",
                "description": ("Optional context about why this skill is being loaded."),
            },
        },
        "required": ["name"],
    },
    permission="skill",
    category="knowledge",
    tags=frozenset({"skill", "knowledge"}),
)
async def skill_tool(ctx: ToolContext, *, name: str, user_message: str = "") -> ToolResult:
    """Load a skill by name and return its content."""
    if _skill_loader is None:
        return ToolResult(
            output="Skill system is not configured. No skill loader available.",
            is_error=True,
        )

    # Load the skill
    skill = await _skill_loader.load(name)
    if skill is None:
        # List available skills for better error message
        available = await _skill_loader.list_available()
        if available:
            names = ", ".join(s.name for s in available[:20])
            return ToolResult(
                output=f"Skill '{name}' not found. Available skills: {names}",
                is_error=True,
            )
        return ToolResult(
            output=f"Skill '{name}' not found. No skills are currently available.",
            is_error=True,
        )

    # Permission check
    approved = await ctx.ask(
        permission="skill",
        description=f"Load skill: {skill.name} - {skill.description}",
    )
    if not approved:
        return ToolResult(output="Skill loading denied by user.", is_error=True)

    logger.info(
        "Loaded skill '%s' (scope=%s, %d bytes)",
        skill.name,
        skill.scope,
        len(skill.content),
    )

    return ToolResult(
        output=skill.content,
        title=f"Skill: {skill.name}",
        metadata={
            "skill_name": skill.name,
            "scope": skill.scope,
            "user_message": user_message,
        },
    )
