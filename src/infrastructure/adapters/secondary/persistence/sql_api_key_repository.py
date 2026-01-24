"""
SQLAlchemy implementation of APIKeyRepository.
"""

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.api_key import APIKey
from src.domain.ports.repositories.api_key_repository import APIKeyRepository
from src.infrastructure.adapters.secondary.persistence.models import APIKey as DBAPIKey

logger = logging.getLogger(__name__)


class SqlAlchemyAPIKeyRepository(APIKeyRepository):
    """SQLAlchemy implementation of APIKeyRepository"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, api_key: APIKey) -> None:
        """Save an API key (create or update)"""
        # Check if API key exists
        result = await self._session.execute(select(DBAPIKey).where(DBAPIKey.id == api_key.id))
        db_key = result.scalar_one_or_none()

        if db_key:
            # Update existing key
            db_key.key_hash = api_key.key_hash
            db_key.name = api_key.name
            db_key.user_id = api_key.user_id
            db_key.is_active = api_key.is_active
            db_key.permissions = api_key.permissions
            db_key.expires_at = api_key.expires_at
            db_key.last_used_at = api_key.last_used_at
        else:
            # Create new key
            db_key = DBAPIKey(
                id=api_key.id,
                key_hash=api_key.key_hash,
                name=api_key.name,
                user_id=api_key.user_id,
                is_active=api_key.is_active,
                permissions=api_key.permissions,
                expires_at=api_key.expires_at,
                last_used_at=api_key.last_used_at,
                created_at=api_key.created_at,
            )
            self._session.add(db_key)

        await self._session.flush()

    async def find_by_id(self, key_id: str) -> Optional[APIKey]:
        """Find an API key by ID"""
        result = await self._session.execute(select(DBAPIKey).where(DBAPIKey.id == key_id))
        db_key = result.scalar_one_or_none()
        return self._to_domain(db_key) if db_key else None

    async def find_by_hash(self, key_hash: str) -> Optional[APIKey]:
        """Find an API key by its hash"""
        result = await self._session.execute(select(DBAPIKey).where(DBAPIKey.key_hash == key_hash))
        db_key = result.scalar_one_or_none()
        return self._to_domain(db_key) if db_key else None

    async def find_by_user(self, user_id: str, limit: int = 50, offset: int = 0) -> List[APIKey]:
        """List all API keys for a user"""
        result = await self._session.execute(
            select(DBAPIKey).where(DBAPIKey.user_id == user_id).offset(offset).limit(limit)
        )
        db_keys = result.scalars().all()
        return [self._to_domain(k) for k in db_keys]

    async def delete(self, key_id: str) -> None:
        """Delete an API key"""
        result = await self._session.execute(select(DBAPIKey).where(DBAPIKey.id == key_id))
        db_key = result.scalar_one_or_none()
        if db_key:
            await self._session.delete(db_key)
            await self._session.flush()

    async def update_last_used(self, key_id: str, timestamp: datetime) -> None:
        """Update the last_used_at timestamp"""
        result = await self._session.execute(select(DBAPIKey).where(DBAPIKey.id == key_id))
        db_key = result.scalar_one_or_none()
        if db_key:
            db_key.last_used_at = timestamp
            await self._session.flush()

    def _to_domain(self, db_key: DBAPIKey) -> APIKey:
        """Convert database model to domain model"""
        return APIKey(
            id=db_key.id,
            user_id=db_key.user_id,
            key_hash=db_key.key_hash,
            name=db_key.name,
            is_active=db_key.is_active,
            permissions=db_key.permissions,
            created_at=db_key.created_at,
            expires_at=db_key.expires_at,
            last_used_at=db_key.last_used_at,
        )
