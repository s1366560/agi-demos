from abc import ABC, abstractmethod
from typing import List, Optional

from src.domain.model.auth.user import User


class UserRepository(ABC):
    """Repository interface for User entity"""

    @abstractmethod
    async def save(self, user: User) -> User:
        """Save a user (create or update). Returns the saved user."""
        pass

    @abstractmethod
    async def find_by_id(self, user_id: str) -> Optional[User]:
        """Find a user by ID"""
        pass

    @abstractmethod
    async def find_by_email(self, email: str) -> Optional[User]:
        """Find a user by email address"""
        pass

    @abstractmethod
    async def list_all(self, limit: int = 50, offset: int = 0) -> List[User]:
        """List all users with pagination"""
        pass

    @abstractmethod
    async def delete(self, user_id: str) -> bool:
        """Delete a user. Returns True if deleted, False if not found."""
        pass
