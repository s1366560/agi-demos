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
