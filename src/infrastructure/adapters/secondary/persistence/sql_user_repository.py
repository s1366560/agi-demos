"""
SQLAlchemy implementation of UserRepository.
"""

import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.domain.ports.repositories.user_repository import UserRepository
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser

logger = logging.getLogger(__name__)


class SqlAlchemyUserRepository(UserRepository):
    """SQLAlchemy implementation of UserRepository"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, user: User) -> None:
        """Save a user (create or update)"""
        # Check if user exists
        result = await self._session.execute(select(DBUser).where(DBUser.id == user.id))
        db_user = result.scalar_one_or_none()

        if db_user:
            # Update existing user (map domain names to DB column names)
            db_user.email = user.email
            db_user.full_name = user.name
            # Ensure we update the password hash if it changed
            if user.password_hash:
                db_user.hashed_password = user.password_hash
            db_user.is_active = user.is_active
        else:
            # Create new user
            db_user = DBUser(
                id=user.id,
                email=user.email,
                full_name=user.name,
                hashed_password=user.password_hash,
                is_active=user.is_active,
                created_at=user.created_at,
            )
            self._session.add(db_user)

        await self._session.flush()

    async def find_by_id(self, user_id: str) -> Optional[User]:
        """Find a user by ID"""
        result = await self._session.execute(select(DBUser).where(DBUser.id == user_id))
        db_user = result.scalar_one_or_none()
        return self._to_domain(db_user) if db_user else None

    async def find_by_email(self, email: str) -> Optional[User]:
        """Find a user by email address"""
        result = await self._session.execute(select(DBUser).where(DBUser.email == email))
        db_user = result.scalar_one_or_none()
        return self._to_domain(db_user) if db_user else None

    async def list_all(self, limit: int = 50, offset: int = 0) -> List[User]:
        """List all users with pagination"""
        result = await self._session.execute(select(DBUser).offset(offset).limit(limit))
        db_users = result.scalars().all()
        return [self._to_domain(u) for u in db_users]

    async def delete(self, user_id: str) -> None:
        """Delete a user"""
        result = await self._session.execute(select(DBUser).where(DBUser.id == user_id))
        db_user = result.scalar_one_or_none()
        if db_user:
            await self._session.delete(db_user)
            await self._session.flush()

    def _to_domain(self, db_user: DBUser) -> User:
        """Convert database model to domain model"""
        return User(
            id=db_user.id,
            email=db_user.email,
            name=db_user.full_name or "",  # Map DB column to domain field
            password_hash=db_user.hashed_password,  # Map DB column to domain field
            is_active=db_user.is_active,
            profile={},  # Default empty dict since DB doesn't have this column
            created_at=db_user.created_at,
        )
