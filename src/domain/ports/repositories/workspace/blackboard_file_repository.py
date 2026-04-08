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
    async def delete(self, file_id: str) -> bool: ...
