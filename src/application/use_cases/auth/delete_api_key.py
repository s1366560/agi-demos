"""
Use case for listing API keys.
"""

from dataclasses import dataclass
from typing import List

from src.domain.model.auth.api_key import APIKey
from src.domain.ports.repositories.api_key_repository import APIKeyRepository


@dataclass
class ListAPIKeysQuery:
    """Query to list API keys"""

    user_id: str
    limit: int = 50
    offset: int = 0


class ListAPIKeysUseCase:
    """Use case for listing API keys"""

    def __init__(self, api_key_repository: APIKeyRepository):
        self._api_key_repo = api_key_repository

    async def execute(self, query: ListAPIKeysQuery) -> List[APIKey]:
        """List API keys for user"""
        return await self._api_key_repo.find_by_user(
            query.user_id, limit=query.limit, offset=query.offset
        )
