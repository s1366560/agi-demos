"""Tests for forced skill tool filtering logic.

Validates the tool filtering behavior when a forced skill (/skill-name) is active.
The logic under test keeps all core tools available but removes skill_loader
to prevent loading other skills during forced execution.

Reference: react_agent.py _stream_prepare_tools()
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
    react_agent.py _stream_prepare_tools() so we can
    test it without instantiating the full ReactAgent.

    The forced skill filter only removes skill_loader to prevent
    loading other skills. All core tools remain available so the
    agent can use them to fulfill the skill's instructions.
    """
    tools_to_use = list(current_tool_definitions)

    if is_forced and matched_skill:
        tools_to_use = [t for t in tools_to_use if t.name != "skill_loader"]

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

# Expected tools after forced skill filter (all minus skill_loader)
ALL_EXCEPT_SKILL_LOADER = [name for name in ALL_TOOL_NAMES if name != "skill_loader"]


@pytest.mark.unit
class TestForcedSkillToolFilter:
    """Test suite for forced skill tool filtering logic."""

    def test_forced_skill_keeps_all_core_tools_except_skill_loader(self) -> None:
        """When is_forced=True, all tools except skill_loader are preserved.

        Arrange: skill declares ["terminal", "web_search"], full tool set available.
        Act: apply filter with is_forced=True.
        Assert: all tools except skill_loader remain available.
        """
        # Arrange
        all_tools = [_make_tool(name) for name in ALL_TOOL_NAMES]
        skill = _make_skill(name="dev-skill", tools=["terminal", "web_search"])

        # Act
        result = _apply_forced_skill_filter(all_tools, is_forced=True, matched_skill=skill)

        # Assert
        result_names = [t.name for t in result]
        assert result_names == ALL_EXCEPT_SKILL_LOADER
        assert "skill_loader" not in result_names

    def test_forced_skill_with_no_matching_tools_keeps_all_core_tools(self) -> None:
        """When is_forced=True and skill declares non-existent tools, core tools stay.

        Arrange: skill declares ["nonexistent_a", "nonexistent_b"], full set available.
        Act: apply filter.
        Assert: all tools except skill_loader remain.
        """
        # Arrange
        all_tools = [_make_tool(name) for name in ALL_TOOL_NAMES]
        skill = _make_skill(name="broken-skill", tools=["nonexistent_a", "nonexistent_b"])

        # Act
        result = _apply_forced_skill_filter(all_tools, is_forced=True, matched_skill=skill)

        # Assert
        result_names = [t.name for t in result]
        assert result_names == ALL_EXCEPT_SKILL_LOADER

    def test_forced_skill_with_empty_tools_list_keeps_all_core_tools(self) -> None:
        """When is_forced=True and skill declares empty tools, core tools stay.

        Arrange: skill.tools = [], full set available.
        Act: apply filter.
        Assert: all tools except skill_loader remain.
        """
        # Arrange
        all_tools = [_make_tool(name) for name in ALL_TOOL_NAMES]
        skill = _make_skill(name="empty-skill", tools=[])

        # Act
        result = _apply_forced_skill_filter(all_tools, is_forced=True, matched_skill=skill)

        # Assert
        result_names = [t.name for t in result]
        assert result_names == ALL_EXCEPT_SKILL_LOADER

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

    def test_core_tools_always_available_during_forced_skill(self) -> None:
        """Core tools (terminal, web_search, memory_search, etc.) stay available.

        Arrange: skill declares only ["code_edit"], full set available.
        Act: apply filter with is_forced=True.
        Assert: all core tools including terminal, web_search, etc. are present.
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
        assert "terminal" in result_names
        assert "web_search" in result_names
        assert "memory_search" in result_names
        assert "code_edit" in result_names
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

    def test_forced_skill_removes_skill_loader_even_without_essentials(self) -> None:
        """When tool set has no essentials, skill_loader is still removed.

        Arrange: available tools have no essential tools (abort/todowrite/todoread),
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

    def test_forced_skill_without_skill_loader_in_toolset(self) -> None:
        """When skill_loader is not in the tool set, all tools are preserved.

        Arrange: tool set without skill_loader, forced skill active.
        Act: apply filter.
        Assert: all tools preserved (nothing to remove).
        """
        # Arrange
        tools_without_loader = ["abort", "terminal", "web_search"]
        all_tools = [_make_tool(name) for name in tools_without_loader]
        skill = _make_skill(name="safe-skill", tools=["terminal"])

        # Act
        result = _apply_forced_skill_filter(all_tools, is_forced=True, matched_skill=skill)

        # Assert
        result_names = [t.name for t in result]
        assert result_names == tools_without_loader
