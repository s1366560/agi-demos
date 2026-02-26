"""Command registry for slash commands.

Central registry that manages command definitions, resolves names
and aliases, and orchestrates parsing into CommandInvocation objects.
"""

import logging

from src.infrastructure.agent.commands.parser import (
    CommandParseError,
    SlashCommandParser,
)
from src.infrastructure.agent.commands.types import (
    CommandCategory,
    CommandDefinition,
    CommandInvocation,
    CommandScope,
)

logger = logging.getLogger(__name__)


class CommandRegistry:
    """Central registry for slash commands.

    Thread-safe for concurrent reads (dict-based, no locking required).
    Registration is expected to happen at startup before concurrent access.
    """

    def __init__(self) -> None:
        super().__init__()
        self._commands: dict[str, CommandDefinition] = {}
        self._aliases: dict[str, str] = {}

    def register(self, definition: CommandDefinition) -> None:
        """Register a command definition.

        Args:
            definition: The command to register.

        Raises:
            ValueError: If the command name or any alias conflicts
                with an existing registration.
        """
        name = definition.name.lower()

        if name in self._commands:
            raise ValueError(f"Command '{name}' is already registered")
        if name in self._aliases:
            raise ValueError(f"Command name '{name}' conflicts with existing alias")

        for alias in definition.aliases:
            alias_lower = alias.lower()
            if alias_lower in self._commands:
                raise ValueError(f"Alias '{alias_lower}' conflicts with existing command")
            if alias_lower in self._aliases:
                raise ValueError(f"Alias '{alias_lower}' is already registered")

        self._commands[name] = definition
        for alias in definition.aliases:
            self._aliases[alias.lower()] = name

        logger.debug("Registered command: /%s", name)

    def resolve(self, name: str) -> CommandDefinition | None:
        """Resolve a command name or alias to its definition.

        Args:
            name: Command name or alias (case-insensitive).

        Returns:
            The matched CommandDefinition, or None if not found.
        """
        lower = name.lower()
        if lower in self._commands:
            return self._commands[lower]
        canonical = self._aliases.get(lower)
        if canonical is not None:
            return self._commands.get(canonical)
        return None

    def parse_and_resolve(self, text: str) -> CommandInvocation | None:
        """Full pipeline: detect slash command, resolve, parse args.

        Args:
            text: Raw user input.

        Returns:
            A CommandInvocation if text is a valid slash command, or None
            if the text is not a slash command at all.

        Raises:
            CommandParseError: If the command is recognized but arguments
                are invalid, or if the command name is unknown.
        """
        parts = SlashCommandParser.extract_command_parts(text)
        if parts is None:
            return None

        cmd_name, raw_args = parts
        definition = self.resolve(cmd_name)

        if definition is None:
            raise CommandParseError(
                f"Unknown command: /{cmd_name}. Type /help to see available commands."
            )

        parsed_args = SlashCommandParser.parse_args(raw_args, definition.args)

        return CommandInvocation(
            definition=definition,
            raw_text=text.strip(),
            parsed_args=parsed_args,
            raw_args_text=raw_args,
        )

    def list_commands(
        self,
        category: CommandCategory | None = None,
        scope: CommandScope | None = None,
        include_hidden: bool = False,
    ) -> list[CommandDefinition]:
        """List registered commands with optional filters.

        Args:
            category: Filter by category.
            scope: Filter by scope (BOTH matches any scope filter).
            include_hidden: Whether to include hidden commands.

        Returns:
            Sorted list of matching command definitions.
        """
        results: list[CommandDefinition] = []

        for definition in self._commands.values():
            if not include_hidden and definition.hidden:
                continue
            if category is not None and definition.category != category:
                continue
            if scope is not None and definition.scope not in (
                scope,
                CommandScope.BOTH,
            ):
                continue
            results.append(definition)

        return sorted(results, key=lambda d: d.name)

    def get_help_text(self, command_name: str | None = None) -> str:
        """Generate formatted help text.

        Args:
            command_name: If provided, show detailed help for one command.
                If None, show a summary of all visible commands.

        Returns:
            Formatted help text string.
        """
        if command_name is not None:
            return self._single_command_help(command_name)
        return self._all_commands_help()

    def _single_command_help(self, name: str) -> str:
        """Generate detailed help for a single command."""
        definition = self.resolve(name)
        if definition is None:
            return f"Unknown command: /{name}. Type /help to see available commands."

        lines: list[str] = [
            f"/{definition.name} - {definition.description}",
            f"Usage: {SlashCommandParser.format_usage(definition)}",
        ]

        if definition.aliases:
            aliases_str = ", ".join(f"/{a}" for a in definition.aliases)
            lines.append(f"Aliases: {aliases_str}")

        if definition.args:
            lines.append("Arguments:")
            for arg in definition.args:
                required_tag = " (required)" if arg.required else ""
                choices_tag = ""
                if arg.choices is not None:
                    choices_tag = f" [{', '.join(arg.choices)}]"
                lines.append(f"  {arg.name}: {arg.description}{required_tag}{choices_tag}")

        return "\n".join(lines)

    def _all_commands_help(self) -> str:
        """Generate a summary of all visible commands grouped by category."""
        commands = self.list_commands(include_hidden=False)
        if not commands:
            return "No commands registered."

        grouped: dict[str, list[CommandDefinition]] = {}
        for cmd in commands:
            key = cmd.category.value.title()
            grouped.setdefault(key, []).append(cmd)

        lines: list[str] = ["Available Commands:"]
        for group_name in sorted(grouped.keys()):
            lines.append(f"\n  {group_name}:")
            for cmd in grouped[group_name]:
                usage = SlashCommandParser.format_usage(cmd)
                lines.append(f"    {usage:24s} {cmd.description}")

        lines.append("\nType /help <command> for detailed help.")
        return "\n".join(lines)
