"""Slash command system for agent chat.

Provides a Command Pattern implementation that intercepts user messages
starting with ``/`` before they reach the ReAct reasoning loop.
"""

from src.infrastructure.agent.commands.parser import (
    CommandParseError,
    SlashCommandParser,
)
from src.infrastructure.agent.commands.registry import CommandRegistry
from src.infrastructure.agent.commands.types import (
    CommandArgSpec,
    CommandCategory,
    CommandDefinition,
    CommandInvocation,
    CommandResult,
    CommandScope,
    ReplyResult,
    SkillTriggerResult,
    ToolCallResult,
)

__all__ = [
    "CommandArgSpec",
    "CommandCategory",
    "CommandDefinition",
    "CommandInvocation",
    "CommandParseError",
    "CommandRegistry",
    "CommandResult",
    "CommandScope",
    "ReplyResult",
    "SkillTriggerResult",
    "SlashCommandParser",
    "ToolCallResult",
]
