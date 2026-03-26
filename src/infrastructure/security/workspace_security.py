"""Workspace security evaluation pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SecurityAction(str, Enum):
    """Actions that can be evaluated."""

    MANAGE_AGENTS = "manage_agents"
    MOVE_AGENTS = "move_agents"
    MANAGE_TASKS = "manage_tasks"
    MANAGE_OBJECTIVES = "manage_objectives"
    MANAGE_GENES = "manage_genes"
    MANAGE_BLACKBOARD = "manage_blackboard"
    MANAGE_TOPOLOGY = "manage_topology"
    MANAGE_MEMBERS = "manage_members"
    VIEW_WORKSPACE = "view_workspace"


class SecurityDecision(str, Enum):
    """Result of security evaluation."""

    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class SecurityContext:
    """Context for a security evaluation."""

    user_id: str
    workspace_id: str
    action: SecurityAction
    resource_id: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class SecurityResult:
    """Result of security evaluation."""

    decision: SecurityDecision
    reason: str
    context: SecurityContext


class SecurityEvaluator:
    """Base class for security evaluators in the pipeline."""

    async def evaluate(self, context: SecurityContext) -> SecurityResult | None:
        """Evaluate security context. Return None to pass to next evaluator."""
        return None


class WorkspaceSecurityPipeline:
    """Middleware-style security pipeline.

    Evaluators are executed in order. First non-None result wins.
    If all evaluators return None, default is DENY.
    """

    def __init__(self) -> None:
        self._evaluators: list[SecurityEvaluator] = []

    def add_evaluator(self, evaluator: SecurityEvaluator) -> None:
        """Add an evaluator to the pipeline."""
        self._evaluators.append(evaluator)

    async def evaluate(self, context: SecurityContext) -> SecurityResult:
        """Run the security pipeline."""
        for evaluator in self._evaluators:
            result = await evaluator.evaluate(context)
            if result is not None:
                logger.info(
                    "Security decision: %s for action=%s user=%s workspace=%s reason=%s",
                    result.decision.value,
                    context.action.value,
                    context.user_id,
                    context.workspace_id,
                    result.reason,
                )
                return result

        # Default deny
        return SecurityResult(
            decision=SecurityDecision.DENY,
            reason="No evaluator approved the action",
            context=context,
        )
