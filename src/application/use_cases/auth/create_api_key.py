"""
Use case for deleting API keys.
"""

from dataclasses import dataclass

from src.domain.ports.repositories.api_key_repository import APIKeyRepository


@dataclass
class DeleteAPIKeyCommand:
    """Command to delete an API key"""

    key_id: str
    user_id: str  # For authorization


class DeleteAPIKeyUseCase:
    """Use case for deleting API keys"""

    def __init__(self, api_key_repository: APIKeyRepository):
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
