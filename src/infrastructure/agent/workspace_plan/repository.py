"""In-memory :class:`PlanRepositoryPort` implementation.

Used by unit tests and as the default repo until a SQL variant is added in
M8. Thread-unsafe on purpose — the supervisor enforces single-writer per
workspace.
"""

from __future__ import annotations

from src.domain.model.workspace_plan import Plan
from src.domain.ports.services.plan_repository_port import PlanRepositoryPort


class InMemoryPlanRepository(PlanRepositoryPort):
    """Process-local dict storage for :class:`Plan` aggregates."""

    def __init__(self) -> None:
        self._by_id: dict[str, Plan] = {}
        self._workspace_to_plan: dict[str, str] = {}

    async def save(self, plan: Plan) -> None:
        self._by_id[plan.id] = plan
        self._workspace_to_plan[plan.workspace_id] = plan.id

    async def get(self, plan_id: str) -> Plan | None:
        return self._by_id.get(plan_id)

    async def get_by_workspace(self, workspace_id: str) -> Plan | None:
        plan_id = self._workspace_to_plan.get(workspace_id)
        if plan_id is None:
            return None
        return self._by_id.get(plan_id)

    async def delete(self, plan_id: str) -> None:
        plan = self._by_id.pop(plan_id, None)
        if plan is not None:
            self._workspace_to_plan.pop(plan.workspace_id, None)
