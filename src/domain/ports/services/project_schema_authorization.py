"""Required caller authorization; a scope payload alone is never an admission grant."""

from __future__ import annotations

from typing import Protocol

from src.domain.model.project_schema.commands import ProjectSchemaAction, ProjectSchemaScope


class ProjectSchemaAuthorization(Protocol):
    async def authorize(self, scope: ProjectSchemaScope, action: ProjectSchemaAction) -> None:
        """Raise unless this actor may perform this exact action in this exact scope."""
        ...
