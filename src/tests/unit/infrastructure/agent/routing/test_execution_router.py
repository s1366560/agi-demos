"""Tests for Execution Router.

Tests the routing logic for determining execution paths.
"""

from typing import Any, Dict, List, Optional

import pytest

from src.infrastructure.agent.routing.execution_router import (
    ExecutionPath,
    RoutingDecision,
    ExecutionRouter,
    SkillMatcher,
    SubAgentMatcher,
    PlanEvaluator,
    create_default_router,
)
from src.infrastructure.agent.config import ExecutionConfig


class MockSkillMatcher:
    """Mock skill matcher for testing."""

    def __init__(self, skills: Dict[str, bool]) -> None:
        """Initialize with skills and their direct execution capability."""
        self.skills = skills

    def match(self, query: str, context: dict) -> Optional[str]:
        """Match query to skill."""
        query_lower = query.lower()
        # Simple keyword matching for common tasks
        if "read" in query_lower and "file" in query_lower:
            return "read_file"
        if "write" in query_lower and "file" in query_lower:
            return "write_file"
        if "search" in query_lower:
            return "search"
        # Check for direct skill name match
        for skill in self.skills:
            if skill in query_lower:
                return skill
        return None

    def can_execute_directly(self, skill_name: str) -> bool:
        """Check if skill can execute directly."""
        return self.skills.get(skill_name, False)


class MockSubAgentMatcher:
    """Mock sub-agent matcher for testing."""

    def __init__(self, subagents: List[str]) -> None:
        """Initialize with available sub-agents."""
        self.subagents = subagents

    def match(self, query: str, context: dict) -> Optional[str]:
        """Match query to sub-agent."""
        query_lower = query.lower()
        for subagent in self.subagents:
            # Check for "code" matching to "code_agent"
            if "code" in subagent and "code" in query_lower:
                return subagent
            # Direct match
            if subagent in query_lower:
                return subagent
        return None

    def get_subagent(self, name: str) -> Any:
        """Get sub-agent by name."""
        return f"SubAgent({name})"


class MockPlanEvaluator:
    """Mock plan evaluator for testing."""

    def __init__(self, plan_keywords: List[str] = None) -> None:
        """Initialize with keywords that trigger plan mode."""
        self.plan_keywords = plan_keywords or ["plan", "design", "architecture", "complex"]

    def should_use_plan_mode(self, query: str, context: dict) -> bool:
        """Check if plan mode should be used."""
        query_lower = query.lower()
        return any(kw in query_lower for kw in self.plan_keywords)

    def estimate_plan_complexity(self, query: str) -> float:
        """Estimate planning complexity."""
        if "complex" in query.lower():
            return 0.9
        return 0.6


class TestExecutionPath:
    """Tests for ExecutionPath enum."""

    def test_path_values(self) -> None:
        """Should have correct path values."""
        assert ExecutionPath.DIRECT_SKILL.value == "direct_skill"
        assert ExecutionPath.SUBAGENT.value == "subagent"
        assert ExecutionPath.PLAN_MODE.value == "plan_mode"
        assert ExecutionPath.REACT_LOOP.value == "react_loop"


class TestRoutingDecision:
    """Tests for RoutingDecision."""

    def test_create_decision(self) -> None:
        """Should create routing decision."""
        decision = RoutingDecision(
            path=ExecutionPath.DIRECT_SKILL,
            confidence=0.95,
            reason="Direct execution",
            target="read_file",
        )

        assert decision.path == ExecutionPath.DIRECT_SKILL
        assert decision.confidence == 0.95
        assert decision.reason == "Direct execution"
        assert decision.target == "read_file"

    def test_decision_with_metadata(self) -> None:
        """Should create decision with metadata."""
        decision = RoutingDecision(
            path=ExecutionPath.PLAN_MODE,
            confidence=0.8,
            reason="Complex task",
            metadata={"complexity": 0.9},
        )

        assert decision.metadata["complexity"] == 0.9

    def test_default_metadata(self) -> None:
        """Should initialize empty metadata dict."""
        decision = RoutingDecision(
            path=ExecutionPath.REACT_LOOP,
            confidence=0.5,
            reason="Default",
        )

        assert decision.metadata == {}


