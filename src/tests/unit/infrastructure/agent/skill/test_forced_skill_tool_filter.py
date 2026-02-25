"""Tests for forced skill tool filtering logic.

Validates the tool filtering behavior when a forced skill (/skill-name) is active.
The logic under test restricts available tools to only those declared by the skill
plus essential system tools (abort, todowrite, todoread).

Reference: react_agent.py lines 1780-1807
"""

from unittest.mock import Mock

import pytest

from src.infrastructure.agent.processor import ToolDefinition


def _make_tool(name: str) -> ToolDefinition:
    """Create a minimal ToolDefinition with the given name."""
    return ToolDefinition(
        name=name,
        description=f"Mock {name} tool",
        parameters={},
        execute=lambda: None,
    )


def _apply_forced_skill_filter(
    current_tool_definitions: list[ToolDefinition],
    is_forced: bool,
    matched_skill: object | None,
) -> list[ToolDefinition]:
    """Replicate the exact forced-skill tool filtering logic from ReactAgent.

    This is a standalone copy of the filtering logic from
    react_agent.py _stream_prepare_tools() (lines 1780-1807) so we can
    test it without instantiating the full ReactAgent.
    """
    tools_to_use = list(current_tool_definitions)

    if is_forced and matched_skill:
        skill_tools = set(matched_skill.tools) if matched_skill.tools else set()  # type: ignore[union-attr]
        essential_tools = {"abort", "todowrite", "todoread"}
        allowed_tools = skill_tools | essential_tools
        filtered_tools = [t for t in tools_to_use if t.name in allowed_tools]

        if not filtered_tools:
            tools_to_use = [t for t in tools_to_use if t.name != "skill_loader"]
        else:
            tools_to_use = filtered_tools

    return tools_to_use


def _make_skill(name: str = "test-skill", tools: list[str] | None = None) -> Mock:
    """Create a mock matched_skill object with .name and .tools attributes."""
    skill = Mock()
    skill.name = name
    skill.tools = tools if tools is not None else []
    return skill


# -- All available tools used across multiple tests --
ALL_TOOL_NAMES = [
    "abort",
    "todowrite",
    "todoread",
    "skill_loader",
    "terminal",
    "web_search",
    "memory_search",
    "code_edit",
]


