"""
Use case for creating API keys.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from pydantic import BaseModel, field_validator

from src.domain.model.auth.api_key import APIKey
from src.domain.ports.repositories.api_key_repository import APIKeyRepository


class CreateAPIKeyCommand(BaseModel):
    """Command to create an API key"""

    model_config = {"frozen": True}

    user_id: str
    name: str
    permissions: List[str]
    expires_in_days: Optional[int] = None

    @field_validator("user_id", "name")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v

    @field_validator("expires_in_days")
    @classmethod
    def must_be_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v <= 0:
            raise ValueError("must be positive")
        return v


class CreateAPIKeyUseCase:
    """Use case for creating API keys"""

    def __init__(
        self,
        api_key_repository: APIKeyRepository,
        generate_key_func,
        hash_key_func,
    ):
        self._api_key_repo = api_key_repository
        self._generate_key = generate_key_func
        self._hash_key = hash_key_func

    async def execute(self, command: CreateAPIKeyCommand) -> tuple[str, APIKey]:
        """Create API key - returns (plain_key, api_key)"""
        plain_key = self._generate_key()
        hashed_key = self._hash_key(plain_key)

        expires_at = None
        if command.expires_in_days:
            expires_at = datetime.now(timezone.utc) + timedelta(days=command.expires_in_days)

        api_key = APIKey(
            user_id=command.user_id,
            key_hash=hashed_key,
            name=command.name,
            permissions=command.permissions,
            expires_at=expires_at,
        )

        await self._api_key_repo.save(api_key)
        return plain_key, api_key
