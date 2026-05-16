"""ToolComposition repository port interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.model.agent.tool_composition import ToolComposition


class ToolCompositionRepositoryPort(ABC):
    """Repository interface for ToolComposition entities."""

    @abstractmethod
    async def save(self, composition: ToolComposition) -> ToolComposition:
        """Save a tool composition.

        Args:
            composition: The tool composition to save

        Returns:
            The saved tool composition
        """
        ...

    @abstractmethod
    async def get_by_id(
        self, composition_id: str, tenant_id: str | None = None
    ) -> ToolComposition | None:
        """Get a tool composition by its ID.

        Args:
            composition_id: The ID of the tool composition
            tenant_id: Optional tenant scope

        Returns:
            The tool composition if found, None otherwise
        """
        ...

    @abstractmethod
    async def get_by_name(
        self,
        name: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> ToolComposition | None:
        """Get a tool composition by its name.

        Args:
            name: The name of the tool composition
            tenant_id: Optional tenant scope
            project_id: Optional project scope

        Returns:
            The tool composition if found, None otherwise
        """
        ...

    @abstractmethod
    async def list_by_tools(
        self,
        tool_names: list[str],
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> list[ToolComposition]:
        """List tool compositions that use the specified tools.

        Args:
            tool_names: List of tool names to filter by
            tenant_id: Optional tenant scope
            project_id: Optional project scope

        Returns:
            List of tool compositions that use any of the specified tools
        """
        ...

    @abstractmethod
    async def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> list[ToolComposition]:
        """List all tool compositions.

        Args:
            limit: Maximum number of compositions to return
            offset: Number of compositions to skip
            tenant_id: Optional tenant scope
            project_id: Optional project scope

        Returns:
            List of tool compositions
        """
        ...

    @abstractmethod
    async def update_usage(
        self,
        composition_id: str,
        success: bool,
    ) -> ToolComposition | None:
        """Update composition usage statistics.

        Args:
            composition_id: The ID of the composition
            success: Whether the usage was successful

        Returns:
            The updated composition if found, None otherwise
        """
        ...

    @abstractmethod
    async def delete(self, composition_id: str) -> bool:
        """Delete a tool composition.

        Args:
            composition_id: The ID of the composition to delete

        Returns:
            True if deleted, False if not found
        """
        ...
