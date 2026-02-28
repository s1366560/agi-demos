"""Command interceptor for the agent chat pipeline.

Bridges between incoming user messages and the command system,
intercepting slash commands before they reach the ReAct loop.
"""

import logging
from typing import Any

from src.infrastructure.agent.commands.parser import (
    CommandParseError,
    SlashCommandParser,
)
from src.infrastructure.agent.commands.registry import CommandRegistry
from src.infrastructure.agent.commands.types import (
    CommandResult,
    ReplyResult,
    SkillTriggerResult,
)

logger = logging.getLogger(__name__)


class CommandInterceptor:
    """Intercepts slash commands before they reach the ReAct loop.

    Usage::

        interceptor = CommandInterceptor(registry)
        result = await interceptor.try_intercept(message, context)
        if result is not None:
            # Command was handled; send result to user
            ...
        else:
            # Not a command; pass message to ReAct loop
            ...
    """

    def __init__(self, registry: CommandRegistry) -> None:
        super().__init__()
        self._registry = registry

    async def try_intercept(
        self,
        message: str,
        context: dict[str, Any],
    ) -> CommandResult | None:
        """Try to intercept a message as a slash command.

        Args:
            message: Raw user input.
            context: Runtime context dict (conversation_id, project_id,
                model_name, tools, skills, etc.). The registry itself
                is injected under the ``_registry`` key for handlers
                that need it (e.g. /help).

        Returns:
            A CommandResult if the message was a slash command (handled),
            or None if the message is not a slash command (pass through).
        """
        if not SlashCommandParser.is_slash_command(message):
            return None

        enriched_context = {**context, "_registry": self._registry}

        try:
            invocation = self._registry.parse_and_resolve(message)
        except CommandParseError as exc:
            # Check if the unknown command name matches a loaded skill.
            # If so, return a SkillTriggerResult so the processor can route
            # the message to the ReAct loop with forced_skill_name set.
            skill_result = self._try_match_skill_command(message, context)
            if skill_result is not None:
                return skill_result
            logger.debug("Command parse error: %s", exc)
            hint = f"\nUsage: {exc.usage_hint}" if exc.usage_hint else ""
            return ReplyResult(
                text=f"{exc}{hint}",
                level="error",
            )

        if invocation is None:
            return None

        logger.info(
            "Intercepted command: /%s (args=%s)",
            invocation.definition.name,
            invocation.parsed_args,
        )

        try:
            return await invocation.definition.handler(invocation, enriched_context)
        except Exception:
            logger.exception(
                "Command handler error for /%s",
                invocation.definition.name,
            )
            return ReplyResult(
                text=f"Command /{invocation.definition.name} failed unexpectedly.",
                level="error",
            )

    def is_command(self, message: str) -> bool:
        """Quick check if a message looks like a slash command.

        Args:
            message: Raw user input.

        Returns:
            True if the message matches the slash command pattern.
        """
        return SlashCommandParser.is_slash_command(message)

    def _try_match_skill_command(
        self,
        message: str,
        context: dict[str, Any],
    ) -> SkillTriggerResult | None:
        """Check if an unknown slash command matches a loaded skill name.

        When the user types ``/some-skill do something``, the command registry
        raises ``CommandParseError`` because "some-skill" is not a registered
        command.  This method inspects the available skills list from the
        runtime context and, if a case-insensitive match is found, returns a
        ``SkillTriggerResult`` so the processor can route the request to the
        ReAct loop with ``forced_skill_name`` set.

        Args:
            message: The original user input (e.g. ``/code-review fix the bug``).
            context: Runtime context dict containing a ``skills`` list.

        Returns:
            A ``SkillTriggerResult`` if the command name matches a skill,
            otherwise ``None``.
        """
        parts = SlashCommandParser.extract_command_parts(message)
        if parts is None:
            return None

        cmd_name, raw_args = parts
        skills: list[str] = context.get("skills", [])
        if not skills:
            return None

        # Case-insensitive match against loaded skill names
        cmd_lower = cmd_name.lower()
        for skill_name in skills:
            if skill_name.lower() == cmd_lower:
                logger.info(
                    "Unknown command '/%s' matched skill '%s'; "+
                    "routing to skill execution",
                    cmd_name,
                    skill_name,
                )
                return SkillTriggerResult(
                    skill_id=skill_name,
                    text_override=raw_args if raw_args else None,
                )

        return None
