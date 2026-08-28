"""Tests for structured tool selection strategy.

This test file follows TDD methodology:
1. Write failing test first (RED)
2. Implement minimal code to pass (GREEN)
3. Refactor while keeping tests passing (REFACTOR)

The tests verify that when too many tools are available, the system preserves
the full set unless an audited Agent judgment supplies the ranking.
"""

import logging
from unittest.mock import MagicMock

import pytest

import src.infrastructure.agent.core.tool_selector as tool_selector_module


@pytest.mark.unit
@pytest.mark.parametrize("authority_name", ("_selector", "get_tool_selector"))
def test_process_global_tool_selector_authority_is_retired(authority_name: str) -> None:
    assert not hasattr(tool_selector_module, authority_name)


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
        from src.infrastructure.agent.core.tool_selector import ToolSelectionContext, ToolSelector

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

        context = ToolSelectionContext(max_tools=5)

        selected = selector.select_tools(tools, context)

        # Core tools should be included
        assert "read" in selected
        assert "write" in selected
        assert "edit" in selected
        assert "bash" in selected

    def test_over_limit_without_agent_ranker_preserves_all_tools(self):
        """
        Tool pruning must not make a local subjective fallback decision.
        """
        from src.infrastructure.agent.core.tool_selector import ToolSelectionContext, ToolSelector

        selector = ToolSelector()

        # Create many tools
        tools = {f"tool_{i}": MagicMock() for i in range(50)}
        tools["read"] = MagicMock()  # Core tool
        tools["write"] = MagicMock()  # Core tool

        context = ToolSelectionContext(max_tools=20)

        selected = selector.select_tools(tools, context)

        assert selected == list(tools)

    def test_default_selection_preserves_declaration_order(self):
        """
        Without an Agent verdict, conversation text cannot influence pruning.
        """
        from src.infrastructure.agent.core.tool_selector import ToolSelectionContext, ToolSelector

        selector = ToolSelector()

        tools = {
            "read": MagicMock(),
            "write": MagicMock(),
            "search_web": MagicMock(description="Search the web for information"),
            "calculate": MagicMock(description="Perform calculations"),
            "send_email": MagicMock(description="Send an email"),
        }

        context = ToolSelectionContext(
            max_tools=3,
            conversation_history=[
                {"role": "user", "content": "I need to search for information about Python"}
            ],
        )

        selected = selector.select_tools(tools, context)

        assert selected == list(tools)

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


