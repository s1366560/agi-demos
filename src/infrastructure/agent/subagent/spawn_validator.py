"""Validates whether a SubAgent spawn request is permitted."""

from __future__ import annotations

from src.domain.model.agent.spawn_policy import (
    SpawnPolicy,
    SpawnRejectionCode,
    SpawnValidationResult,
)
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry


class SpawnValidator:
    """Validates whether a SubAgent spawn request is permitted.

    Validation pipeline (short-circuit on first rejection):
    1. Depth check: current_depth < policy.max_depth
    2. Allowlist check: subagent_name in policy.allowed_subagents (if set)
    3. Children count: active children for requester < policy.max_children_per_requester
    4. Global concurrency: total active runs < policy.max_active_runs
    """

    def __init__(self, policy: SpawnPolicy, run_registry: SubAgentRunRegistry) -> None:
        self._policy = policy
        self._registry = run_registry

    def validate(
        self,
        subagent_name: str,
        current_depth: int,
        conversation_id: str,
        requester_session_id: str | None = None,
    ) -> SpawnValidationResult:
        """Run the 4-step validation pipeline."""
        if current_depth >= self._policy.max_depth:
            return SpawnValidationResult.rejected(
                reason=(f"Depth {current_depth} >= max {self._policy.max_depth}"),
                code=SpawnRejectionCode.DEPTH_EXCEEDED,
                context={
                    "current_depth": current_depth,
                    "max_depth": self._policy.max_depth,
                },
            )

        allowed_subagents = self._policy.allowed_subagents
        if allowed_subagents is not None and subagent_name not in allowed_subagents:
            return SpawnValidationResult.rejected(
                reason=f"SubAgent '{subagent_name}' not in allowlist",
                code=SpawnRejectionCode.SUBAGENT_NOT_ALLOWED,
                context={
                    "subagent_name": subagent_name,
                    "allowed": sorted(allowed_subagents),
                },
            )

        active_children = self._registry.count_active_runs(conversation_id)
        if active_children >= self._policy.max_children_per_requester:
            return SpawnValidationResult.rejected(
                reason=(
                    f"Active children {active_children} >= max "
                    f"{self._policy.max_children_per_requester}"
                ),
                code=SpawnRejectionCode.CHILDREN_EXCEEDED,
                context={
                    "active_children": active_children,
                    "max_children": self._policy.max_children_per_requester,
                },
            )

        total_active = self._registry.count_all_active_runs()
        if total_active >= self._policy.max_active_runs:
            return SpawnValidationResult.rejected(
                reason=(f"Total active {total_active} >= max {self._policy.max_active_runs}"),
                code=SpawnRejectionCode.CONCURRENCY_EXCEEDED,
                context={
                    "total_active": total_active,
                    "max_active": self._policy.max_active_runs,
                },
            )

        return SpawnValidationResult.ok()
