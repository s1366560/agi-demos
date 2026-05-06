# pyright: reportUninitializedInstanceVariable=false
"""Routing mixin extracted from ``react_agent.py``.

Hosts the lane-inference / execution-path-decision / skill-matching helpers
without changing any behavior. ``ReActAgent`` composes this mixin via
multiple inheritance.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, cast

from ..routing import ExecutionPath, IntentGate, RoutingDecision
from ..skill import SkillProtocol

if TYPE_CHECKING:
    from src.domain.model.agent.skill import Skill

logger = logging.getLogger(__name__)


class _RoutingAgent(Protocol):
    """Subset of ``ReActAgent`` state used by :class:`RoutingMixin`."""

    skills: list[Skill]
    agent_mode: str
    skill_match_threshold: float
    raw_tools: dict[str, Any]
    _use_dynamic_tools: bool
    _tool_provider: Callable[..., Any] | None
    _intent_gate: IntentGate

    def _infer_domain_lane(
        self,
        *,
        message: str,
        forced_subagent_name: str | None = ...,
        forced_skill_name: str | None = ...,
        plan_mode_requested: bool = ...,
    ) -> str: ...


class RoutingMixin:
    """Routing helpers (lane inference, execution path, skill match)."""

    _DOMAIN_LANE_RULES: ClassVar[tuple[tuple[str, tuple[str, ...]], ...]] = (
        ("plugin", ("plugin", "channel", "reload", "install", "uninstall", "enable", "disable")),
        ("mcp", ("mcp", "sandbox", "tool server", "connector")),
        ("governance", ("policy", "permission", "compliance", "audit", "risk", "guard")),
        ("code", ("code", "refactor", "test", "build", "compile", "debug", "function", "class")),
        ("data", ("memory", "entity", "graph", "sql", "database", "query", "episode")),
    )

    def _infer_domain_lane(
        self: _RoutingAgent,
        *,
        message: str,
        forced_subagent_name: str | None = None,
        forced_skill_name: str | None = None,
        plan_mode_requested: bool = False,
    ) -> str:
        """Infer routing lane for router-fabric diagnostics."""
        if forced_subagent_name:
            return "subagent"
        if forced_skill_name:
            return "skill"
        if plan_mode_requested:
            return "planning"

        normalized = message.lower()
        for lane, keywords in RoutingMixin._DOMAIN_LANE_RULES:
            if any(keyword in normalized for keyword in keywords):
                return lane
        return "general"

    def _decide_execution_path(
        self: _RoutingAgent,
        *,
        message: str,
        conversation_context: list[dict[str, str]],
        forced_subagent_name: str | None = None,
        forced_skill_name: str | None = None,
        plan_mode_requested: bool = False,
    ) -> RoutingDecision:
        """Decide execution path via centralized ExecutionRouter."""
        domain_lane = self._infer_domain_lane(
            message=message,
            forced_subagent_name=forced_subagent_name,
            forced_skill_name=forced_skill_name,
            plan_mode_requested=plan_mode_requested,
        )
        if forced_subagent_name:
            return RoutingDecision(
                path=ExecutionPath.REACT_LOOP,
                confidence=1.0,
                reason="Forced delegation via system instruction (subagent-as-tool)",
                target=forced_subagent_name,
                metadata={
                    "forced_subagent": forced_subagent_name,
                    "domain_lane": domain_lane,
                    "router_fabric_version": "lane-v1",
                },
            )
        if forced_skill_name:
            return RoutingDecision(
                path=ExecutionPath.DIRECT_SKILL,
                confidence=1.0,
                reason="Forced skill execution requested",
                target=forced_skill_name,
                metadata={
                    "domain_lane": domain_lane,
                    "router_fabric_version": "lane-v1",
                },
            )
        if plan_mode_requested:
            return RoutingDecision(
                path=ExecutionPath.PLAN_MODE,
                confidence=1.0,
                reason="Plan mode explicitly requested",
                metadata={
                    "domain_lane": domain_lane,
                    "router_fabric_version": "lane-v1",
                },
            )

        # Intent gate: lightweight pattern-based pre-classification
        gate_result = self._intent_gate.classify(
            message,
            _available_skills=[s.name for s in (self.skills or [])],
        )
        if gate_result is not None:
            if gate_result.metadata is None:
                gate_result.metadata = {}
            gate_result.metadata["domain_lane"] = domain_lane
            gate_result.metadata["router_fabric_version"] = "lane-v1"
            return gate_result

        # Default to ReAct loop -- prompt-driven routing replaces
        # confidence scoring
        return RoutingDecision(
            path=ExecutionPath.REACT_LOOP,
            confidence=0.5,
            reason="Standard ReAct reasoning loop",
            metadata={
                "domain_lane": domain_lane,
                "router_fabric_version": "lane-v1",
            },
        )

    def _estimate_available_tool_count(self: _RoutingAgent) -> int:
        """Estimate available tool count without mutating selection trace state."""
        if self._use_dynamic_tools and self._tool_provider is not None:
            try:
                dynamic_tools = self._tool_provider()
                if isinstance(dynamic_tools, dict):
                    return len(dynamic_tools)
            except Exception:
                logger.warning(
                    "Failed to fetch dynamic tools for router threshold check", exc_info=True
                )
        return len(self.raw_tools)

    def _match_skill(
        self: _RoutingAgent,
        query: str,
        available_skills: list[SkillProtocol] | None = None,
    ) -> tuple[SkillProtocol | None, float]:
        """Match query against available skills, filtered by agent_mode.

        Inlined from SkillOrchestrator.match() (Wave 5.1).

        Args:
            query: User query

        Returns:
            Tuple of (best matching skill or None, match score)
        """
        skills = available_skills or cast("list[SkillProtocol]", self.skills or [])
        if not skills:
            logger.debug("[ReActAgent] No skills available for matching")
            return None, 0.0

        best_skill: SkillProtocol | None = None
        best_score = 0.0

        for skill in skills:
            if not skill.is_accessible_by_agent(self.agent_mode):
                continue
            if skill.status.value != "active":
                continue
            score = skill.matches_query(query)
            if score > best_score:
                best_score = score
                best_skill = skill

        if best_skill and best_score >= self.skill_match_threshold:
            logger.info(
                f"[ReActAgent] Matched skill: {best_skill.name} with score {best_score:.2f}"
            )
            return best_skill, best_score

        logger.debug("[ReActAgent] No skill matched for query")
        return None, 0.0
