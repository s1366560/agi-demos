"""Repository port for PromptTemplate."""

from abc import ABC, abstractmethod
from typing import Optional

from src.domain.model.agent.prompt_template import PromptTemplate


class PromptTemplateRepository(ABC):
    """Repository interface for PromptTemplate persistence."""

    @abstractmethod
    async def save(self, template: PromptTemplate) -> PromptTemplate:
        """Save a template (create or update)."""
        pass

    @abstractmethod
    async def find_by_id(self, template_id: str) -> Optional[PromptTemplate]:
        """Find a template by ID."""
        pass

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: str,
        category: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PromptTemplate]:
        """List templates for a tenant, optionally filtered by category."""
        pass

    @abstractmethod
    async def list_by_project(
        self,
        project_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PromptTemplate]:
        """List templates for a specific project."""
        pass

    @abstractmethod
    async def delete(self, template_id: str) -> bool:
        """Delete a template. Returns True if deleted."""
        pass

    @abstractmethod
    async def increment_usage(self, template_id: str) -> None:
        """Increment usage count for a template."""
        pass
