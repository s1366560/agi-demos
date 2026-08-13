"""Fail-closed compatibility shim for the retired platform SQL Plan repository."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.services.plan_repository_port import PlanRepositoryPort
from src.infrastructure.workspace_core.legacy_runtime import legacy_workspace_runtime_retired


class SqlPlanRepository(PlanRepositoryPort):
    """Reject legacy Workspace Plan persistence before touching an SQL session."""

    def __init__(self, db: AsyncSession) -> None:
        _ = db
        legacy_workspace_runtime_retired("plan repository")
