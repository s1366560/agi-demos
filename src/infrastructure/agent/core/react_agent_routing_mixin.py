# pyright: reportUninitializedInstanceVariable=false
"""Routing mixin extracted from ``react_agent.py``.

Hosts the execution-path decision helpers. Runtime semantic routing is
agent-first: explicit structural commands may force a path, otherwise the
ReAct loop owns the decision instead of local keyword gates.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

from ..routing import ExecutionPath, IntentGate, RoutingDecision

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

    def _infer_domain_lane(
        self: _RoutingAgent,
        *,
        message: str,
        forced_subagent_name: str | None = None,
        forced_skill_name: str | None = None,
        plan_mode_requested: bool = False,
    ) -> str:
        """Return structural routing lane for router-fabric diagnostics."""
        _ = message
        if forced_subagent_name:
            return "subagent"
        if forced_skill_name:
            return "skill"
        if plan_mode_requested:
            return "planning"
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

        # Natural-language routing is intentionally prompt-driven here.
        # IntentGate remains available for explicit structural commands only,
        # and is not used as a local keyword fallback in this runtime path.

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
