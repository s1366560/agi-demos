from abc import ABC, abstractmethod

from src.domain.model.workspace.blackboard_post import BlackboardPost
from src.domain.model.workspace.blackboard_reply import BlackboardReply


class BlackboardRepository(ABC):
    """Repository interface for blackboard posts and replies."""

    @abstractmethod
    async def save_post(self, post: BlackboardPost) -> BlackboardPost:
        """Save a blackboard post (create or update)."""

    @abstractmethod
    async def find_post_by_id(self, post_id: str) -> BlackboardPost | None:
        """Find blackboard post by ID."""

    @abstractmethod
    async def list_posts_by_workspace(
        self,
        workspace_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BlackboardPost]:
        """List blackboard posts for a workspace."""

    @abstractmethod
    async def save_reply(self, reply: BlackboardReply) -> BlackboardReply:
        """Save a blackboard reply (create or update)."""

    @abstractmethod
    async def list_replies_by_post(
        self,
        post_id: str,
        limit: int = 200,
        offset: int = 0,
    ) -> list[BlackboardReply]:
        """List replies under a blackboard post."""

    @abstractmethod
    async def delete_post(self, post_id: str) -> bool:
        """Delete blackboard post by ID."""

    @abstractmethod
    async def delete_reply(self, reply_id: str) -> bool:
        """Delete blackboard reply by ID."""
