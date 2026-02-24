"""
Use case for listing API keys.
"""

from typing import List

from pydantic import BaseModel, Field, field_validator

from src.domain.model.auth.api_key import APIKey
from src.domain.ports.repositories.api_key_repository import APIKeyRepository


class ListAPIKeysQuery(BaseModel):
    """Query to list API keys"""

    model_config = {"frozen": True}

    user_id: str
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)

    @field_validator("user_id")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v


class ListAPIKeysUseCase:
    """Use case for listing API keys"""

    def __init__(self, api_key_repository: APIKeyRepository):
        self._api_key_repo = api_key_repository

    async def execute(self, query: ListAPIKeysQuery) -> List[APIKey]:
        """List API keys for user"""
        return await self._api_key_repo.find_by_user(
            query.user_id, limit=query.limit, offset=query.offset
        )