class TestAgentToolRanking:
    """Test explicit Agent-backed ranking behavior."""

    def test_agent_ranker_can_order_prune_and_emit_audit(
        self,
        caplog: pytest.LogCaptureFixture,
    ):
        from src.infrastructure.agent.core.tool_selector import (
            ToolRankingAuditV2,
            ToolRankingDecisionV2,
            ToolSelectionContext,
            ToolSelector,
        )

        selector = ToolSelector()
        tools = {name: MagicMock() for name in ("alpha", "beta", "gamma", "delta")}

        class AgentRanker:
            name = "test-agent-ranker"
            decision_mode = "structured_tool_call"
            audit_enabled = True

            def rank_tools(self, _tools, _context):
                return ToolRankingDecisionV2(
                    ordered_tool_names=("gamma", "beta"),
                    audit=ToolRankingAuditV2(
                        agent_id="judge:model-a",
                        tool_name="rank_agent_tools_v2",
                        input_json={"candidate_tool_names": list(_tools)},
                        output_json={"ordered_tool_names": ["gamma", "beta"]},
                        rationale="Gamma and beta match the supplied structured evidence.",
                        latency_ms=7,
                    ),
                )

        with caplog.at_level(logging.INFO, logger="agent_decision_audit"):
            selected = selector.select_tools(
                tools,
                ToolSelectionContext(
                    max_tools=2,
                    metadata={
                        "semantic_backend": "agent_decision",
                        "semantic_ranker": AgentRanker(),
                    },
                ),
            )

        assert selected == ["gamma", "beta"]
        audit = next(record for record in caplog.records if record.name == "agent_decision_audit")
        assert audit.agent_id == "judge:model-a"
        assert audit.tool_name == "rank_agent_tools_v2"
        assert audit.latency_ms == 7

    def test_agent_ranker_failure_preserves_all_tools(self):
        from src.infrastructure.agent.core.tool_selector import ToolSelectionContext, ToolSelector

        selector = ToolSelector()
        tools = {name: MagicMock() for name in ("alpha", "beta", "gamma")}

        class FailingAgentRanker:
            name = "failing-agent-ranker"
            decision_mode = "structured_tool_call"
            audit_enabled = True

            def rank_tools(self, _tools, _context):
                raise RuntimeError("judge unavailable")

        selected = selector.select_tools(
            tools,
            ToolSelectionContext(
                max_tools=1,
                metadata={
                    "semantic_backend": "agent_decision",
                    "semantic_ranker": FailingAgentRanker(),
                },
            ),
        )

        assert selected == list(tools)

    def test_invalid_agent_ranker_output_preserves_all_tools(self):
        from src.infrastructure.agent.core.tool_selector import (
            ToolRankingAuditV2,
            ToolRankingDecisionV2,
            ToolSelectionContext,
            ToolSelector,
        )

        selector = ToolSelector()
        tools = {name: MagicMock() for name in ("alpha", "beta", "gamma")}

        class InvalidAgentRanker:
            name = "invalid-agent-ranker"
            decision_mode = "structured_tool_call"
            audit_enabled = True

            def rank_tools(self, _tools, _context):
                return ToolRankingDecisionV2(
                    ordered_tool_names=("missing-tool",),
                    audit=ToolRankingAuditV2(
                        agent_id="judge:model-a",
                        tool_name="rank_agent_tools_v2",
                        input_json={},
                        output_json={"ordered_tool_names": ["missing-tool"]},
                        rationale="Invalid candidate.",
                        latency_ms=1,
                    ),
                )

        selected = selector.select_tools(
            tools,
            ToolSelectionContext(
                max_tools=1,
                metadata={
                    "semantic_backend": "agent_decision",
                    "semantic_ranker": InvalidAgentRanker(),
                },
            ),
        )

        assert selected == list(tools)

    def test_untyped_callable_ranker_cannot_prune(self):
        from src.infrastructure.agent.core.tool_selector import ToolSelectionContext, ToolSelector

        selector = ToolSelector()
        tools = {name: MagicMock() for name in ("alpha", "beta", "gamma")}

        selected = selector.select_tools(
            tools,
            ToolSelectionContext(
                max_tools=1,
                metadata={
                    "semantic_backend": "agent_decision",
                    "semantic_ranker": lambda _tools, _context: ["gamma"],
                },
            ),
        )

        assert selected == list(tools)

    def test_mismatched_agent_ranker_audit_cannot_prune(self):
        from src.infrastructure.agent.core.tool_selector import (
            ToolRankingAuditV2,
            ToolRankingDecisionV2,
            ToolSelectionContext,
            ToolSelector,
        )

        selector = ToolSelector()
        tools = {name: MagicMock() for name in ("alpha", "beta", "gamma")}

        class MismatchedAuditRanker:
            name = "mismatched-audit-ranker"
            decision_mode = "structured_tool_call"
            audit_enabled = True

            def rank_tools(self, _tools, _context):
                return ToolRankingDecisionV2(
                    ordered_tool_names=("gamma",),
                    audit=ToolRankingAuditV2(
                        agent_id="judge:model-a",
                        tool_name="rank_agent_tools_v2",
                        input_json={"candidate_tool_names": list(_tools)},
                        output_json={"ordered_tool_names": ["alpha"]},
                        rationale="The audit output does not match the returned decision.",
                        latency_ms=1,
                    ),
                )

        selected = selector.select_tools(
            tools,
            ToolSelectionContext(
                max_tools=1,
                metadata={
                    "semantic_backend": "agent_decision",
                    "semantic_ranker": MismatchedAuditRanker(),
                },
            ),
        )

        assert selected == list(tools)


class TestToolSelectorIntegration:
    """Integration tests for tool selector."""

    def test_select_tools_preserves_core_tools(self):
        """
        Test that core tools are always preserved even with very low limit.
        """
        from src.infrastructure.agent.core.tool_selector import ToolSelectionContext, ToolSelector

        selector = ToolSelector()

        tools = {
            "read": MagicMock(),
            "write": MagicMock(),
            "mcp_1": MagicMock(),
            "mcp_2": MagicMock(),
            "mcp_3": MagicMock(),
        }

        context = ToolSelectionContext(max_tools=2)

        selected = selector.select_tools(tools, context)

        assert selected == list(tools)

    def test_mcp_tools_selected_by_relevance(self):
        """
        Test that default tool pruning uses deterministic safe order.
        """
        from src.infrastructure.agent.core.tool_selector import ToolSelectionContext, ToolSelector

        selector = ToolSelector()

        tools = {
            "read": MagicMock(),
            "write": MagicMock(),
            "mcp__api__get_users": MagicMock(description="Get list of users"),
            "mcp__api__get_products": MagicMock(description="Get list of products"),
            "mcp__email__send": MagicMock(description="Send an email"),
        }

        context = ToolSelectionContext(
            max_tools=4,
            conversation_history=[{"role": "user", "content": "I want to send an email to users"}],
        )

        selected = selector.select_tools(tools, context)

        assert selected == list(tools)
