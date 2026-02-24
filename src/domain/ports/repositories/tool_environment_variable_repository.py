"""
ToolEnvironmentVariableRepository port for environment variable persistence.

Repository interface for persisting and retrieving tool environment variables,
following the Repository pattern with tenant and project-level isolation.
"""

from abc import ABC, abstractmethod

from src.domain.model.agent.tool_environment_variable import (
    EnvVarScope,
    ToolEnvironmentVariable,
)


class ToolEnvironmentVariableRepositoryPort(ABC):
    """
    Repository port for tool environment variable persistence.

    Provides CRUD operations for environment variables with tenant
    and project-level isolation for multi-tenant support.
    """

    @abstractmethod
    async def create(self, env_var: ToolEnvironmentVariable) -> ToolEnvironmentVariable:
        """
        Create a new environment variable.

        Args:
            env_var: Environment variable to create

        Returns:
            Created environment variable with generated ID

        Raises:
            ValueError: If env_var data is invalid or already exists
        """

    @abstractmethod
    async def get_by_id(self, env_var_id: str) -> ToolEnvironmentVariable | None:
        """
        Get an environment variable by its ID.

        Args:
            env_var_id: Environment variable ID

        Returns:
            Environment variable if found, None otherwise
        """

    @abstractmethod
    async def get(
        self,
        tenant_id: str,
        tool_name: str,
        variable_name: str,
        project_id: str | None = None,
    ) -> ToolEnvironmentVariable | None:
        """
        Get an environment variable by tenant, tool, and name.

        If project_id is provided, looks for project-level variable first,
        then falls back to tenant-level. If project_id is None, only looks
        for tenant-level variables.

        Args:
            tenant_id: Tenant ID
            tool_name: Tool name
            variable_name: Variable name
            project_id: Optional project ID for project-level lookup

        Returns:
            Environment variable if found, None otherwise
        """

    @abstractmethod
    async def get_for_tool(
        self,
        tenant_id: str,
        tool_name: str,
        project_id: str | None = None,
    ) -> list[ToolEnvironmentVariable]:
        """
        Get all environment variables for a tool.

        Returns merged list with project-level variables overriding
        tenant-level variables with the same name.

        Args:
            tenant_id: Tenant ID
            tool_name: Tool name
            project_id: Optional project ID for project-level variables

        Returns:
            List of environment variables for the tool
        """

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: str,
        scope: EnvVarScope | None = None,
    ) -> list[ToolEnvironmentVariable]:
        """
        List all environment variables for a tenant.

        Args:
            tenant_id: Tenant ID
            scope: Optional scope filter (tenant or project)

        Returns:
            List of environment variables
        """

    @abstractmethod
    async def list_by_project(
        self,
        tenant_id: str,
        project_id: str,
    ) -> list[ToolEnvironmentVariable]:
        """
        List all environment variables for a project.

        Args:
            tenant_id: Tenant ID
            project_id: Project ID

        Returns:
            List of project-level environment variables
        """

    @abstractmethod
    async def update(self, env_var: ToolEnvironmentVariable) -> ToolEnvironmentVariable:
        """
        Update an existing environment variable.

        Args:
            env_var: Environment variable to update

        Returns:
            Updated environment variable

        Raises:
            ValueError: If env_var not found or data is invalid
        """

    @abstractmethod
    async def delete(self, env_var_id: str) -> bool:
        """
        Delete an environment variable by ID.

        Args:
            env_var_id: Environment variable ID to delete

        Raises:
            ValueError: If env_var not found
        """

    @abstractmethod
    async def delete_by_tool(
        self,
        tenant_id: str,
        tool_name: str,
        project_id: str | None = None,
    ) -> int:
        """
        Delete all environment variables for a tool.

        Args:
            tenant_id: Tenant ID
            tool_name: Tool name
            project_id: Optional project ID (if None, deletes tenant-level)

        Returns:
            Number of deleted variables
        """

    @abstractmethod
    async def upsert(self, env_var: ToolEnvironmentVariable) -> ToolEnvironmentVariable:
        """
        Create or update an environment variable.

        If a variable with the same tenant_id, project_id, tool_name,
        and variable_name exists, updates it. Otherwise creates a new one.

        Args:
            env_var: Environment variable to upsert

        Returns:
            Created or updated environment variable
        """

    @abstractmethod
    async def batch_upsert(
        self,
        env_vars: list[ToolEnvironmentVariable],
    ) -> list[ToolEnvironmentVariable]:
        """
        Batch create or update environment variables.

        Args:
            env_vars: List of environment variables to upsert

        Returns:
            List of created or updated environment variables
        """
