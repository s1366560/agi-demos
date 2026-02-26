"""Built-in slash command definitions.

Registers the default set of commands that ship with every agent session.
Each command handler receives a CommandInvocation and a context dict.
"""

import logging
from typing import Any

from src.infrastructure.agent.commands.registry import CommandRegistry
from src.infrastructure.agent.commands.types import (
    CommandArgSpec,
    CommandArgType,
    CommandCategory,
    CommandDefinition,
    CommandInvocation,
    CommandResult,
    CommandScope,
    ReplyResult,
    ToolCallResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Handler implementations
# ---------------------------------------------------------------------------


async def _handle_help(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Show help for all commands or a specific command."""
    registry: CommandRegistry | None = context.get("_registry")
    if registry is None:
        return ReplyResult(text="Help is not available (no registry in context).")

    target = invocation.parsed_args.get("command")
    target_str = str(target) if target is not None else None
    help_text = registry.get_help_text(target_str)
    return ReplyResult(text=help_text)


async def _handle_commands(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """List all available commands."""
    registry: CommandRegistry | None = context.get("_registry")
    if registry is None:
        return ReplyResult(text="Command listing is not available.")

    commands = registry.list_commands(include_hidden=False)
    if not commands:
        return ReplyResult(text="No commands registered.")

    lines: list[str] = ["Available commands:"]
    for cmd in commands:
        aliases = ""
        if cmd.aliases:
            aliases = f" (aliases: {', '.join('/' + a for a in cmd.aliases)})"
        lines.append(f"  /{cmd.name:16s} {cmd.description}{aliases}")
    return ReplyResult(text="\n".join(lines))


async def _handle_status(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Show current session status."""
    model = context.get("model_name", "unknown")
    project_id = context.get("project_id", "none")
    conversation_id = context.get("conversation_id", "none")

    tools_list: list[str] = context.get("tools", [])
    skills_list: list[str] = context.get("skills", [])

    lines = [
        "Session Status:",
        f"  Model:          {model}",
        f"  Project:        {project_id}",
        f"  Conversation:   {conversation_id}",
        f"  Tools loaded:   {len(tools_list)}",
        f"  Skills loaded:  {len(skills_list)}",
    ]
    return ReplyResult(text="\n".join(lines))


async def _handle_model(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Show or switch the current model."""
    target = invocation.parsed_args.get("name")
    current_model = context.get("model_name", "unknown")

    if target is None:
        return ReplyResult(text=f"Current model: {current_model}")

    return ReplyResult(
        text=(
            f"Model switch requested: {current_model} -> {target}. "
            "Model switching will be applied on the next turn."
        ),
    )


async def _handle_compact(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Trigger context compaction."""
    return ToolCallResult(tool_name="compact_context", args={})


async def _handle_new(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Start a new conversation."""
    return ReplyResult(
        text="Starting a new conversation. Previous context will be preserved in history."
    )


async def _handle_stop(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Stop current agent execution."""
    return ReplyResult(text="Stopping current execution.")


async def _handle_think(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Toggle thinking/reasoning mode."""
    mode = invocation.parsed_args.get("mode", "auto")
    return ReplyResult(text=f"Thinking mode set to: {mode}")


async def _handle_debug(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Toggle debug mode."""
    toggle = invocation.parsed_args.get("toggle", "on")
    return ReplyResult(text=f"Debug mode: {toggle}")


async def _handle_clear(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Clear conversation display."""
    return ReplyResult(text="Conversation display cleared.")


async def _handle_tools(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """List available tools."""
    tools_list: list[str] = context.get("tools", [])
    if not tools_list:
        return ReplyResult(text="No tools available.")

    lines = [f"Available tools ({len(tools_list)}):"]
    for tool_name in sorted(tools_list):
        lines.append(f"  - {tool_name}")
    return ReplyResult(text="\n".join(lines))


async def _handle_skills(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """List available skills."""
    skills_list: list[str] = context.get("skills", [])
    if not skills_list:
        return ReplyResult(text="No skills available.")

    lines = [f"Available skills ({len(skills_list)}):"]
    for skill_name in sorted(skills_list):
        lines.append(f"  - {skill_name}")
    return ReplyResult(text="\n".join(lines))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_builtin_commands(registry: CommandRegistry) -> None:
    """Register all built-in commands.

    Args:
        registry: The command registry to populate.
    """
    registry.register(
        CommandDefinition(
            name="help",
            description="Show help for all commands or a specific command",
            category=CommandCategory.HELP,
            scope=CommandScope.BOTH,
            args=[
                CommandArgSpec(
                    name="command",
                    description="Command name to get help for",
                    arg_type=CommandArgType.STRING,
                    required=False,
                ),
            ],
            handler=_handle_help,
        )
    )

    registry.register(
        CommandDefinition(
            name="commands",
            description="List all available commands",
            category=CommandCategory.HELP,
            scope=CommandScope.BOTH,
            aliases=["cmds"],
            handler=_handle_commands,
        )
    )

    registry.register(
        CommandDefinition(
            name="status",
            description="Show current session status",
            category=CommandCategory.STATUS,
            scope=CommandScope.BOTH,
            handler=_handle_status,
        )
    )

    registry.register(
        CommandDefinition(
            name="model",
            description="Show or switch current model",
            category=CommandCategory.MODEL,
            scope=CommandScope.BOTH,
            args=[
                CommandArgSpec(
                    name="name",
                    description="Model name to switch to",
                    arg_type=CommandArgType.STRING,
                    required=False,
                ),
            ],
            handler=_handle_model,
        )
    )

    registry.register(
        CommandDefinition(
            name="compact",
            description="Trigger context compaction",
            category=CommandCategory.SESSION,
            scope=CommandScope.CHAT,
            handler=_handle_compact,
        )
    )

    registry.register(
        CommandDefinition(
            name="new",
            description="Start a new conversation",
            category=CommandCategory.SESSION,
            scope=CommandScope.CHAT,
            handler=_handle_new,
        )
    )

    registry.register(
        CommandDefinition(
            name="stop",
            description="Stop current agent execution",
            category=CommandCategory.SESSION,
            scope=CommandScope.CHAT,
            handler=_handle_stop,
        )
    )

    registry.register(
        CommandDefinition(
            name="think",
            description="Toggle thinking/reasoning mode",
            category=CommandCategory.CONFIG,
            scope=CommandScope.BOTH,
            args=[
                CommandArgSpec(
                    name="mode",
                    description="Thinking mode",
                    arg_type=CommandArgType.CHOICE,
                    required=False,
                    choices=["on", "off", "auto"],
                ),
            ],
            handler=_handle_think,
        )
    )

    registry.register(
        CommandDefinition(
            name="debug",
            description="Toggle debug mode",
            category=CommandCategory.DEBUG,
            scope=CommandScope.BOTH,
            args=[
                CommandArgSpec(
                    name="toggle",
                    description="Debug toggle",
                    arg_type=CommandArgType.CHOICE,
                    required=False,
                    choices=["on", "off"],
                ),
            ],
            handler=_handle_debug,
        )
    )

    registry.register(
        CommandDefinition(
            name="clear",
            description="Clear conversation display",
            category=CommandCategory.SESSION,
            scope=CommandScope.CHAT,
            handler=_handle_clear,
        )
    )

    registry.register(
        CommandDefinition(
            name="tools",
            description="List available tools",
            category=CommandCategory.TOOLS,
            scope=CommandScope.BOTH,
            handler=_handle_tools,
        )
    )

    registry.register(
        CommandDefinition(
            name="skills",
            description="List available skills",
            category=CommandCategory.SKILL,
            scope=CommandScope.BOTH,
            handler=_handle_skills,
        )
    )
