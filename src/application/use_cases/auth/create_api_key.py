"""
Use case for deleting API keys.
"""

from pydantic import BaseModel, field_validator

from src.domain.ports.repositories.api_key_repository import APIKeyRepository


class DeleteAPIKeyCommand(BaseModel):
    """Command to delete an API key"""

    model_config = {"frozen": True}

    key_id: str
    user_id: str  # For authorization

    @field_validator("key_id", "user_id")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v


class DeleteAPIKeyUseCase:
    """Use case for deleting API keys"""

    def __init__(self, api_key_repository: APIKeyRepository) -> None:
        self._api_key_repo = api_key_repository

    async def execute(self, command: DeleteAPIKeyCommand) -> bool:
        """Delete API key - returns True if deleted"""
        # Implementation would be in the execute method

        # Get the key
        api_key = await self._api_key_repo.find_by_id(command.key_id)

        if not api_key:
            return False

        # Authorization check
        if api_key.user_id != command.user_id:
            return False

        await self._api_key_repo.delete(command.key_id)
        return True
