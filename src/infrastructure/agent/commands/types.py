"""Core type definitions for the slash command system.

Defines command scopes, categories, argument specs, result types,
and the full command definition and invocation structures.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CommandScope(str, Enum):
    """Where a command can be triggered."""

    CHAT = "chat"
    NATIVE = "native"
    BOTH = "both"


class CommandCategory(str, Enum):
    """Grouping category for UI display."""

    SESSION = "session"
    MODEL = "model"
    TOOLS = "tools"
    STATUS = "status"
    SKILL = "skill"
    CONFIG = "config"
    DEBUG = "debug"
    HELP = "help"


class CommandArgType(str, Enum):
    """Supported argument value types."""

    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    CHOICE = "choice"


@dataclass(kw_only=True)
class CommandArgSpec:
    """Definition of a single command argument.

    Attributes:
        name: Argument name used as the dict key in parsed results.
        description: Human-readable description for help text.
        arg_type: Expected value type.
        required: Whether the argument must be provided.
        choices: Valid values when arg_type is CHOICE.
        capture_remaining: If True, captures all remaining tokens as one string.
    """

    name: str
    description: str
    arg_type: CommandArgType = CommandArgType.STRING
    required: bool = False
    choices: list[str] | None = None
    capture_remaining: bool = False


@dataclass(kw_only=True)
class CommandResult:
    """Base class for command execution results."""


@dataclass(kw_only=True)
class ReplyResult(CommandResult):
    """Direct text reply to the user (no LLM invocation needed).

    Attributes:
        text: The reply message content.
        level: Severity indicator for frontend rendering.
    """

    text: str
    level: str = "info"


@dataclass(kw_only=True)
class ToolCallResult(CommandResult):
    """Delegate execution to an existing tool via ToolExecutor.

    Attributes:
        tool_name: Registered tool name to invoke.
        args: Arguments to pass to the tool.
    """

    tool_name: str
    args: dict[str, Any]


@dataclass(kw_only=True)
class SkillTriggerResult(CommandResult):
    """Trigger a registered skill.

    Attributes:
        skill_id: The skill identifier to activate.
        text_override: Optional replacement text for the skill invocation.
    """

    skill_id: str
    text_override: str | None = None


@dataclass(kw_only=True)
class CommandDefinition:
    """Full specification of a slash command.

    Attributes:
        name: Primary command name (e.g. "help").
        description: Human-readable description shown in /help.
        category: UI grouping category.
        scope: Where the command is available.
        aliases: Alternative names that resolve to this command.
        args: Positional argument specifications.
        handler: Async function that executes the command logic.
        hidden: If True, the command is omitted from /help listings.
    """

    name: str
    description: str
    category: CommandCategory
    scope: CommandScope = CommandScope.BOTH
    aliases: list[str] = field(default_factory=list[str])
    args: list[CommandArgSpec] = field(default_factory=list[CommandArgSpec])
    handler: Callable[["CommandInvocation", dict[str, Any]], Awaitable[CommandResult]]
    hidden: bool = False


@dataclass(kw_only=True)
class CommandInvocation:
    """A parsed command ready for execution.

    Attributes:
        definition: The resolved command definition.
        raw_text: The original user input string.
        parsed_args: Argument name-to-value mapping after parsing.
        raw_args_text: The raw substring after the command name.
    """

    definition: CommandDefinition
    raw_text: str
    parsed_args: dict[str, Any]
    raw_args_text: str
