"""Slash command parser.

Detects, extracts, and validates slash commands from raw user input.
Uses shlex for robust tokenization (handles quoted strings).
"""

import logging
import re
import shlex
from typing import Any

from src.infrastructure.agent.commands.types import (
    CommandArgSpec,
    CommandArgType,
    CommandDefinition,
)

logger = logging.getLogger(__name__)


class CommandParseError(Exception):
    """Raised when command parsing fails.

    Attributes:
        usage_hint: Optional usage string to show the user.
    """

    def __init__(self, message: str, usage_hint: str | None = None) -> None:
        super().__init__(message)
        self.usage_hint = usage_hint


class SlashCommandParser:
    """Parses slash command text into structured invocations."""

    COMMAND_PATTERN: re.Pattern[str] = re.compile(r"^/(\w[\w-]*)(?:\s+(.*))?$", re.DOTALL)

    @staticmethod
    def is_slash_command(text: str) -> bool:
        """Check whether text starts with a valid slash command pattern.

        Args:
            text: Raw user input.

        Returns:
            True if the text matches the slash command format.
        """
        stripped = text.strip()
        return bool(SlashCommandParser.COMMAND_PATTERN.match(stripped))

    @staticmethod
    def extract_command_parts(text: str) -> tuple[str, str] | None:
        """Extract the command name and raw argument string.

        Args:
            text: Raw user input.

        Returns:
            A (command_name, raw_args) tuple, or None if not a command.
        """
        stripped = text.strip()
        match = SlashCommandParser.COMMAND_PATTERN.match(stripped)
        if match is None:
            return None
        name = match.group(1).lower()
        raw_args = (match.group(2) or "").strip()
        return name, raw_args

    @staticmethod
    def parse_args(
        raw_args: str,
        specs: list[CommandArgSpec],
    ) -> dict[str, Any]:
        """Parse a raw argument string against a list of argument specs.

        Tokenizes with shlex, then maps positional tokens to specs in order.
        Validates types, choices, and required constraints.

        Args:
            raw_args: The raw argument string after the command name.
            specs: Ordered list of argument specifications.

        Returns:
            A dict mapping argument names to parsed values.

        Raises:
            CommandParseError: If validation fails.
        """
        result: dict[str, Any] = {}

        if not specs:
            return result

        tokens = _tokenize(raw_args)
        token_idx = 0

        for spec in specs:
            if spec.capture_remaining:
                # Capture everything from current position onwards
                remaining = " ".join(tokens[token_idx:]) if token_idx < len(tokens) else ""
                if remaining:
                    result[spec.name] = _coerce_value(remaining, spec)
                elif spec.required:
                    raise CommandParseError(
                        f"Missing required argument: {spec.name}",
                        usage_hint=f"<{spec.name}>",
                    )
                break

            if token_idx < len(tokens):
                result[spec.name] = _coerce_value(tokens[token_idx], spec)
                token_idx += 1
            elif spec.required:
                raise CommandParseError(
                    f"Missing required argument: {spec.name}",
                    usage_hint=f"<{spec.name}>",
                )

        return result

    @staticmethod
    def format_usage(definition: CommandDefinition) -> str:
        """Generate a human-readable usage string for a command.

        Args:
            definition: The command definition.

        Returns:
            Usage string like: /help [command]
        """
        parts = [f"/{definition.name}"]
        for arg in definition.args:
            if arg.required:
                parts.append(f"<{arg.name}>")
            else:
                parts.append(f"[{arg.name}]")
        return " ".join(parts)


def _tokenize(raw: str) -> list[str]:
    """Split raw argument text into tokens using shlex.

    Falls back to simple whitespace splitting if shlex fails
    (e.g. unbalanced quotes).

    Args:
        raw: Raw argument string.

    Returns:
        List of string tokens.
    """
    stripped = raw.strip()
    if not stripped:
        return []
    try:
        return shlex.split(stripped)
    except ValueError:
        logger.debug("shlex.split failed, falling back to str.split")
        return stripped.split()


def _coerce_value(token: str, spec: CommandArgSpec) -> str | float | bool:
    """Coerce a string token to the type required by the spec.

    Args:
        token: The raw string token.
        spec: The argument specification.

    Returns:
        The coerced value.

    Raises:
        CommandParseError: If coercion or validation fails.
    """
    if spec.arg_type == CommandArgType.NUMBER:
        try:
            return float(token)
        except ValueError:
            raise CommandParseError(
                f"Argument '{spec.name}' must be a number, got: {token}"
            ) from None

    if spec.arg_type == CommandArgType.BOOLEAN:
        lower = token.lower()
        if lower in ("true", "1", "yes", "on"):
            return True
        if lower in ("false", "0", "no", "off"):
            return False
        raise CommandParseError(f"Argument '{spec.name}' must be a boolean, got: {token}")

    if spec.arg_type == CommandArgType.CHOICE:
        if spec.choices is not None and token.lower() not in [c.lower() for c in spec.choices]:
            choices_str = ", ".join(spec.choices)
            raise CommandParseError(
                f"Argument '{spec.name}' must be one of [{choices_str}], got: {token}"
            )
        return token.lower()

    # STRING type
    return token
