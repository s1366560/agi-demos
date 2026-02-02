"""Execution Router for ReActAgent.

Decides the execution path based on input and context:
- Direct skill execution (for simple/known tasks)
- SubAgent routing (for specialized tasks)
- Plan mode (for complex multi-step tasks)
- Normal ReAct loop (default)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

from src.infrastructure.agent.config import ExecutionConfig


class ExecutionPath(Enum):
    """Possible execution paths for a request."""
    DIRECT_SKILL = "direct_skill"      # Execute skill directly without LLM
    SUBAGENT = "subagent"              # Route to specialized sub-agent
    PLAN_MODE = "plan_mode"            # Use planning mode
    REACT_LOOP = "react_loop"          # Standard ReAct reasoning loop


@dataclass
class RoutingDecision:
    """Result of routing analysis."""

    path: ExecutionPath
    confidence: float  # 0.0 to 1.0
    reason: str
    target: Optional[str] = None  # Skill/subagent name if applicable
    metadata: Dict[str, Any] = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


class SkillMatcher(Protocol):
    """Protocol for skill matching."""

    def match(self, query: str, context: Dict[str, Any]) -> Optional[str]:
        """Match a query to a skill name.

        Args:
            query: The user query
            context: Additional context for matching

        Returns:
            The matched skill name or None
        """
        ...

    def can_execute_directly(self, skill_name: str) -> bool:
        """Check if a skill can be executed directly.

        Args:
            skill_name: The skill to check

        Returns:
            True if the skill supports direct execution
        """
        ...


class SubAgentMatcher(Protocol):
    """Protocol for sub-agent matching."""

    def match(self, query: str, context: Dict[str, Any]) -> Optional[str]:
        """Match a query to a sub-agent.

        Args:
            query: The user query
            context: Additional context for matching

        Returns:
            The matched sub-agent name or None
        """
        ...

    def get_subagent(self, name: str) -> Any:
        """Get a sub-agent by name.

        Args:
            name: The sub-agent name

        Returns:
            The sub-agent instance
        """
        ...


class PlanEvaluator(Protocol):
    """Protocol for plan mode evaluation."""

    def should_use_plan_mode(self, query: str, context: Dict[str, Any]) -> bool:
        """Determine if plan mode should be used.

        Args:
            query: The user query
            context: Additional context

        Returns:
            True if plan mode is recommended
        """
        ...

    def estimate_plan_complexity(self, query: str) -> float:
        """Estimate the complexity of planning for a query.

        Args:
            query: The user query

        Returns:
            Complexity score (0.0 = simple, 1.0 = very complex)
        """
        ...


class ExecutionRouter:
    """
    Routes execution requests to appropriate execution paths.

    Analyzes the input message and context to determine the best
    execution strategy: direct skill execution, sub-agent routing,
    plan mode, or standard ReAct loop.
    """

    def __init__(
        self,
        config: Optional[ExecutionConfig] = None,
        skill_matcher: Optional[SkillMatcher] = None,
        subagent_matcher: Optional[SubAgentMatcher] = None,
        plan_evaluator: Optional[PlanEvaluator] = None,
    ) -> None:
        """Initialize the execution router.

        Args:
            config: Execution configuration
            skill_matcher: Skill matching implementation
            subagent_matcher: Sub-agent matching implementation
            plan_evaluator: Plan mode evaluator implementation
        """
        self._config = config or ExecutionConfig()
        self._skill_matcher = skill_matcher
        self._subagent_matcher = subagent_matcher
        self._plan_evaluator = plan_evaluator

    def decide(
        self,
        message: str,
        context: Dict[str, Any],
    ) -> RoutingDecision:
        """Decide the execution path for a request.

        Args:
            message: The user message/request
            context: Additional context (history, user info, etc.)

        Returns:
            A routing decision with the selected path and metadata

        Raises:
            AgentError: If routing analysis fails
        """
        # 1. Check for direct skill execution (highest priority)
        if self._skill_matcher:
            skill = self._skill_matcher.match(message, context)
            if skill and self._skill_matcher.can_execute_directly(skill):
                # Check if confidence meets threshold
                confidence = self._calculate_skill_confidence(message, skill, context)
                if confidence >= self._config.skill_match_threshold:
                    return RoutingDecision(
                        path=ExecutionPath.DIRECT_SKILL,
                        confidence=confidence,
                        reason=f"Direct execution of skill '{skill}'",
                        target=skill,
                    )

        # 2. Check for sub-agent routing
        if self._subagent_matcher and self._config.enable_subagent_routing:
            subagent = self._subagent_matcher.match(message, context)
            if subagent:
                confidence = self._calculate_subagent_confidence(message, subagent, context)
                if confidence >= self._config.subagent_match_threshold:
                    return RoutingDecision(
                        path=ExecutionPath.SUBAGENT,
                        confidence=confidence,
                        reason=f"Route to sub-agent '{subagent}'",
                        target=subagent,
                    )

        # 3. Check for plan mode
        if self._plan_evaluator and self._config.enable_plan_mode:
            if self._plan_evaluator.should_use_plan_mode(message, context):
                complexity = self._plan_evaluator.estimate_plan_complexity(message)
                return RoutingDecision(
                    path=ExecutionPath.PLAN_MODE,
                    confidence=complexity,
                    reason="Complex task requiring planning",
                    metadata={"complexity": complexity},
                )

        # 4. Default to ReAct loop
        return RoutingDecision(
            path=ExecutionPath.REACT_LOOP,
            confidence=0.5,
            reason="Standard ReAct reasoning loop",
        )

    def _calculate_skill_confidence(
        self,
        message: str,
        skill_name: str,
        context: Dict[str, Any],
    ) -> float:
        """Calculate confidence score for skill matching.

        Args:
            message: The user message
            skill_name: The matched skill name
            context: Additional context

        Returns:
            Confidence score (0.0 to 1.0)
        """
        # Base confidence from keyword matching
        base = 0.8 if skill_name.lower() in message.lower() else 0.6

        # Boost if message is short and direct
        if len(message.split()) <= 5:
            base += 0.1

        # Boost if recent context shows similar patterns
        recent_messages = context.get("recent_messages", [])
        if recent_messages:
            last_msg = recent_messages[-1] if recent_messages else ""
            if skill_name.lower() in last_msg.lower():
                base += 0.05

        return min(base, 1.0)

    def _calculate_subagent_confidence(
        self,
        message: str,
        subagent_name: str,
        context: Dict[str, Any],
    ) -> float:
        """Calculate confidence score for sub-agent matching.

        Args:
            message: The user message
            subagent_name: The matched sub-agent name
            context: Additional context

        Returns:
            Confidence score (0.0 to 1.0)
        """
        # Sub-agents typically have lower confidence than direct skills
        base = 0.5 if subagent_name.lower() in message.lower() else 0.4

        # Boost based on message domain specificity
        domain_keywords = {
            "code": ["code", "function", "class", "bug", "refactor"],
            "data": ["data", "analyze", "chart", "graph", "statistics"],
            "file": ["file", "read", "write", "directory", "folder"],
        }

        for domain, keywords in domain_keywords.items():
            if domain in subagent_name.lower():
                if any(kw in message.lower() for kw in keywords):
                    base += 0.15
                    break

        return min(base, 1.0)

    def can_execute_directly(self, message: str, context: Dict[str, Any]) -> bool:
        """Quick check if message can be executed directly.

        Args:
            message: The user message
            context: Additional context

        Returns:
            True if direct execution is possible
        """
        if not self._skill_matcher:
            return False

        skill = self._skill_matcher.match(message, context)
        return skill is not None and self._skill_matcher.can_execute_directly(skill) and self._calculate_skill_confidence(message, skill, context) >= self._config.skill_match_threshold

    def get_routing_summary(self, decisions: List[RoutingDecision]) -> Dict[str, Any]:
        """Get summary statistics for routing decisions.

        Args:
            decisions: List of routing decisions

        Returns:
            Summary statistics
        """
        path_counts = {path: 0 for path in ExecutionPath}
        total_confidence = 0.0

        for decision in decisions:
            path_counts[decision.path] += 1
            total_confidence += decision.confidence

        return {
            "total_decisions": len(decisions),
            "path_distribution": {p.value: c for p, c in path_counts.items()},
            "average_confidence": total_confidence / len(decisions) if decisions else 0.0,
        }


def create_default_router(config: Optional[ExecutionConfig] = None) -> ExecutionRouter:
    """Create an execution router with default matchers.

    Args:
        config: Optional execution configuration

    Returns:
        A configured ExecutionRouter
    """
    return ExecutionRouter(config=config)