@pytest.mark.unit
class TestForcedSkillToolFilter:
    """Test suite for forced skill tool filtering logic."""

    def test_forced_skill_with_declared_tools_keeps_only_declared_and_essential(self) -> None:
        """When is_forced=True and skill declares tools, only declared + essential tools remain.

        Arrange: skill declares ["terminal", "web_search"], full tool set available.
        Act: apply filter with is_forced=True.
        Assert: result contains terminal, web_search, abort, todowrite, todoread only.
        """
        # Arrange
        all_tools = [_make_tool(name) for name in ALL_TOOL_NAMES]
        skill = _make_skill(name="dev-skill", tools=["terminal", "web_search"])

        # Act
        result = _apply_forced_skill_filter(all_tools, is_forced=True, matched_skill=skill)

        # Assert
        result_names = {t.name for t in result}
        expected = {"terminal", "web_search", "abort", "todowrite", "todoread"}
        assert result_names == expected

    def test_forced_skill_with_no_matching_tools_keeps_only_essentials(self) -> None:
        """When is_forced=True and skill declares tools that don't exist, only essentials remain.

        The essential tools (abort, todowrite, todoread) are always in allowed_tools,
        so filtered_tools is non-empty as long as essentials exist in available tools.
        Non-matching declared tools are simply absent from the result.

        Arrange: skill declares ["nonexistent_a", "nonexistent_b"], essentials available.
        Act: apply filter.
        Assert: only essential tools remain (abort, todowrite, todoread).
        """
        # Arrange
        all_tools = [_make_tool(name) for name in ALL_TOOL_NAMES]
        skill = _make_skill(name="broken-skill", tools=["nonexistent_a", "nonexistent_b"])

        # Act
        result = _apply_forced_skill_filter(all_tools, is_forced=True, matched_skill=skill)

        # Assert
        result_names = {t.name for t in result}
        assert result_names == {"abort", "todowrite", "todoread"}

    def test_forced_skill_with_empty_tools_list_keeps_only_essentials(self) -> None:
        """When is_forced=True and skill declares empty tools, only essentials remain.

        With tools=[], skill_tools is empty set. allowed_tools = essentials only.
        filtered_tools picks up essentials from available tools.

        Arrange: skill.tools = [], essentials available.
        Act: apply filter.
        Assert: only essential tools remain.
        """
        # Arrange
        all_tools = [_make_tool(name) for name in ALL_TOOL_NAMES]
        skill = _make_skill(name="empty-skill", tools=[])

        # Act
        result = _apply_forced_skill_filter(all_tools, is_forced=True, matched_skill=skill)

        # Assert
        result_names = {t.name for t in result}
        assert result_names == {"abort", "todowrite", "todoread"}

    def test_not_forced_preserves_full_tool_set(self) -> None:
        """When is_forced=False, no filtering occurs regardless of matched_skill.

        Arrange: full tool set, is_forced=False.
        Act: apply filter.
        Assert: all tools are preserved unchanged.
        """
        # Arrange
        all_tools = [_make_tool(name) for name in ALL_TOOL_NAMES]
        skill = _make_skill(name="some-skill", tools=["terminal"])

        # Act
        result = _apply_forced_skill_filter(all_tools, is_forced=False, matched_skill=skill)

        # Assert
        result_names = [t.name for t in result]
        assert result_names == ALL_TOOL_NAMES

    def test_essential_tools_always_survive_filtering(self) -> None:
        """Essential tools (abort, todowrite, todoread) are always kept even if not in skill.tools.

        Arrange: skill declares only ["code_edit"], essentials are in the available set.
        Act: apply filter.
        Assert: abort, todowrite, todoread are present alongside code_edit.
        """
        # Arrange
        all_tools = [_make_tool(name) for name in ALL_TOOL_NAMES]
        skill = _make_skill(name="code-skill", tools=["code_edit"])

        # Act
        result = _apply_forced_skill_filter(all_tools, is_forced=True, matched_skill=skill)

        # Assert
        result_names = {t.name for t in result}
        assert "abort" in result_names
        assert "todowrite" in result_names
        assert "todoread" in result_names
        assert "code_edit" in result_names
        # Non-declared, non-essential tools should be excluded
        assert "terminal" not in result_names
        assert "skill_loader" not in result_names

    def test_forced_with_none_matched_skill_preserves_full_tool_set(self) -> None:
        """When is_forced=True but matched_skill is None, no filtering occurs.

        This can happen if the skill name didn't resolve. The guard
        `if is_forced and matched_skill` short-circuits.
        """
        # Arrange
        all_tools = [_make_tool(name) for name in ALL_TOOL_NAMES]

        # Act
        result = _apply_forced_skill_filter(all_tools, is_forced=True, matched_skill=None)

        # Assert
        result_names = [t.name for t in result]
        assert result_names == ALL_TOOL_NAMES

    def test_fallback_when_no_tools_match_at_all_removes_skill_loader(self) -> None:
        """When filtered_tools is truly empty (no essentials available), fallback kicks in.

        This edge case occurs when the available tool set lacks essential tools AND
        the skill's declared tools don't match any available tool.

        Arrange: available tools have no essentials (abort/todowrite/todoread),
                 skill declares non-matching tools.
        Act: apply filter.
        Assert: all available tools minus skill_loader are returned.
        """
        # Arrange - a tool set with NO essential tools
        non_essential_tools = ["skill_loader", "terminal", "web_search", "code_edit"]
        all_tools = [_make_tool(name) for name in non_essential_tools]
        skill = _make_skill(name="edge-skill", tools=["nonexistent"])

        # Act
        result = _apply_forced_skill_filter(all_tools, is_forced=True, matched_skill=skill)

        # Assert
        result_names = {t.name for t in result}
        assert "skill_loader" not in result_names
        assert result_names == {"terminal", "web_search", "code_edit"}
