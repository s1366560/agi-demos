from abc import ABC, abstractmethod
from datetime import datetime

from src.domain.model.auth.api_key import APIKey


class APIKeyRepository(ABC):
    """Repository interface for APIKey entity"""

    @abstractmethod
    async def save(self, api_key: APIKey) -> APIKey:
        """Save an API key (create or update)"""

    @abstractmethod
    async def find_by_id(self, key_id: str) -> APIKey | None:
        """Find an API key by ID"""

    @abstractmethod
    async def find_by_hash(self, key_hash: str) -> APIKey | None:
        """Find an API key by its hash"""

    @abstractmethod
    async def find_by_user(self, user_id: str, limit: int = 50, offset: int = 0) -> list[APIKey]:
        """List all API keys for a user"""

    @abstractmethod
    async def delete(self, key_id: str) -> bool:
        """Delete an API key"""

    @abstractmethod
    async def update_last_used(self, key_id: str, timestamp: datetime) -> None:
        """Update the last_used_at timestamp"""
