from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from src.domain.model.auth.api_key import APIKey


class APIKeyRepository(ABC):
    """Repository interface for APIKey entity"""

    @abstractmethod
    async def save(self, api_key: APIKey) -> None:
        """Save an API key (create or update)"""
        pass

    @abstractmethod
    async def find_by_id(self, key_id: str) -> Optional[APIKey]:
        """Find an API key by ID"""
        pass

    @abstractmethod
    async def find_by_hash(self, key_hash: str) -> Optional[APIKey]:
        """Find an API key by its hash"""
        pass

    @abstractmethod
    async def find_by_user(self, user_id: str, limit: int = 50, offset: int = 0) -> List[APIKey]:
        """List all API keys for a user"""
        pass

    @abstractmethod
    async def delete(self, key_id: str) -> None:
        """Delete an API key"""
        pass

    @abstractmethod
    async def update_last_used(self, key_id: str, timestamp: datetime) -> None:
        """Update the last_used_at timestamp"""
        pass
