from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.model.workspace.workspace_message import WorkspaceMessage


class WorkspaceMessageRepository(ABC):
    @abstractmethod
    async def save(self, message: WorkspaceMessage) -> WorkspaceMessage: ...

    @abstractmethod
    async def find_by_id(self, message_id: str) -> WorkspaceMessage | None: ...

    @abstractmethod
    async def find_by_workspace(
        self,
        workspace_id: str,
        limit: int = 50,
        offset: int = 0,
        before: str | None = None,
    ) -> list[WorkspaceMessage]: ...

    @abstractmethod
    async def find_thread(
        self,
        parent_message_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WorkspaceMessage]: ...

    @abstractmethod
    async def delete(self, message_id: str) -> bool: ...
