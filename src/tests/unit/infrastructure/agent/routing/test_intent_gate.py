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
        """Default IntentGate has no patterns; natural language returns None.

        Per Agent First, plan-mode verdicts come from the LLM-driven
        ReActAgent routing, not from keyword classification here.
        """
        gate = IntentGate()
        assert gate.classify("make a plan for the migration") is None

    def test_classify_complex_task_regex(self) -> None:
        """Default IntentGate has no patterns; complex prose returns None."""
        gate = IntentGate()
        assert gate.classify("implement a full authentication system") is None

    def test_classify_simple_question_regex(self) -> None:
        """Default IntentGate has no patterns; questions return None."""
        gate = IntentGate()
        assert gate.classify("What is the weather today?") is None

    def test_classify_direct_search(self) -> None:
        """Default IntentGate has no patterns; search prose returns None."""
        gate = IntentGate()
        assert gate.classify("search for memory about cats") is None

    def test_classify_direct_web(self) -> None:
        """Default IntentGate has no patterns; web prose returns None."""
        gate = IntentGate()
        assert gate.classify("browse to the documentation page") is None

    def test_classify_no_match_returns_none(self) -> None:
        """Messages without matching patterns return None."""
        gate = IntentGate()

        result = gate.classify("hello there")
        assert result is None

    def test_classify_custom_patterns(self) -> None:
        """IntentGate ignores natural-language custom patterns."""
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
        assert result is None

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
        assert result is None

    def test_default_patterns_not_empty(self) -> None:
        """Default IntentGate ships empty under Agent First; natural language returns None."""
        gate = IntentGate()
        assert gate.classify("make a plan for testing") is None
        assert gate.classify("What is Python?") is None

    def test_routing_decision_metadata(self) -> None:
        """Custom patterns surface intent_gate metadata."""
        patterns = [
            IntentPattern(
                name="explicit_plan",
                path=ExecutionPath.PLAN_MODE,
                keywords=("/plan",),
                confidence=0.9,
            ),
        ]
        gate = IntentGate(patterns=patterns)

        result = gate.classify("/plan deploy")
        assert result is not None
        assert result.metadata is not None
        assert result.metadata["intent_gate"] is True
        assert result.metadata["pattern_name"] == "explicit_plan"

    def test_keyword_match_case_insensitive(self) -> None:
        """Structural command matching is case-insensitive via normalization."""
        patterns = [
            IntentPattern(
                name="plan_cmd",
                path=ExecutionPath.PLAN_MODE,
                keywords=("/plan",),
                confidence=0.9,
            ),
        ]
        gate = IntentGate(patterns=patterns)

        result = gate.classify("/PLAN for the feature")
        assert result is not None
        assert result.path == ExecutionPath.PLAN_MODE

    def test_regex_pattern_matching(self) -> None:
        """Regex-only custom patterns require a structural command message."""
        import re as _re

        patterns = [
            IntentPattern(
                name="complex_task",
                path=ExecutionPath.PLAN_MODE,
                keywords=(),
                confidence=0.8,
                regex=_re.compile(
                    r"^/build\s+(?:full|complete)\s+",
                    _re.IGNORECASE,
                ),
            ),
        ]
        gate = IntentGate(patterns=patterns)

        result = gate.classify("/build complete REST API for user management")
        assert result is not None
        assert result.path == ExecutionPath.PLAN_MODE
        assert (result.metadata or {}).get("pattern_name") == "complex_task"

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
                keywords=("/deploy",),
                confidence=0.9,
                target="deploy_skill",
            ),
        ]
        gate = IntentGate(patterns=patterns)

        result = gate.classify("/deploy application")
        assert result is not None
        assert result.target == "deploy_skill"
        assert result.path == ExecutionPath.DIRECT_SKILL
