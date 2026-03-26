from abc import ABC, abstractmethod

from src.domain.model.workspace.cyber_objective import CyberObjective


class CyberObjectiveRepository(ABC):
    @abstractmethod
    async def save(self, objective: CyberObjective) -> CyberObjective: ...

    @abstractmethod
    async def find_by_id(self, objective_id: str) -> CyberObjective | None: ...

    @abstractmethod
    async def find_by_workspace(
        self,
        workspace_id: str,
        obj_type: str | None = None,
        parent_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CyberObjective]: ...

    @abstractmethod
    async def delete(self, objective_id: str) -> bool: ...
