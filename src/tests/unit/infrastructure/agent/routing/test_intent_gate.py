"""Tests for IntentGate pre-classification system."""


import pytest

from src.infrastructure.agent.routing.execution_router import (
    ExecutionPath,
)
from src.infrastructure.agent.routing.intent_gate import (
    IntentGate,
    IntentPattern,
)


@pytest.mark.unit
class TestIntentGate:
    """Test suite for IntentGate classification."""

    def test_classify_empty_message_returns_none(self) -> None:
        """Empty or whitespace-only messages return None."""
        gate = IntentGate()

        assert gate.classify("") is None
        assert gate.classify("   ") is None
        assert gate.classify("\n\t") is None

    def test_classify_explicit_plan_keywords(self) -> None:
        """Messages with plan keywords route to PLAN_MODE."""
        gate = IntentGate()

        result = gate.classify("make a plan for the migration")
        assert result is not None
        assert result.path == ExecutionPath.PLAN_MODE
        assert result.confidence == 0.9
        assert result.reason == "Intent gate: explicit_plan"

    def test_classify_complex_task_regex(self) -> None:
        """Complex task descriptions route to PLAN_MODE via regex."""
        gate = IntentGate()

        result = gate.classify("implement a full authentication system")
        assert result is not None
        assert result.path == ExecutionPath.PLAN_MODE
        assert result.confidence == 0.8

    def test_classify_simple_question_regex(self) -> None:
        """Simple questions route to REACT_LOOP with 0.8 confidence."""
        gate = IntentGate()

        result = gate.classify("What is the weather today?")
        assert result is not None
        assert result.path == ExecutionPath.REACT_LOOP
        assert result.confidence == 0.8
        assert "simple_question" in (result.metadata or {}).get("pattern_name", "")

    def test_classify_direct_search(self) -> None:
        """Search keywords route to REACT_LOOP with 0.8 confidence."""
        gate = IntentGate()

        result = gate.classify("search for memory about cats")
        assert result is not None
        assert result.path == ExecutionPath.REACT_LOOP
        assert result.confidence == 0.8
        assert (result.metadata or {}).get("pattern_name") == ("direct_search")

    def test_classify_direct_web(self) -> None:
        """Web-related keywords route to REACT_LOOP with 0.8 confidence."""
        gate = IntentGate()

        result = gate.classify("browse to the documentation page")
        assert result is not None
        assert result.path == ExecutionPath.REACT_LOOP
        assert result.confidence == 0.8
        assert (result.metadata or {}).get("pattern_name") == "direct_web"

    def test_classify_no_match_returns_none(self) -> None:
        """Messages without matching patterns return None."""
        gate = IntentGate()

        result = gate.classify("hello there")
        assert result is None

    def test_classify_custom_patterns(self) -> None:
        """IntentGate works with custom patterns."""
        custom_patterns = [
            IntentPattern(
                name="greeting",
                path=ExecutionPath.REACT_LOOP,
                keywords=("hello", "hi", "hey"),
                confidence=0.9,
            ),
        ]
        gate = IntentGate(patterns=custom_patterns)

        result = gate.classify("hello world")
        assert result is not None
        assert result.path == ExecutionPath.REACT_LOOP
        assert result.confidence == 0.9
        assert (result.metadata or {}).get("pattern_name") == "greeting"

    def test_classify_min_confidence_threshold(self) -> None:
        """Patterns below min_confidence threshold return None."""
        low_conf_patterns = [
            IntentPattern(
                name="low_conf",
                path=ExecutionPath.REACT_LOOP,
                keywords=("test",),
                confidence=0.5,
            ),
        ]
        gate = IntentGate(
            patterns=low_conf_patterns,
            min_confidence=0.7,
        )

        result = gate.classify("test message")
        assert result is None

    def test_classify_best_match_wins(self) -> None:
        """When multiple patterns match, highest confidence wins."""
        patterns = [
            IntentPattern(
                name="low",
                path=ExecutionPath.REACT_LOOP,
                keywords=("search",),
                confidence=0.7,
            ),
            IntentPattern(
                name="high",
                path=ExecutionPath.PLAN_MODE,
                keywords=("search",),
                confidence=0.95,
            ),
        ]
        gate = IntentGate(patterns=patterns)

        result = gate.classify("search for something")
        assert result is not None
        assert result.path == ExecutionPath.PLAN_MODE
        assert result.confidence == 0.95
        assert (result.metadata or {}).get("pattern_name") == "high"

    def test_default_patterns_not_empty(self) -> None:
        """Default IntentGate has patterns loaded."""
        gate = IntentGate()

        # Verify default patterns exist by checking known classifications
        assert gate.classify("make a plan for testing") is not None
        assert gate.classify("What is Python?") is not None

    def test_routing_decision_metadata(self) -> None:
        """Returned decision includes intent_gate metadata."""
        gate = IntentGate()

        result = gate.classify("make a plan for deployment")
        assert result is not None
        assert result.metadata is not None
        assert result.metadata["intent_gate"] is True
        assert result.metadata["pattern_name"] == "explicit_plan"

    def test_keyword_match_case_insensitive(self) -> None:
        """Keyword matching is case-insensitive via normalization."""
        gate = IntentGate()

        result = gate.classify("Make A Plan for the feature")
        assert result is not None
        assert result.path == ExecutionPath.PLAN_MODE

    def test_regex_pattern_matching(self) -> None:
        """Regex-only patterns (no keywords) match correctly."""
        gate = IntentGate()

        result = gate.classify("build a complete REST API for user management")
        assert result is not None
        assert result.path == ExecutionPath.PLAN_MODE
        assert (result.metadata or {}).get("pattern_name") == ("complex_task")

    def test_available_skills_parameter_accepted(self) -> None:
        """The _available_skills parameter is accepted without error."""
        gate = IntentGate()

        # Should not raise -- _available_skills is for future use
        result = gate.classify(
            "hello",
            _available_skills=["skill_a", "skill_b"],
        )
        assert result is None

    def test_pattern_with_target(self) -> None:
        """IntentPattern target field propagates to RoutingDecision."""
        patterns = [
            IntentPattern(
                name="targeted",
                path=ExecutionPath.DIRECT_SKILL,
                keywords=("deploy",),
                confidence=0.9,
                target="deploy_skill",
            ),
        ]
        gate = IntentGate(patterns=patterns)

        result = gate.classify("deploy the application")
        assert result is not None
        assert result.target == "deploy_skill"
        assert result.path == ExecutionPath.DIRECT_SKILL
