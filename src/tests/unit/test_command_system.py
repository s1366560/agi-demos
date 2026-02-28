"""Unit tests for the slash command system.

Tests for:
- SlashCommandParser: detection, extraction, arg parsing, usage formatting
- CommandRegistry: registration, resolution, listing, help text
- CommandInterceptor: interception, delegation, error handling
- Built-in commands: registration, handler behavior
"""

from __future__ import annotations

from typing import Any

import pytest

from src.infrastructure.agent.commands.builtins import register_builtin_commands
from src.infrastructure.agent.commands.interceptor import CommandInterceptor
from src.infrastructure.agent.commands.parser import CommandParseError, SlashCommandParser
from src.infrastructure.agent.commands.registry import CommandRegistry
from src.infrastructure.agent.commands.types import (
    CommandArgSpec,
    CommandArgType,
    CommandCategory,
    CommandDefinition,
    CommandInvocation,
    CommandResult,
    ReplyResult,
    SkillTriggerResult,
    ToolCallResult,
)

# ============================================================================
# Fixtures
# ============================================================================


async def _noop_handler(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """No-op handler for testing."""
    return ReplyResult(text="ok")


async def _echo_handler(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Echo handler that returns raw_args_text."""
    return ReplyResult(text=invocation.raw_args_text)


async def _raising_handler(
    invocation: CommandInvocation,
    context: dict[str, Any],
) -> CommandResult:
    """Handler that always raises."""
    raise RuntimeError("boom")


@pytest.fixture()
def parser() -> SlashCommandParser:
    """Create a SlashCommandParser instance."""
    return SlashCommandParser()


@pytest.fixture()
def registry() -> CommandRegistry:
    """Create an empty CommandRegistry."""
    return CommandRegistry()


@pytest.fixture()
def registry_with_builtins() -> CommandRegistry:
    """Create a CommandRegistry with all built-in commands registered."""
    reg = CommandRegistry()
    register_builtin_commands(reg)
    return reg


@pytest.fixture()
def interceptor(registry_with_builtins: CommandRegistry) -> CommandInterceptor:
    """Create a CommandInterceptor backed by a registry with builtins."""
    return CommandInterceptor(registry_with_builtins)


@pytest.fixture()
def sample_command() -> CommandDefinition:
    """A simple command definition for tests."""
    return CommandDefinition(
        name="ping",
        description="Ping the system",
        category=CommandCategory.STATUS,
        handler=_noop_handler,
    )


@pytest.fixture()
def hidden_command() -> CommandDefinition:
    """A hidden command definition for tests."""
    return CommandDefinition(
        name="secret",
        description="Secret command",
        category=CommandCategory.DEBUG,
        handler=_noop_handler,
        hidden=True,
    )


@pytest.fixture()
def aliased_command() -> CommandDefinition:
    """A command with aliases."""
    return CommandDefinition(
        name="greet",
        description="Say hello",
        category=CommandCategory.SESSION,
        aliases=["hi", "hello"],
        handler=_echo_handler,
    )


@pytest.fixture()
def command_with_required_arg() -> CommandDefinition:
    """A command with a required argument."""
    return CommandDefinition(
        name="deploy",
        description="Deploy to an environment",
        category=CommandCategory.TOOLS,
        args=[
            CommandArgSpec(
                name="env",
                description="Target environment",
                arg_type=CommandArgType.CHOICE,
                required=True,
                choices=["dev", "staging", "prod"],
            ),
        ],
        handler=_noop_handler,
    )


# ============================================================================
# SlashCommandParser Tests
# ============================================================================


@pytest.mark.unit
class TestSlashCommandParserIsSlashCommand:
    """Tests for SlashCommandParser.is_slash_command()."""

    def test_valid_command_help(self) -> None:
        """'/help' is a valid slash command."""
        assert SlashCommandParser.is_slash_command("/help") is True

    def test_valid_command_with_args(self) -> None:
        """'/model gpt-4' is a valid slash command."""
        assert SlashCommandParser.is_slash_command("/model gpt-4") is True

    def test_valid_command_status(self) -> None:
        """'/status' is a valid slash command."""
        assert SlashCommandParser.is_slash_command("/status") is True

    def test_valid_command_with_leading_spaces(self) -> None:
        """Leading whitespace should be stripped before matching."""
        assert SlashCommandParser.is_slash_command("  /help") is True

    def test_not_command_plain_text(self) -> None:
        """Plain text is not a command."""
        assert SlashCommandParser.is_slash_command("hello") is False

    def test_not_command_slash_in_middle(self) -> None:
        """A slash not at the start is not a command."""
        assert SlashCommandParser.is_slash_command("not a /command") is False

    def test_not_command_empty_string(self) -> None:
        """Empty string is not a command."""
        assert SlashCommandParser.is_slash_command("") is False

    def test_not_command_whitespace_only(self) -> None:
        """Whitespace-only string is not a command."""
        assert SlashCommandParser.is_slash_command("   ") is False

    def test_not_command_slash_only(self) -> None:
        """A bare '/' without a name is not a command."""
        assert SlashCommandParser.is_slash_command("/") is False

    def test_valid_command_with_hyphen(self) -> None:
        """Command names with hyphens are valid."""
        assert SlashCommandParser.is_slash_command("/my-cmd") is True


@pytest.mark.unit
class TestSlashCommandParserExtractAndParse:
    """Tests for extract_command_parts() and parse_args()."""

    def test_extract_command_name(self) -> None:
        """extract_command_parts returns correct name."""
        parts = SlashCommandParser.extract_command_parts("/help")
        assert parts is not None
        name, raw_args = parts
        assert name == "help"
        assert raw_args == ""

    def test_extract_command_args_text(self) -> None:
        """extract_command_parts returns remaining text as raw_args."""
        parts = SlashCommandParser.extract_command_parts("/model gpt-4o")
        assert parts is not None
        name, raw_args = parts
        assert name == "model"
        assert raw_args == "gpt-4o"

    def test_extract_handles_leading_whitespace(self) -> None:
        """Leading spaces are stripped before extraction."""
        parts = SlashCommandParser.extract_command_parts("   /status  ")
        assert parts is not None
        name, _ = parts
        assert name == "status"

    def test_extract_returns_none_for_non_command(self) -> None:
        """Non-command text returns None."""
        assert SlashCommandParser.extract_command_parts("hello world") is None

    def test_extract_lowercases_name(self) -> None:
        """Command name should be lowercased."""
        parts = SlashCommandParser.extract_command_parts("/HELP")
        assert parts is not None
        assert parts[0] == "help"

    def test_parse_args_no_specs(self) -> None:
        """parse_args with empty specs returns empty dict."""
        result = SlashCommandParser.parse_args("anything", [])
        assert result == {}

    def test_parse_args_string_arg(self) -> None:
        """parse_args handles a simple string arg."""
        specs = [
            CommandArgSpec(name="target", description="target name"),
        ]
        result = SlashCommandParser.parse_args("myvalue", specs)
        assert result == {"target": "myvalue"}

    def test_parse_args_number_arg(self) -> None:
        """parse_args coerces number args."""
        specs = [
            CommandArgSpec(
                name="count",
                description="count",
                arg_type=CommandArgType.NUMBER,
            ),
        ]
        result = SlashCommandParser.parse_args("42", specs)
        assert result == {"count": 42.0}

    def test_parse_args_boolean_arg_true(self) -> None:
        """parse_args coerces boolean true variants."""
        specs = [
            CommandArgSpec(
                name="flag",
                description="flag",
                arg_type=CommandArgType.BOOLEAN,
            ),
        ]
        for val in ("true", "1", "yes", "on"):
            result = SlashCommandParser.parse_args(val, specs)
            assert result["flag"] is True

    def test_parse_args_boolean_arg_false(self) -> None:
        """parse_args coerces boolean false variants."""
        specs = [
            CommandArgSpec(
                name="flag",
                description="flag",
                arg_type=CommandArgType.BOOLEAN,
            ),
        ]
        for val in ("false", "0", "no", "off"):
            result = SlashCommandParser.parse_args(val, specs)
            assert result["flag"] is False

    def test_parse_args_boolean_arg_invalid(self) -> None:
        """parse_args raises on invalid boolean."""
        specs = [
            CommandArgSpec(
                name="flag",
                description="flag",
                arg_type=CommandArgType.BOOLEAN,
                required=True,
            ),
        ]
        with pytest.raises(CommandParseError, match="must be a boolean"):
            SlashCommandParser.parse_args("maybe", specs)

    def test_parse_args_choice_valid(self) -> None:
        """parse_args accepts valid choice."""
        specs = [
            CommandArgSpec(
                name="env",
                description="env",
                arg_type=CommandArgType.CHOICE,
                choices=["dev", "prod"],
            ),
        ]
        result = SlashCommandParser.parse_args("dev", specs)
        assert result == {"env": "dev"}

    def test_parse_args_choice_invalid(self) -> None:
        """parse_args raises on invalid choice."""
        specs = [
            CommandArgSpec(
                name="env",
                description="env",
                arg_type=CommandArgType.CHOICE,
                required=True,
                choices=["dev", "prod"],
            ),
        ]
        with pytest.raises(CommandParseError, match="must be one of"):
            SlashCommandParser.parse_args("qa", specs)

    def test_parse_args_required_missing(self) -> None:
        """parse_args raises when required arg is missing."""
        specs = [
            CommandArgSpec(
                name="target",
                description="target",
                required=True,
            ),
        ]
        with pytest.raises(CommandParseError, match="Missing required argument"):
            SlashCommandParser.parse_args("", specs)

    def test_parse_args_number_invalid(self) -> None:
        """parse_args raises on non-numeric input for NUMBER type."""
        specs = [
            CommandArgSpec(
                name="count",
                description="count",
                arg_type=CommandArgType.NUMBER,
                required=True,
            ),
        ]
        with pytest.raises(CommandParseError, match="must be a number"):
            SlashCommandParser.parse_args("abc", specs)

    def test_format_usage_no_args(self) -> None:
        """format_usage for command without args."""
        defn = CommandDefinition(
            name="ping",
            description="Ping",
            category=CommandCategory.STATUS,
            handler=_noop_handler,
        )
        assert SlashCommandParser.format_usage(defn) == "/ping"

    def test_format_usage_with_required_and_optional(self) -> None:
        """format_usage shows <required> and [optional]."""
        defn = CommandDefinition(
            name="deploy",
            description="Deploy",
            category=CommandCategory.TOOLS,
            args=[
                CommandArgSpec(name="env", description="env", required=True),
                CommandArgSpec(name="tag", description="tag", required=False),
            ],
            handler=_noop_handler,
        )
        assert SlashCommandParser.format_usage(defn) == "/deploy <env> [tag]"


# ============================================================================
# CommandRegistry Tests
# ============================================================================


@pytest.mark.unit
class TestCommandRegistry:
    """Tests for CommandRegistry."""

    def test_register_and_resolve(
        self, registry: CommandRegistry, sample_command: CommandDefinition
    ) -> None:
        """register() stores a command that resolve() can find."""
        registry.register(sample_command)
        resolved = registry.resolve("ping")
        assert resolved is not None
        assert resolved.name == "ping"

    def test_register_with_aliases(
        self, registry: CommandRegistry, aliased_command: CommandDefinition
    ) -> None:
        """Aliases are resolvable after registration."""
        registry.register(aliased_command)
        assert registry.resolve("greet") is not None
        assert registry.resolve("hi") is not None
        assert registry.resolve("hello") is not None

    def test_register_duplicate_name_raises(
        self, registry: CommandRegistry, sample_command: CommandDefinition
    ) -> None:
        """Registering the same name twice raises ValueError."""
        registry.register(sample_command)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(sample_command)

    def test_register_alias_conflict_with_command_raises(self, registry: CommandRegistry) -> None:
        """An alias that matches an existing command name raises ValueError."""
        registry.register(
            CommandDefinition(
                name="foo",
                description="foo cmd",
                category=CommandCategory.STATUS,
                handler=_noop_handler,
            )
        )
        with pytest.raises(ValueError, match="conflicts with existing command"):
            registry.register(
                CommandDefinition(
                    name="bar",
                    description="bar cmd",
                    category=CommandCategory.STATUS,
                    aliases=["foo"],
                    handler=_noop_handler,
                )
            )

    def test_register_duplicate_alias_raises(self, registry: CommandRegistry) -> None:
        """Duplicate aliases across commands raise ValueError."""
        registry.register(
            CommandDefinition(
                name="cmd1",
                description="cmd1",
                category=CommandCategory.STATUS,
                aliases=["shortcut"],
                handler=_noop_handler,
            )
        )
        with pytest.raises(ValueError, match="already registered"):
            registry.register(
                CommandDefinition(
                    name="cmd2",
                    description="cmd2",
                    category=CommandCategory.STATUS,
                    aliases=["shortcut"],
                    handler=_noop_handler,
                )
            )

    def test_resolve_returns_none_for_unknown(self, registry: CommandRegistry) -> None:
        """resolve() returns None for unregistered name."""
        assert registry.resolve("nonexistent") is None

    def test_resolve_is_case_insensitive(
        self, registry: CommandRegistry, sample_command: CommandDefinition
    ) -> None:
        """resolve() matches regardless of case."""
        registry.register(sample_command)
        assert registry.resolve("PING") is not None
        assert registry.resolve("Ping") is not None

    def test_list_commands_returns_non_hidden(
        self,
        registry: CommandRegistry,
        sample_command: CommandDefinition,
        hidden_command: CommandDefinition,
    ) -> None:
        """list_commands() excludes hidden commands by default."""
        registry.register(sample_command)
        registry.register(hidden_command)
        visible = registry.list_commands()
        names = [c.name for c in visible]
        assert "ping" in names
        assert "secret" not in names

    def test_list_commands_include_hidden(
        self,
        registry: CommandRegistry,
        sample_command: CommandDefinition,
        hidden_command: CommandDefinition,
    ) -> None:
        """list_commands(include_hidden=True) includes hidden commands."""
        registry.register(sample_command)
        registry.register(hidden_command)
        all_cmds = registry.list_commands(include_hidden=True)
        names = [c.name for c in all_cmds]
        assert "secret" in names

    def test_list_commands_sorted_by_name(self, registry: CommandRegistry) -> None:
        """list_commands() returns commands sorted alphabetically."""
        for name in ("zebra", "alpha", "middle"):
            registry.register(
                CommandDefinition(
                    name=name,
                    description=name,
                    category=CommandCategory.STATUS,
                    handler=_noop_handler,
                )
            )
        names = [c.name for c in registry.list_commands()]
        assert names == sorted(names)

    def test_parse_and_resolve_by_name(
        self, registry: CommandRegistry, sample_command: CommandDefinition
    ) -> None:
        """parse_and_resolve() resolves a command by primary name."""
        registry.register(sample_command)
        invocation = registry.parse_and_resolve("/ping")
        assert invocation is not None
        assert invocation.definition.name == "ping"

    def test_parse_and_resolve_by_alias(
        self, registry: CommandRegistry, aliased_command: CommandDefinition
    ) -> None:
        """parse_and_resolve() resolves a command by alias."""
        registry.register(aliased_command)
        invocation = registry.parse_and_resolve("/hi")
        assert invocation is not None
        assert invocation.definition.name == "greet"

    def test_parse_and_resolve_returns_none_for_non_command(
        self, registry: CommandRegistry
    ) -> None:
        """parse_and_resolve() returns None for non-slash input."""
        result = registry.parse_and_resolve("just text")
        assert result is None

    def test_parse_and_resolve_raises_for_unknown_command(self, registry: CommandRegistry) -> None:
        """parse_and_resolve() raises CommandParseError for unknown /command."""
        with pytest.raises(CommandParseError, match="Unknown command"):
            registry.parse_and_resolve("/nonexistent")

    def test_parse_and_resolve_validates_required_arg(
        self,
        registry: CommandRegistry,
        command_with_required_arg: CommandDefinition,
    ) -> None:
        """parse_and_resolve() raises when required arg is missing."""
        registry.register(command_with_required_arg)
        with pytest.raises(CommandParseError, match="Missing required argument"):
            registry.parse_and_resolve("/deploy")

    def test_parse_and_resolve_validates_choice(
        self,
        registry: CommandRegistry,
        command_with_required_arg: CommandDefinition,
    ) -> None:
        """parse_and_resolve() raises when choice value is invalid."""
        registry.register(command_with_required_arg)
        with pytest.raises(CommandParseError, match="must be one of"):
            registry.parse_and_resolve("/deploy invalid")

    def test_parse_and_resolve_accepts_valid_choice(
        self,
        registry: CommandRegistry,
        command_with_required_arg: CommandDefinition,
    ) -> None:
        """parse_and_resolve() succeeds with valid choice arg."""
        registry.register(command_with_required_arg)
        invocation = registry.parse_and_resolve("/deploy dev")
        assert invocation is not None
        assert invocation.parsed_args["env"] == "dev"

    def test_get_help_text_all(
        self, registry: CommandRegistry, sample_command: CommandDefinition
    ) -> None:
        """get_help_text() without args returns an overview."""
        registry.register(sample_command)
        text = registry.get_help_text()
        assert "Available Commands:" in text
        assert "/ping" in text

    def test_get_help_text_single(
        self, registry: CommandRegistry, sample_command: CommandDefinition
    ) -> None:
        """get_help_text(name) returns details for one command."""
        registry.register(sample_command)
        text = registry.get_help_text("ping")
        assert "/ping" in text
        assert "Ping the system" in text

    def test_get_help_text_unknown(self, registry: CommandRegistry) -> None:
        """get_help_text(name) for unknown command returns error message."""
        text = registry.get_help_text("nope")
        assert "Unknown command" in text


# ============================================================================
# CommandInterceptor Tests
# ============================================================================


@pytest.mark.unit
class TestCommandInterceptor:
    """Tests for CommandInterceptor."""

    async def test_try_intercept_returns_none_for_non_command(
        self, interceptor: CommandInterceptor
    ) -> None:
        """Non-slash messages pass through (return None)."""
        result = await interceptor.try_intercept("hello world", {})
        assert result is None

    async def test_try_intercept_returns_reply_for_valid_command(
        self, interceptor: CommandInterceptor
    ) -> None:
        """Valid /status command returns a ReplyResult."""
        result = await interceptor.try_intercept("/status", {})
        assert isinstance(result, ReplyResult)
        assert "Session Status:" in result.text

    async def test_try_intercept_unknown_command_returns_error(
        self, interceptor: CommandInterceptor
    ) -> None:
        """Unknown /xyz returns a ReplyResult with error level."""
        result = await interceptor.try_intercept("/xyz", {})
        assert isinstance(result, ReplyResult)
        assert result.level == "error"
        assert "Unknown command" in result.text

    async def test_try_intercept_enriches_context_with_registry(
        self, registry_with_builtins: CommandRegistry
    ) -> None:
        """Context passed to handler should contain '_registry' key."""
        captured_context: dict[str, Any] = {}

        async def _capture_handler(
            invocation: CommandInvocation,
            context: dict[str, Any],
        ) -> CommandResult:
            captured_context.update(context)
            return ReplyResult(text="captured")

        registry_with_builtins.register(
            CommandDefinition(
                name="capture",
                description="Captures context",
                category=CommandCategory.DEBUG,
                handler=_capture_handler,
            )
        )
        interceptor = CommandInterceptor(registry_with_builtins)
        await interceptor.try_intercept("/capture", {"foo": "bar"})
        assert "_registry" in captured_context
        assert captured_context["_registry"] is registry_with_builtins
        assert captured_context["foo"] == "bar"

    async def test_try_intercept_handler_exception_returns_error(
        self, registry: CommandRegistry
    ) -> None:
        """If handler raises, interceptor returns error ReplyResult."""
        registry.register(
            CommandDefinition(
                name="boom",
                description="Exploding command",
                category=CommandCategory.DEBUG,
                handler=_raising_handler,
            )
        )
        interceptor = CommandInterceptor(registry)
        result = await interceptor.try_intercept("/boom", {})
        assert isinstance(result, ReplyResult)
        assert result.level == "error"
        assert "failed unexpectedly" in result.text

    def test_is_command_delegates_correctly(self, interceptor: CommandInterceptor) -> None:
        """is_command() delegates to SlashCommandParser.is_slash_command()."""
        assert interceptor.is_command("/help") is True
        assert interceptor.is_command("hello") is False
        assert interceptor.is_command("") is False


# ============================================================================
# Skill as Command Interception Tests
# ============================================================================


@pytest.mark.unit
class TestSkillAsCommandInterception:
    """Tests for skill-to-command interception feature."""

    async def test_skill_match_returns_skill_trigger_result(
        self, interceptor: CommandInterceptor
    ) -> None:
        """/code-review when skills=['code-review'] returns SkillTriggerResult."""
        result = await interceptor.try_intercept(
            "/code-review fix bug", {"skills": ["code-review"]}
        )
        assert isinstance(result, SkillTriggerResult)
        assert result.skill_id == "code-review"
        assert result.text_override == "fix bug"

    async def test_skill_match_case_insensitive(
        self, interceptor: CommandInterceptor
    ) -> None:
        """/Code-Review matches skill 'code-review' case-insensitively."""
        result = await interceptor.try_intercept(
            "/Code-Review fix bug", {"skills": ["code-review"]}
        )
        assert isinstance(result, SkillTriggerResult)
        assert result.skill_id == "code-review"
        assert result.text_override == "fix bug"

    async def test_unknown_skill_returns_error(
        self, interceptor: CommandInterceptor
    ) -> None:
        """/unknown-thing returns error when not in skills list."""
        result = await interceptor.try_intercept(
            "/unknown-thing", {"skills": ["code-review"]}
        )
        assert isinstance(result, ReplyResult)
        assert result.level == "error"

    async def test_skill_match_without_args(
        self, interceptor: CommandInterceptor
    ) -> None:
        """/code-review with no args returns SkillTriggerResult with None override."""
        result = await interceptor.try_intercept(
            "/code-review", {"skills": ["code-review"]}
        )
        assert isinstance(result, SkillTriggerResult)
        assert result.skill_id == "code-review"
        assert result.text_override is None

    async def test_empty_skills_returns_error(
        self, interceptor: CommandInterceptor
    ) -> None:
        """/code-review returns error when skills list is empty."""
        result = await interceptor.try_intercept(
            "/code-review fix bug", {"skills": []}
        )
        assert isinstance(result, ReplyResult)
        assert result.level == "error"

    async def test_builtin_takes_priority_over_skill(
        self, interceptor: CommandInterceptor
    ) -> None:
        """/help returns builtin ReplyResult, not SkillTriggerResult."""
        result = await interceptor.try_intercept(
            "/help", {"skills": ["help"]}
        )
        # Builtin takes priority, so should be ReplyResult, not SkillTriggerResult
        assert isinstance(result, ReplyResult)
        assert "Available Commands:" in result.text

    async def test_session_processor_rewrite_string_content(self) -> None:
        """SessionProcessor._rewrite_last_user_message rewrites string content."""
        from src.infrastructure.agent.processor.processor import SessionProcessor

        messages = [
            {"role": "user", "content": "old message"},
        ]
        SessionProcessor._rewrite_last_user_message(messages, "new message")
        assert messages[0]["content"] == "new message"

    async def test_session_processor_rewrite_multipart_content(self) -> None:
        """SessionProcessor._rewrite_last_user_message rewrites first text part in multi-part content."""
        from src.infrastructure.agent.processor.processor import SessionProcessor

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "old text"},
                    {"type": "image_url", "image_url": {"url": "http://example.com/img.png"}},
                ],
            },
        ]
        SessionProcessor._rewrite_last_user_message(messages, "new text")
        assert messages[0]["content"][0]["text"] == "new text"
        # Image part should remain unchanged
        assert messages[0]["content"][1]["type"] == "image_url"

# ============================================================================
# Built-in Commands Integration Tests
# ============================================================================


@pytest.mark.unit
class TestBuiltinCommands:
    """Tests for built-in command registration and handler behavior."""

    def test_register_builtin_commands_count(self, registry_with_builtins: CommandRegistry) -> None:
        """register_builtin_commands() registers all 12 commands."""
        all_cmds = registry_with_builtins.list_commands(include_hidden=True)
        assert len(all_cmds) == 12

    def test_all_builtin_names_present(self, registry_with_builtins: CommandRegistry) -> None:
        """All expected built-in command names are registered."""
        expected = {
            "help",
            "commands",
            "status",
            "model",
            "compact",
            "new",
            "stop",
            "think",
            "debug",
            "clear",
            "tools",
            "skills",
        }
        names = {c.name for c in registry_with_builtins.list_commands(include_hidden=True)}
        assert expected == names

    async def test_help_handler_returns_listing(
        self, registry_with_builtins: CommandRegistry
    ) -> None:
        """/help returns a ReplyResult containing 'Available Commands'."""
        invocation = registry_with_builtins.parse_and_resolve("/help")
        assert invocation is not None
        result = await invocation.definition.handler(
            invocation, {"_registry": registry_with_builtins}
        )
        assert isinstance(result, ReplyResult)
        assert "Available Commands:" in result.text

    async def test_help_handler_single_command(
        self, registry_with_builtins: CommandRegistry
    ) -> None:
        """/help status returns details for the status command."""
        invocation = registry_with_builtins.parse_and_resolve("/help status")
        assert invocation is not None
        result = await invocation.definition.handler(
            invocation, {"_registry": registry_with_builtins}
        )
        assert isinstance(result, ReplyResult)
        assert "/status" in result.text

    async def test_commands_alias(self, registry_with_builtins: CommandRegistry) -> None:
        """/cmds is an alias of /commands."""
        invocation = registry_with_builtins.parse_and_resolve("/cmds")
        assert invocation is not None
        assert invocation.definition.name == "commands"

    async def test_commands_handler_lists_all(
        self, registry_with_builtins: CommandRegistry
    ) -> None:
        """/commands handler returns a list of commands."""
        invocation = registry_with_builtins.parse_and_resolve("/commands")
        assert invocation is not None
        result = await invocation.definition.handler(
            invocation, {"_registry": registry_with_builtins}
        )
        assert isinstance(result, ReplyResult)
        assert "Available commands:" in result.text

    async def test_model_no_args_returns_current(
        self, registry_with_builtins: CommandRegistry
    ) -> None:
        """/model with no args shows current model."""
        invocation = registry_with_builtins.parse_and_resolve("/model")
        assert invocation is not None
        result = await invocation.definition.handler(invocation, {"model_name": "gpt-4o"})
        assert isinstance(result, ReplyResult)
        assert "Current model: gpt-4o" in result.text

    async def test_model_with_arg_requests_switch(
        self, registry_with_builtins: CommandRegistry
    ) -> None:
        """/model claude-3 requests a model switch."""
        invocation = registry_with_builtins.parse_and_resolve("/model claude-3")
        assert invocation is not None
        result = await invocation.definition.handler(invocation, {"model_name": "gpt-4o"})
        assert isinstance(result, ReplyResult)
        assert "claude-3" in result.text
        assert "switch" in result.text.lower()

    async def test_status_returns_session_info(
        self, registry_with_builtins: CommandRegistry
    ) -> None:
        """/status returns session status with model, project, conversation."""
        invocation = registry_with_builtins.parse_and_resolve("/status")
        assert invocation is not None
        context = {
            "model_name": "gemini-2.0-flash",
            "project_id": "proj-123",
            "conversation_id": "conv-456",
            "tools": ["tool_a", "tool_b"],
            "skills": ["skill_x"],
        }
        result = await invocation.definition.handler(invocation, context)
        assert isinstance(result, ReplyResult)
        assert "gemini-2.0-flash" in result.text
        assert "proj-123" in result.text
        assert "conv-456" in result.text
        assert "2" in result.text  # 2 tools
        assert "1" in result.text  # 1 skill

    async def test_compact_returns_tool_call(self, registry_with_builtins: CommandRegistry) -> None:
        """/compact returns a ToolCallResult."""
        invocation = registry_with_builtins.parse_and_resolve("/compact")
        assert invocation is not None
        result = await invocation.definition.handler(invocation, {})
        assert isinstance(result, ToolCallResult)
        assert result.tool_name == "compact_context"

    async def test_think_with_choice_arg(self, registry_with_builtins: CommandRegistry) -> None:
        """/think on sets thinking mode."""
        invocation = registry_with_builtins.parse_and_resolve("/think on")
        assert invocation is not None
        result = await invocation.definition.handler(invocation, {})
        assert isinstance(result, ReplyResult)
        assert "on" in result.text

    async def test_think_invalid_choice_raises(
        self, registry_with_builtins: CommandRegistry
    ) -> None:
        """/think invalid raises CommandParseError."""
        with pytest.raises(CommandParseError, match="must be one of"):
            registry_with_builtins.parse_and_resolve("/think invalid")

    async def test_tools_handler_lists_tools(self, registry_with_builtins: CommandRegistry) -> None:
        """/tools handler lists available tools from context."""
        invocation = registry_with_builtins.parse_and_resolve("/tools")
        assert invocation is not None
        result = await invocation.definition.handler(invocation, {"tools": ["search", "write"]})
        assert isinstance(result, ReplyResult)
        assert "search" in result.text
        assert "write" in result.text

    async def test_tools_handler_empty(self, registry_with_builtins: CommandRegistry) -> None:
        """/tools with no tools returns empty message."""
        invocation = registry_with_builtins.parse_and_resolve("/tools")
        assert invocation is not None
        result = await invocation.definition.handler(invocation, {"tools": []})
        assert isinstance(result, ReplyResult)
        assert "No tools available" in result.text

    async def test_skills_handler_lists_skills(
        self, registry_with_builtins: CommandRegistry
    ) -> None:
        """/skills handler lists available skills."""
        invocation = registry_with_builtins.parse_and_resolve("/skills")
        assert invocation is not None
        result = await invocation.definition.handler(invocation, {"skills": ["coding", "analysis"]})
        assert isinstance(result, ReplyResult)
        assert "coding" in result.text

    async def test_skills_handler_empty(self, registry_with_builtins: CommandRegistry) -> None:
        """/skills with no skills returns empty message."""
        invocation = registry_with_builtins.parse_and_resolve("/skills")
        assert invocation is not None
        result = await invocation.definition.handler(invocation, {"skills": []})
        assert isinstance(result, ReplyResult)
        assert "No skills available" in result.text


# ============================================================================
# Type / Data Model Tests
# ============================================================================


@pytest.mark.unit
class TestCommandTypes:
    """Tests for command type dataclasses."""

    def test_reply_result_defaults(self) -> None:
        """ReplyResult defaults to info level."""
        r = ReplyResult(text="hello")
        assert r.text == "hello"
        assert r.level == "info"

    def test_tool_call_result(self) -> None:
        """ToolCallResult stores tool_name and args."""
        r = ToolCallResult(tool_name="search", args={"q": "test"})
        assert r.tool_name == "search"
        assert r.args == {"q": "test"}

    def test_skill_trigger_result(self) -> None:
        """SkillTriggerResult stores skill_id and optional override."""
        r = SkillTriggerResult(skill_id="coding")
        assert r.skill_id == "coding"
        assert r.text_override is None

    def test_command_invocation_fields(self) -> None:
        """CommandInvocation stores all parsed data."""
        defn = CommandDefinition(
            name="test",
            description="test",
            category=CommandCategory.STATUS,
            handler=_noop_handler,
        )
        inv = CommandInvocation(
            definition=defn,
            raw_text="/test arg1",
            parsed_args={"key": "val"},
            raw_args_text="arg1",
        )
        assert inv.definition.name == "test"
        assert inv.raw_text == "/test arg1"
        assert inv.parsed_args == {"key": "val"}
        assert inv.raw_args_text == "arg1"

    def test_command_parse_error_usage_hint(self) -> None:
        """CommandParseError stores usage_hint."""
        err = CommandParseError("bad input", usage_hint="/cmd <arg>")
        assert str(err) == "bad input"
        assert err.usage_hint == "/cmd <arg>"

    def test_command_parse_error_no_hint(self) -> None:
        """CommandParseError without hint defaults to None."""
        err = CommandParseError("bad input")
        assert err.usage_hint is None
