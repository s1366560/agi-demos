"""DI sub-container for authentication and authorization domain."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.repositories.api_key_repository import APIKeyRepository
from src.domain.ports.repositories.tenant_repository import TenantRepository
from src.domain.ports.repositories.user_repository import UserRepository
from src.infrastructure.adapters.secondary.persistence.sql_api_key_repository import (
    SqlAPIKeyRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_tenant_repository import (
    SqlTenantRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_user_repository import (
    SqlUserRepository,
)


class AuthContainer:
    """Sub-container for auth-related repositories.

    Provides factory methods for user, API key, and tenant repositories.
    """

    def __init__(self, db: AsyncSession | None = None) -> None:
        self._db = db

    def user_repository(self) -> UserRepository:
        """Get UserRepository for user persistence."""
        return SqlUserRepository(self._db)

    def api_key_repository(self) -> APIKeyRepository:
        """Get APIKeyRepository for API key persistence."""
        return SqlAPIKeyRepository(self._db)

    def tenant_repository(self) -> TenantRepository:
        """Get TenantRepository for tenant persistence."""
        return SqlTenantRepository(self._db)
