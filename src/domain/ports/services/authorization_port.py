"""Authorization port - Domain layer interface for authorization."""

from abc import ABC, abstractmethod


class AuthorizationPort(ABC):
    """Domain interface for authorization and permission management."""

    @abstractmethod
    async def check_permission(
        self,
        user_id: str,
        permission: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> bool:
        """Check if a user has a specific permission."""
        ...

    @abstractmethod
    async def get_user_permissions(
        self,
        user_id: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> list[str]:
        """Get all permissions for a user in a specific context."""
        ...

    @abstractmethod
    async def assign_role(
        self,
        user_id: str,
        role_name: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        """Assign a role to a user."""
        ...

    @abstractmethod
    async def remove_role(
        self,
        user_id: str,
        role_name: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        """Remove a role from a user."""
        ...

    @abstractmethod
    async def get_user_roles(self, user_id: str, tenant_id: str | None = None) -> list[dict]:
        """Get all roles assigned to a user."""
        ...

    @abstractmethod
    async def initialize_default_roles(self) -> None:
        """Initialize all default roles and permissions in the database."""
        ...
