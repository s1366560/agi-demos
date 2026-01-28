"""Sample Python file for testing AST tools.

This file contains various Python constructs for parsing.
"""

import os
import sys
from typing import List, Optional
from dataclasses import dataclass

# Local imports
from collections import defaultdict


# Constants
MAX_ITEMS = 100
DEFAULT_TIMEOUT = 30


@dataclass
class User:
    """A user entity."""

    name: str
    age: int
    email: Optional[str] = None


class BaseService:
    """Base service class with common functionality."""

    def __init__(self, config: dict):
        self.config = config
        self._initialized = False

    def start(self) -> None:
        """Start the service."""
        self._initialized = True

    def stop(self) -> None:
        """Stop the service."""
        self._initialized = False


class UserService(BaseService):
    """Service for managing users."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.users: List[User] = []

    async def get_user(self, user_id: int) -> Optional[User]:
        """Get a user by ID.

        Args:
            user_id: The user ID to look up

        Returns:
            The user if found, None otherwise
        """
        for user in self.users:
            if user.age == user_id:  # Simplified for testing
                return user
        return None

    async def create_user(self, name: str, age: int) -> User:
        """Create a new user.

        Args:
            name: User's name
            age: User's age

        Returns:
            The created user
        """
        user = User(name=name, age=age)
        self.users.append(user)
        return user

    def _internal_helper(self) -> None:
        """Internal helper method."""
        pass


def calculate_score(value: int, multiplier: float = 1.0) -> float:
    """Calculate a score from a value.

    Args:
        value: The input value
        multiplier: Score multiplier

    Returns:
        Calculated score
    """
    return value * multiplier


async def fetch_data(url: str) -> dict:
    """Fetch data from a URL.

    Args:
        url: The URL to fetch from

    Returns:
        The fetched data
    """
    # Simplified implementation
    return {"status": "ok"}


def main():
    """Main entry point."""
    service = UserService({"timeout": DEFAULT_TIMEOUT})
    service.start()

    score = calculate_score(42, 2.0)

    service.stop()


if __name__ == "__main__":
    main()
