from abc import ABC, abstractmethod

from src.domain.model.workspace.cyber_gene import CyberGene


class CyberGeneRepository(ABC):
    @abstractmethod
    async def save(self, gene: CyberGene) -> CyberGene: ...

    @abstractmethod
    async def find_by_id(self, gene_id: str) -> CyberGene | None: ...

    @abstractmethod
    async def find_by_workspace(
        self,
        workspace_id: str,
        category: str | None = None,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CyberGene]: ...

    @abstractmethod
    async def delete(self, gene_id: str) -> bool: ...
