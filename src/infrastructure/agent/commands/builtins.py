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


async def _handle_agents(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """List all available agents in the current project."""
    agent_registry = context.get("agent_registry")
    project_id = context.get("project_id", "none")

    if agent_registry is None:
        return ReplyResult(text="Agent registry not available in current context.")

    agents = await agent_registry.list_by_project(project_id)
    if not agents:
        return ReplyResult(text="No agents configured for this project.")

    lines = ["Available Agents:", ""]
    for agent in agents:
        status = "enabled" if agent.enabled else "disabled"
        lines.append(f"  - {agent.name} ({agent.agent_type}) [{status}]")
        if agent.description:
            lines.append(f"    {agent.description}")
    return ReplyResult(text="\n".join(lines))


async def _handle_subagents(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """List sub-agents of the current agent."""
    current_agent = context.get("current_agent")
    if current_agent is None:
        return ReplyResult(text="No active agent in current context.")

    sub_agent_ids = getattr(current_agent, "sub_agent_ids", None)
    if not sub_agent_ids:
        name = getattr(current_agent, "name", "current agent")
        return ReplyResult(text=f"Agent {name} has no sub-agents.")

    name = getattr(current_agent, "name", "current agent")
    lines = [f"Sub-agents of {name}:", ""]
    for sub_id in sub_agent_ids:
        lines.append(f"  - {sub_id}")
    return ReplyResult(text="\n".join(lines))


async def _handle_focus(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Focus conversation on a specific agent."""
    agent_name = invocation.raw_args_text.strip()
    if not agent_name:
        return ReplyResult(text="Usage: /focus <agent_name> -- Focus on a specific agent.")

    session_metadata: dict[str, Any] = context.get("session_metadata", {})
    session_metadata["focused_agent"] = agent_name
    context["session_metadata"] = session_metadata

    return ReplyResult(
        text=f"Focused on agent {agent_name}. All messages will be routed to this agent.",
    )


async def _handle_unfocus(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Remove agent focus, return to default routing."""
    session_metadata: dict[str, Any] = context.get("session_metadata", {})
    removed = session_metadata.pop("focused_agent", None)
    if removed:
        context["session_metadata"] = session_metadata
        return ReplyResult(
            text=f"Removed focus from {removed}. Default routing restored.",
        )
    return ReplyResult(text="No agent focus is currently set.")


async def _handle_send(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Send a message to a specific agent."""
    raw = invocation.raw_args_text.strip()
    if not raw:
        return ReplyResult(
            text="Usage: /send <agent_name> <message> -- Send message to an agent.",
        )
    parts = raw.split(maxsplit=1)
    if len(parts) < 2:
        return ReplyResult(text="Usage: /send <agent_name> <message>")

    agent_name, message = parts
    return ReplyResult(text=f"Message sent to {agent_name}: {message}")


async def _handle_reset(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Reset the current conversation session."""
    return ReplyResult(text="Session has been reset. Starting fresh.")


async def _handle_context(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Show current agent context and session info."""
    lines = ["Current Context:", ""]
    project_id = context.get("project_id")
    if project_id:
        lines.append(f"  Project:        {project_id}")

    current_agent = context.get("current_agent")
    if current_agent is not None:
        name = getattr(current_agent, "name", "unknown")
        lines.append(f"  Agent:          {name}")

    conversation_id = context.get("conversation_id")
    if conversation_id:
        lines.append(f"  Conversation:   {conversation_id}")

    session_metadata: dict[str, Any] = context.get("session_metadata", {})
    focused = session_metadata.get("focused_agent")
    if focused:
        lines.append(f"  Focused Agent:  {focused}")

    if len(lines) == 2:
        return ReplyResult(text="No context information available.")
    return ReplyResult(text="\n".join(lines))


async def _handle_goal(  # noqa: PLR0911
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Create a workspace-backed standing goal."""
    from src.infrastructure.agent.commands.goal_mode import (
        create_workspace_goal,
        list_workspace_goals,
        resolve_preferred_language,
        resolve_workspace_id,
    )

    goal_text = invocation.raw_args_text.strip()
    if goal_text.lower() in {"pause", "resume", "clear", "stop", "done"}:
        return ReplyResult(
            text=(
                "This /goal mode is backed by workspace root tasks. "
                "Use the workspace Goals panel for pause, completion, or cleanup controls."
            ),
            level="warning",
        )

    workspace_id = resolve_workspace_id(context)
    if not workspace_id:
        return ReplyResult(
            text="/goal requires a workspace-linked conversation.",
            level="warning",
        )

    actor_user_id = context.get("user_id")
    if not isinstance(actor_user_id, str) or not actor_user_id.strip():
        return ReplyResult(text="/goal requires an authenticated user.", level="error")

    if not goal_text or goal_text.lower() == "status":
        try:
            goals = await list_workspace_goals(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
            )
        except PermissionError:
            return ReplyResult(text="Access denied for this workspace.", level="error")
        if not goals:
            return ReplyResult(
                text=(
                    "No workspace root goals are active.\n"
                    "Usage: /goal <objective>"
                )
            )
        lines = ["Workspace root goals:"]
        lines.extend(f"- {goal.root_task_id} [{goal.status}] {goal.title}" for goal in goals)
        return ReplyResult(text="\n".join(lines))

    try:
        conversation_id = context.get("conversation_id")
        outcome = await create_workspace_goal(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            goal_text=goal_text,
            conversation_id=conversation_id if isinstance(conversation_id, str) else None,
            preferred_language=resolve_preferred_language(context),
        )
    except PermissionError:
        return ReplyResult(text="Access denied for this workspace.", level="error")
    except ValueError as exc:
        return ReplyResult(text=str(exc), level="error")

    tick_line = "Autonomy tick scheduled." if outcome.scheduled else "Autonomy tick queued."
    return ReplyResult(
        text=(
            f"Goal created: {outcome.root_task_id}\n"
            f"Workspace: {outcome.workspace_id}\n"
            f"{tick_line}"
        )
    )


async def _handle_spawn(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Spawn a task on a sub-agent via /spawn <agent> <task>."""
    raw = invocation.raw_args_text.strip()
    if not raw:
        return ReplyResult(
            text="Usage: /spawn <subagent_name> <task description>",
            level="warning",
        )

    parts = raw.split(maxsplit=1)
    if len(parts) < 2:
        return ReplyResult(
            text="Usage: /spawn <subagent_name> <task description>",
            level="warning",
        )

    agent_name, task = parts
    return ToolCallResult(
        tool_name="delegate_to_subagent",
        args={"subagent_name": agent_name, "task": task},
    )


async def _handle_kill(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Kill a running sub-agent via /kill <target>."""
    target = invocation.raw_args_text.strip()
    if not target:
        return ReplyResult(
            text="Usage: /kill <run_id | #index | label:tag | all>",
            level="warning",
        )

    return ToolCallResult(
        tool_name="subagents",
        args={"action": "kill", "target": target},
    )


async def _handle_steer(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Steer a running sub-agent via /steer <target> <instruction>."""
    raw = invocation.raw_args_text.strip()
    if not raw:
        return ReplyResult(
            text="Usage: /steer <run_id | #index | label:tag> <instruction>",
            level="warning",
        )

    parts = raw.split(maxsplit=1)
    if len(parts) < 2:
        return ReplyResult(
            text="Usage: /steer <target> <instruction>",
            level="warning",
        )

    target, instruction = parts
    return ToolCallResult(
        tool_name="subagents",
        args={"action": "steer", "target": target, "instruction": instruction},
    )


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

    registry.register(
        CommandDefinition(
            name="agents",
            description="List available agents in this project",
            category=CommandCategory.AGENT,
            scope=CommandScope.BOTH,
            handler=_handle_agents,
        )
    )

    registry.register(
        CommandDefinition(
            name="subagents",
            description="List sub-agents of current agent",
            category=CommandCategory.AGENT,
            scope=CommandScope.BOTH,
            handler=_handle_subagents,
        )
    )

    registry.register(
        CommandDefinition(
            name="focus",
            description="Focus conversation on a specific agent",
            category=CommandCategory.AGENT,
            scope=CommandScope.CHAT,
            handler=_handle_focus,
        )
    )

    registry.register(
        CommandDefinition(
            name="unfocus",
            description="Remove agent focus, return to default routing",
            category=CommandCategory.AGENT,
            scope=CommandScope.CHAT,
            handler=_handle_unfocus,
        )
    )

    registry.register(
        CommandDefinition(
            name="send",
            description="Send message to a specific agent",
            category=CommandCategory.AGENT,
            scope=CommandScope.CHAT,
            handler=_handle_send,
        )
    )

    registry.register(
        CommandDefinition(
            name="reset",
            description="Reset current conversation session",
            category=CommandCategory.AGENT,
            scope=CommandScope.CHAT,
            handler=_handle_reset,
        )
    )

    registry.register(
        CommandDefinition(
            name="context",
            description="Show current agent context and session info",
            category=CommandCategory.AGENT,
            scope=CommandScope.BOTH,
            handler=_handle_context,
        )
    )

    registry.register(
        CommandDefinition(
            name="goal",
            description="Create a workspace-backed standing goal",
            category=CommandCategory.AGENT,
            scope=CommandScope.CHAT,
            args=[
                CommandArgSpec(
                    name="objective",
                    description="Goal objective text",
                    arg_type=CommandArgType.STRING,
                    required=False,
                    capture_remaining=True,
                ),
            ],
            handler=_handle_goal,
        )
    )

    registry.register(
        CommandDefinition(
            name="spawn",
            description="Delegate a task to a sub-agent",
            category=CommandCategory.AGENT,
            scope=CommandScope.CHAT,
            aliases=["delegate"],
            handler=_handle_spawn,
        )
    )

    registry.register(
        CommandDefinition(
            name="kill",
            description="Kill a running sub-agent",
            category=CommandCategory.AGENT,
            scope=CommandScope.CHAT,
            handler=_handle_kill,
        )
    )

    registry.register(
        CommandDefinition(
            name="steer",
            description="Send steering instruction to a running sub-agent",
            category=CommandCategory.AGENT,
            scope=CommandScope.CHAT,
            handler=_handle_steer,
        )
    )
