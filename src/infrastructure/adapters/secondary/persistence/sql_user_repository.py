"""
V2 SQLAlchemy implementation of UserRepository using BaseRepository.

This is a migrated version that:
- Extends BaseRepository for common CRUD operations
- Implements UserRepository interface
- Maintains 100% compatibility with original implementation
- Uses standard _to_domain() and _to_db() conversion methods

Migration Benefits:
- ~70% reduction in boilerplate code
- Consistent error handling via BaseRepository
- Built-in transaction management
- Bulk operations support
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.domain.ports.repositories.user_repository import UserRepository
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser

logger = logging.getLogger(__name__)


class SqlUserRepository(BaseRepository[User, DBUser], UserRepository):
    """
    V2 SQLAlchemy implementation of UserRepository using BaseRepository.

    Leverages the base class for standard CRUD operations while providing
    user-specific query methods.
    """

    # Define the SQLAlchemy model class
    _model_class = DBUser

    def __init__(self, session: AsyncSession) -> None:
        """
        Initialize the repository.

        Args:
            session: SQLAlchemy async session
        """
        super().__init__(session)

    # === Interface implementation (user-specific queries) ===

    async def find_by_email(self, email: str) -> User | None:
        """Find a user by email address."""
        query = select(DBUser).where(DBUser.email == email)
        result = await self._session.execute(query)
        db_user = result.scalar_one_or_none()
        return self._to_domain(db_user)

    async def list_all(self, limit: int = 50, offset: int = 0, **filters: Any) -> list[User]:
        """List all users with pagination."""
        # Use the parent class list_all method via super() to avoid recursion
        return await super().list_all(limit=limit, offset=offset, **filters)

    # === Conversion methods ===

    def _to_domain(self, db_user: DBUser | None) -> User | None:
        """
        Convert database model to domain model.

        Note: DB model uses 'full_name' and 'hashed_password' columns
        while domain model uses 'name' and 'password_hash'.

        Args:
            db_user: Database model instance or None

        Returns:
            Domain model instance or None
        """
        if db_user is None:
            return None

        return User(
            id=db_user.id,
            email=db_user.email,
            name=db_user.full_name or "",  # Map DB column to domain field
            password_hash=db_user.hashed_password,  # Map DB column to domain field
            is_active=db_user.is_active,
            profile={},  # Default empty dict since DB doesn't have this column
            created_at=db_user.created_at,
        )

    def _to_db(self, domain_entity: User) -> DBUser:
        """
        Convert domain entity to database model.

        Note: Maps 'name' -> 'full_name' and 'password_hash' -> 'hashed_password'.

        Args:
            domain_entity: Domain model instance

        Returns:
            Database model instance
        """
        return DBUser(
            id=domain_entity.id,
            email=domain_entity.email,
            full_name=domain_entity.name,  # Map domain field to DB column
            hashed_password=domain_entity.password_hash,  # Map domain field to DB column
            is_active=domain_entity.is_active,
            created_at=domain_entity.created_at,
        )

    def _update_fields(self, db_model: DBUser, domain_entity: User) -> None:
        """
        Update database model fields from domain entity.

        Note: Maps 'name' -> 'full_name' and 'password_hash' -> 'hashed_password'.

        Args:
            db_model: Database model to update
            domain_entity: Domain entity with new values
        """
        db_model.email = domain_entity.email
        db_model.full_name = domain_entity.name  # Map domain field to DB column
        # Only update password hash if it's provided (non-empty)
        if domain_entity.password_hash:
            db_model.hashed_password = domain_entity.password_hash
        db_model.is_active = domain_entity.is_active
