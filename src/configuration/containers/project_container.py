"""DI sub-container for project domain."""

from collections.abc import Callable
from typing import Never

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.repositories.user_repository import UserRepository
from src.infrastructure.workspace_core.legacy_runtime import legacy_workspace_runtime_retired


class ProjectContainer:
    """Legacy facade for workspace methods that have not moved to V2 yet."""

    def __init__(
        self,
        db: AsyncSession | None = None,
        user_repository_factory: Callable[[], UserRepository] | None = None,
    ) -> None:
        self._db = db
        self._user_repository_factory = user_repository_factory

    def topology_repository(self) -> Never:
        """Reject the retired platform SQL Topology repository."""
        legacy_workspace_runtime_retired("DI topology repository")
