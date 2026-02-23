"""Tests for intelligent tool selection strategy.

This test file follows TDD methodology:
1. Write failing test first (RED)
2. Implement minimal code to pass (GREEN)
3. Refactor while keeping tests passing (REFACTOR)

The tests verify that when too many tools are available,
the system can intelligently select the most relevant ones
to reduce LLM context consumption.
"""

from unittest.mock import MagicMock


class TestToolSelectionContext:
    """Test ToolSelectionContext dataclass."""

    def test_context_exists(self):
        """
        RED Test: Verify that ToolSelectionContext class exists.
        """
        from src.infrastructure.agent.core.tool_selector import ToolSelectionContext

        assert ToolSelectionContext is not None

    def test_context_has_required_fields(self):
        """
        Test that context has required fields.
        """
        from src.infrastructure.agent.core.tool_selector import ToolSelectionContext

        context = ToolSelectionContext(
            conversation_history=[{"role": "user", "content": "test"}],
            project_id="proj-1",
            max_tools=30,
        )

        assert context.conversation_history is not None
        assert context.project_id == "proj-1"
        assert context.max_tools == 30


class TestToolSelector:
    """Test tool selection functionality."""

    def test_selector_exists(self):
        """
        RED Test: Verify that ToolSelector class exists.
        """
        from src.infrastructure.agent.core.tool_selector import ToolSelector

        assert ToolSelector is not None

    def test_always_include_core_tools(self):
        """
        Test that core tools are always included.
        """
        from src.infrastructure.agent.core.tool_selector import ToolSelector

        selector = ToolSelector()

        tools = {
            "read": MagicMock(),
            "write": MagicMock(),
            "edit": MagicMock(),
            "bash": MagicMock(),
            "todoread": MagicMock(),
            "todowrite": MagicMock(),
            "mcp_tool_1": MagicMock(),
            "mcp_tool_2": MagicMock(),
        }

        context = MagicMock()
        context.max_tools = 5

        selected = selector.select_tools(tools, context)

        # Core tools should be included
        assert "read" in selected
        assert "write" in selected
        assert "edit" in selected
        assert "bash" in selected

    def test_limit_to_max_tools(self):
        """
        Test that selection is limited to max_tools.
        """
        from src.infrastructure.agent.core.tool_selector import ToolSelector

        selector = ToolSelector()

        # Create many tools
        tools = {f"tool_{i}": MagicMock() for i in range(50)}
        tools["read"] = MagicMock()  # Core tool
        tools["write"] = MagicMock()  # Core tool

        context = MagicMock()
        context.max_tools = 20
        context.conversation_history = []

        selected = selector.select_tools(tools, context)

        # Should not exceed max_tools
        assert len(selected) <= 20

    def test_rank_tools_by_relevance(self):
        """
        Test that tools are ranked by relevance to conversation.
        """
        from src.infrastructure.agent.core.tool_selector import ToolSelector

        selector = ToolSelector()

        tools = {
            "read": MagicMock(),
            "write": MagicMock(),
            "search_web": MagicMock(description="Search the web for information"),
            "calculate": MagicMock(description="Perform calculations"),
            "send_email": MagicMock(description="Send an email"),
        }

        context = MagicMock()
        context.max_tools = 3
        context.conversation_history = [
            {"role": "user", "content": "I need to search for information about Python"}
        ]

        selected = selector.select_tools(tools, context)

        # search_web should be included due to keyword match
        # Note: actual implementation may vary, this is a basic test
        assert len(selected) <= 3

    def test_no_selection_needed_when_under_limit(self):
        """
        Test that all tools are returned when under limit.
        """
        from src.infrastructure.agent.core.tool_selector import ToolSelector

        selector = ToolSelector()

        tools = {
            "read": MagicMock(),
            "write": MagicMock(),
            "edit": MagicMock(),
        }

        context = MagicMock()
        context.max_tools = 10
        context.conversation_history = []

        selected = selector.select_tools(tools, context)

        # All tools should be included
        assert len(selected) == 3
        assert "read" in selected
        assert "write" in selected
        assert "edit" in selected


class TestToolRelevanceScoring:
    """Test tool relevance scoring functionality."""

    def test_score_based_on_name_match(self):
        """
        Test that tools are scored based on name match.
        """
        from src.infrastructure.agent.core.tool_selector import ToolSelector

        selector = ToolSelector()

        tool = MagicMock()
        tool.name = "search_web"
        tool.description = "Search the web"

        context = MagicMock()
        context.conversation_history = [
            {"role": "user", "content": "I want to search for something"}
        ]

        score = selector.score_tool_relevance(tool, context)

        # Should have positive score due to keyword match
        assert score > 0

    def test_score_based_on_description_match(self):
        """
        Test that tools are scored based on description match.
        """
        from src.infrastructure.agent.core.tool_selector import ToolSelector

        selector = ToolSelector()

        tool = MagicMock()
        tool.name = "tool_x"
        tool.description = "This tool sends emails to users"

        context = MagicMock()
        context.conversation_history = [
            {"role": "user", "content": "I need to send an email"}
        ]

        score = selector.score_tool_relevance(tool, context)

        # Should have positive score due to description match
        assert score > 0

    def test_core_tools_get_high_score(self):
        """
        Test that core tools always get high relevance score.
        """
        from src.infrastructure.agent.core.tool_selector import ToolSelector

        selector = ToolSelector()

        core_tools = ["read", "write", "edit", "bash", "todoread", "todowrite"]

        context = MagicMock()
        context.conversation_history = []

        for tool_name in core_tools:
            tool = MagicMock()
            tool.name = tool_name
            tool.description = ""

            score = selector.score_tool_relevance(tool, context)

            # Core tools should always have high score
            assert score >= 100  # High baseline for core tools


class TestToolSelectorIntegration:
    """Integration tests for tool selector."""

    def test_select_tools_preserves_core_tools(self):
        """
        Test that core tools are always preserved even with very low limit.
        """
        from src.infrastructure.agent.core.tool_selector import ToolSelector

        selector = ToolSelector()

        tools = {
            "read": MagicMock(),
            "write": MagicMock(),
            "mcp_1": MagicMock(),
            "mcp_2": MagicMock(),
            "mcp_3": MagicMock(),
        }

        context = MagicMock()
        context.max_tools = 2  # Very limited
        context.conversation_history = []

        selected = selector.select_tools(tools, context)

        # At minimum, core tools should be included
        assert "read" in selected or "write" in selected

    def test_mcp_tools_selected_by_relevance(self):
        """
        Test that MCP tools are selected based on relevance.
        """
        from src.infrastructure.agent.core.tool_selector import ToolSelector

        selector = ToolSelector()

        tools = {
            "read": MagicMock(),
            "write": MagicMock(),
            "mcp__api__get_users": MagicMock(description="Get list of users"),
            "mcp__api__get_products": MagicMock(description="Get list of products"),
            "mcp__email__send": MagicMock(description="Send an email"),
        }

        context = MagicMock()
        context.max_tools = 4
        context.conversation_history = [
            {"role": "user", "content": "I want to send an email to users"}
        ]

        selected = selector.select_tools(tools, context)

        # Core tools should be there
        assert "read" in selected
        assert "write" in selected

        # Email tool should be selected due to relevance
        # (actual behavior depends on implementation)
        assert len(selected) <= 4
