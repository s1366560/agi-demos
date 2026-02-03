"""
V2 SQLAlchemy implementation of APIKeyRepository using BaseRepository.
"""

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.api_key import APIKey
from src.domain.ports.repositories.api_key_repository import APIKeyRepository
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import APIKey as DBAPIKey

logger = logging.getLogger(__name__)


class SqlAPIKeyRepository(BaseRepository[APIKey, DBAPIKey], APIKeyRepository):
    """V2 SQLAlchemy implementation of APIKeyRepository using BaseRepository."""

    _model_class = DBAPIKey

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository."""
        super().__init__(session)

    # === Interface implementation ===

    async def find_by_hash(self, key_hash: str) -> Optional[APIKey]:
        """Find an API key by its hash."""
        query = select(DBAPIKey).where(DBAPIKey.key_hash == key_hash)
        result = await self._session.execute(query)
        db_key = result.scalar_one_or_none()
        return self._to_domain(db_key)

    async def find_by_user(self, user_id: str, limit: int = 50, offset: int = 0) -> List[APIKey]:
        """List all API keys for a user."""
        query = select(DBAPIKey).where(DBAPIKey.user_id == user_id).offset(offset).limit(limit)
        result = await self._session.execute(query)
        db_keys = result.scalars().all()
        return [self._to_domain(k) for k in db_keys]

    async def delete(self, key_id: str) -> None:
        """Delete an API key."""
        db_key = await self._find_db_model_by_id(key_id)
        if db_key:
            await self._session.delete(db_key)
            await self._session.flush()

    async def update_last_used(self, key_id: str, timestamp: datetime) -> None:
        """Update the last_used_at timestamp."""
        db_key = await self._find_db_model_by_id(key_id)
        if db_key:
            db_key.last_used_at = timestamp
            await self._session.flush()

    # === Conversion methods ===

    def _to_domain(self, db_key: Optional[DBAPIKey]) -> Optional[APIKey]:
        """Convert database model to domain model."""
        if db_key is None:
            return None

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

    def _to_db(self, domain_entity: APIKey) -> DBAPIKey:
        """Convert domain entity to database model."""
        return DBAPIKey(
            id=domain_entity.id,
            key_hash=domain_entity.key_hash,
            name=domain_entity.name,
            user_id=domain_entity.user_id,
            is_active=domain_entity.is_active,
            permissions=domain_entity.permissions,
            expires_at=domain_entity.expires_at,
            last_used_at=domain_entity.last_used_at,
            created_at=domain_entity.created_at,
        )

    def _update_fields(self, db_model: DBAPIKey, domain_entity: APIKey) -> None:
        """Update database model fields from domain entity."""
        db_model.key_hash = domain_entity.key_hash
        db_model.name = domain_entity.name
        db_model.user_id = domain_entity.user_id
        db_model.is_active = domain_entity.is_active
        db_model.permissions = domain_entity.permissions
        db_model.expires_at = domain_entity.expires_at
        db_model.last_used_at = domain_entity.last_used_at
