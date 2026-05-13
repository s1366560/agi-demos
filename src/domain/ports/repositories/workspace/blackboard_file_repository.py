from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.model.workspace.blackboard_file import BlackboardFile


class BlackboardFileRepository(ABC):
    """Repository interface for workspace blackboard files."""

    @abstractmethod
    async def save(self, file: BlackboardFile) -> BlackboardFile: ...

    @abstractmethod
    async def find_by_id(self, file_id: str) -> BlackboardFile | None: ...

    @abstractmethod
    async def list_by_workspace(
        self,
        workspace_id: str,
        parent_path: str = "/",
    ) -> list[BlackboardFile]: ...

    @abstractmethod
    async def find_descendants(
        self,
        workspace_id: str,
        path_prefix: str,
    ) -> list[BlackboardFile]:
        """Return all files whose parent_path starts with ``path_prefix``."""

    @abstractmethod
    async def bulk_update_parent_path(
        self,
        workspace_id: str,
        old_prefix: str,
        new_prefix: str,
    ) -> int:
        """Rewrite descendant ``parent_path`` from ``old_prefix`` to ``new_prefix``.

        Returns the number of rows updated.
        """

    @abstractmethod
    async def update_checksum(
        self,
        file_id: str,
        checksum_sha256: str,
    ) -> None:
        """Idempotent backfill: set checksum_sha256 only when currently NULL."""

    @abstractmethod
    async def delete(self, file_id: str) -> bool: ...