class TestExecutionRouter:
    """Tests for ExecutionRouter."""

    def test_route_to_direct_skill(self) -> None:
        """Should route to direct skill when match found."""
        skill_matcher = MockSkillMatcher({"read_file": True})
        router = ExecutionRouter(skill_matcher=skill_matcher)

        # Use message with skill name to ensure high confidence
        decision = router.decide("read_file the document", {})

        assert decision.path == ExecutionPath.DIRECT_SKILL
        assert decision.target == "read_file"
        assert decision.confidence >= 0.9

    def test_route_to_subagent(self) -> None:
        """Should route to sub-agent when match found."""
        subagent_matcher = MockSubAgentMatcher(["code_agent"])
        config = ExecutionConfig(
            skill_match_threshold=1.0,  # Disable direct skill
            subagent_match_threshold=0.5,
            enable_subagent_routing=True,
        )
        router = ExecutionRouter(
            config=config,
            subagent_matcher=subagent_matcher,
        )

        decision = router.decide("code_agent help me", {})

        assert decision.path == ExecutionPath.SUBAGENT
        assert decision.target == "code_agent"

    def test_route_to_plan_mode(self) -> None:
        """Should route to plan mode for complex tasks."""
        plan_evaluator = MockPlanEvaluator()
        router = ExecutionRouter(
            skill_matcher=MockSkillMatcher({}),
            subagent_matcher=MockSubAgentMatcher([]),
            plan_evaluator=plan_evaluator,
        )

        decision = router.decide("Design a complex system", {})

        assert decision.path == ExecutionPath.PLAN_MODE
        assert "complex" in decision.reason.lower()

    def test_default_to_react_loop(self) -> None:
        """Should default to ReAct loop when no matches found."""
        router = ExecutionRouter(
            skill_matcher=MockSkillMatcher({}),
            subagent_matcher=MockSubAgentMatcher([]),
            plan_evaluator=None,
        )

        decision = router.decide("What is the weather?", {})

        assert decision.path == ExecutionPath.REACT_LOOP

    def test_priority_order(self) -> None:
        """Should prioritize direct skill over sub-agent."""
        skill_matcher = MockSkillMatcher({"read": True})
        subagent_matcher = MockSubAgentMatcher(["read"])  # Also matches

        router = ExecutionRouter(
            skill_matcher=skill_matcher,
            subagent_matcher=subagent_matcher,
        )

        decision = router.decide("Please read", {})

        # Direct skill should win
        assert decision.path == ExecutionPath.DIRECT_SKILL

    def test_skill_below_threshold(self) -> None:
        """Should not use skill if confidence below threshold."""
        skill_matcher = MockSkillMatcher({"rare_skill": True})
        config = ExecutionConfig(skill_match_threshold=0.99)  # High threshold

        router = ExecutionRouter(
            config=config,
            skill_matcher=skill_matcher,
        )

        decision = router.decide("Execute rare_skill", {})

        # Should fall back to ReAct loop
        assert decision.path == ExecutionPath.REACT_LOOP

    def test_subagent_disabled(self) -> None:
        """Should not route to sub-agent when disabled."""
        subagent_matcher = MockSubAgentMatcher(["code_agent"])
        config = ExecutionConfig(enable_subagent_routing=False)

        router = ExecutionRouter(
            config=config,
            subagent_matcher=subagent_matcher,
        )

        decision = router.decide("Help with code", {})

        assert decision.path != ExecutionPath.SUBAGENT

    def test_can_execute_directly(self) -> None:
        """Should check if direct execution is possible."""
        skill_matcher = MockSkillMatcher({"read_file": True})
        router = ExecutionRouter(skill_matcher=skill_matcher)

        assert router.can_execute_directly("read_file document", {})
        assert not router.can_execute_directly("unknown task", {})

    def test_no_matcher_returns_false(self) -> None:
        """Should return False when no matcher configured."""
        router = ExecutionRouter()

        assert not router.can_execute_directly("any task", {})

    def test_context_influences_confidence(self) -> None:
        """Should use context to boost confidence."""
        skill_matcher = MockSkillMatcher({"search": True})
        router = ExecutionRouter(skill_matcher=skill_matcher)

        context_with_history = {
            "recent_messages": ["I want to search", "search for files"]
        }

        decision = router.decide("search", context_with_history)

        # Confidence should be boosted by context
        assert decision.confidence > 0.6


class TestCreateDefaultRouter:
    """Tests for default router creation."""

    def test_create_default(self) -> None:
        """Should create router with default config."""
        router = create_default_router()

        assert isinstance(router, ExecutionRouter)
        assert router._config is not None

    def test_create_with_custom_config(self) -> None:
        """Should create router with custom config."""
        config = ExecutionConfig(max_steps=50)
        router = create_default_router(config=config)

        assert router._config.max_steps == 50


class TestRoutingSummary:
    """Tests for routing summary statistics."""

    def test_empty_decisions(self) -> None:
        """Should handle empty decision list."""
        router = ExecutionRouter()
        summary = router.get_routing_summary([])

        assert summary["total_decisions"] == 0
        assert summary["average_confidence"] == 0.0

    def test_single_decision(self) -> None:
        """Should summarize single decision."""
        router = ExecutionRouter()
        decisions = [
            RoutingDecision(
                path=ExecutionPath.DIRECT_SKILL,
                confidence=0.9,
                reason="test",
            )
        ]

        summary = router.get_routing_summary(decisions)

        assert summary["total_decisions"] == 1
        assert summary["path_distribution"]["direct_skill"] == 1
        assert summary["average_confidence"] == 0.9

    def test_multiple_decisions(self) -> None:
        """Should summarize multiple decisions."""
        router = ExecutionRouter()
        decisions = [
            RoutingDecision(ExecutionPath.DIRECT_SKILL, 0.9, "test1"),
            RoutingDecision(ExecutionPath.SUBAGENT, 0.7, "test2"),
            RoutingDecision(ExecutionPath.REACT_LOOP, 0.5, "test3"),
            RoutingDecision(ExecutionPath.REACT_LOOP, 0.5, "test4"),
        ]

        summary = router.get_routing_summary(decisions)

        assert summary["total_decisions"] == 4
        assert summary["path_distribution"]["direct_skill"] == 1
        assert summary["path_distribution"]["subagent"] == 1
        assert summary["path_distribution"]["react_loop"] == 2
        assert summary["average_confidence"] == 0.65


class TestRouterEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_message(self) -> None:
        """Should handle empty message gracefully."""
        router = ExecutionRouter()

        decision = router.decide("", {})

        assert decision.path == ExecutionPath.REACT_LOOP

    def test_very_long_message(self) -> None:
        """Should handle long messages."""
        router = ExecutionRouter()
        long_message = "analyze " + "data " * 100

        decision = router.decide(long_message, {})

        # Should not crash
        assert decision.path in ExecutionPath

    def test_special_characters(self) -> None:
        """Should handle special characters."""
        router = ExecutionRouter()

        decision = router.decide("Execute: <script>alert('xss')</script>", {})

        # Should not crash
        assert isinstance(decision, RoutingDecision)
