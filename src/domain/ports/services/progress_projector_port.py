"""Port: progress projector — aggregates plan state into GoalProgress."""

from __future__ import annotations

from typing import Protocol

from src.domain.model.workspace_plan import GoalProgress, Plan


class ProgressProjectorPort(Protocol):
    def project(self, plan: Plan) -> GoalProgress: ...
