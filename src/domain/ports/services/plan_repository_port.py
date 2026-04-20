"""Port: persist and query :class:`Plan` aggregates."""

from __future__ import annotations

from typing import Protocol

from src.domain.model.workspace_plan import Plan


class PlanRepositoryPort(Protocol):
    async def save(self, plan: Plan) -> None: ...
    async def get(self, plan_id: str) -> Plan | None: ...
    async def get_by_workspace(self, workspace_id: str) -> Plan | None:
        """Return the active plan for a workspace, or None."""
        ...

    async def delete(self, plan_id: str) -> None: ...
