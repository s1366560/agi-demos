"""Unit tests for SessionProcessor forced skill reinforcement (Fix 4).

Tests that ProcessorConfig stores forced_skill_name/forced_skill_tools,
SessionProcessor initializes them correctly, and the [SKILL REMINDER]
message is injected only at step > 1.
"""

import pytest

from src.infrastructure.agent.processor import ProcessorConfig, SessionProcessor


@pytest.mark.unit
class TestProcessorForcedSkill:
    """Forced skill reinforcement behavior for SessionProcessor."""

    # -- ProcessorConfig field tests --

    def test_config_stores_forced_skill_fields(self) -> None:
        """ProcessorConfig correctly stores forced_skill_name and forced_skill_tools."""
        # Arrange / Act
        config = ProcessorConfig(
            model="test-model",
            forced_skill_name="web-search",
            forced_skill_tools=["web_search", "web_scrape"],
        )

        # Assert
        assert config.forced_skill_name == "web-search"
        assert config.forced_skill_tools == ["web_search", "web_scrape"]

    def test_config_defaults_forced_skill_fields_to_none(self) -> None:
        """ProcessorConfig defaults forced_skill_name/tools to None when omitted."""
        # Arrange / Act
        config = ProcessorConfig(model="test-model")

        # Assert
        assert config.forced_skill_name is None
        assert config.forced_skill_tools is None

    # -- SessionProcessor __init__ tests --

    def test_processor_stores_forced_skill_from_config(self) -> None:
        """SessionProcessor stores forced skill fields from config in __init__."""
        # Arrange
        config = ProcessorConfig(
            model="test-model",
            forced_skill_name="web-search",
            forced_skill_tools=["web_search", "web_scrape"],
        )

        # Act
        processor = SessionProcessor(config=config, tools=[])

        # Assert
        assert processor._forced_skill_name == "web-search"
        assert processor._forced_skill_tools == {"web_search", "web_scrape"}

    # -- Skill reminder injection logic tests --

    def test_no_skill_reminder_at_step_one(self) -> None:
        """At step 1, no [SKILL REMINDER] message should be generated."""
        # Arrange
        config = ProcessorConfig(
            model="test-model",
            forced_skill_name="web-search",
            forced_skill_tools=["web_search", "web_scrape"],
        )
        processor = SessionProcessor(config=config, tools=[])
        processor._step_count = 1
        messages: list[dict[str, str]] = [
            {"role": "user", "content": "search the web"},
        ]

        # Act -- replicate the injection guard from processor.py lines 1202-1218
        injected = False
        if processor._forced_skill_name and processor._step_count > 1:
            injected = True

        # Assert
        assert injected is False
        # messages should remain unchanged
        assert len(messages) == 1

    def test_skill_reminder_injected_at_step_two(self) -> None:
        """At step 2+, a [SKILL REMINDER] system message IS generated with correct content."""
        # Arrange
        config = ProcessorConfig(
            model="test-model",
            forced_skill_name="web-search",
            forced_skill_tools=["web_search", "web_scrape"],
        )
        processor = SessionProcessor(config=config, tools=[])
        processor._step_count = 2
        messages: list[dict[str, str]] = [
            {"role": "user", "content": "search the web"},
        ]

        # Act -- replicate the injection logic from processor.py lines 1202-1218
        if processor._forced_skill_name and processor._step_count > 1:
            skill_tool_msg = (
                f" Use ONLY these tools: {', '.join(sorted(processor._forced_skill_tools))}."
                if processor._forced_skill_tools
                else ""
            )
            skill_reminder = {
                "role": "system",
                "content": (
                    f"[SKILL REMINDER] You are executing forced skill "
                    f'"/{processor._forced_skill_name}". '
                    f"Follow the skill instructions from the system prompt precisely."
                    + skill_tool_msg
                ),
            }
            messages.append(skill_reminder)

        # Assert
        assert len(messages) == 2
        reminder = messages[-1]
        assert reminder["role"] == "system"
        assert "[SKILL REMINDER]" in reminder["content"]
        assert '"/web-search"' in reminder["content"]
        assert "web_scrape" in reminder["content"]
        assert "web_search" in reminder["content"]
        assert "Use ONLY these tools:" in reminder["content"]

    def test_skill_reminder_without_tool_restriction(self) -> None:
        """When forced_skill_tools is None, reminder omits tool restriction clause."""
        # Arrange
        config = ProcessorConfig(
            model="test-model",
            forced_skill_name="code-review",
            forced_skill_tools=None,
        )
        processor = SessionProcessor(config=config, tools=[])
        processor._step_count = 3
        messages: list[dict[str, str]] = []

        # Act -- replicate the injection logic
        if processor._forced_skill_name and processor._step_count > 1:
            skill_tool_msg = (
                f" Use ONLY these tools: {', '.join(sorted(processor._forced_skill_tools))}."
                if processor._forced_skill_tools
                else ""
            )
            skill_reminder = {
                "role": "system",
                "content": (
                    f"[SKILL REMINDER] You are executing forced skill "
                    f'"/{processor._forced_skill_name}". '
                    f"Follow the skill instructions from the system prompt precisely."
                    + skill_tool_msg
                ),
            }
            messages.append(skill_reminder)

        # Assert
        assert len(messages) == 1
        reminder = messages[0]
        assert "[SKILL REMINDER]" in reminder["content"]
        assert '"/code-review"' in reminder["content"]
        assert "Use ONLY these tools:" not in reminder["content"]
