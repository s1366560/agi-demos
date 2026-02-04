"""
HITLRequestRepository port for Human-in-the-Loop request persistence.

Repository interface for persisting and retrieving HITL requests,
following the Repository pattern with tenant and project-level isolation.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from src.domain.model.agent.hitl_request import HITLRequest


class HITLRequestRepositoryPort(ABC):
    """
    Repository port for HITL request persistence.

    Provides CRUD operations for HITL requests (clarification, decision, env_var)
    with tenant and project-level isolation for multi-tenant support.
    """

    @abstractmethod
    async def create(self, request: HITLRequest) -> HITLRequest:
        """
        Create a new HITL request.

        Args:
            request: HITL request to create

        Returns:
            Created request with generated ID

        Raises:
            ValueError: If request data is invalid
        """
        pass

    @abstractmethod
    async def get_by_id(self, request_id: str) -> Optional[HITLRequest]:
        """
        Get an HITL request by its ID.

        Args:
            request_id: Request ID

        Returns:
            HITL request if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_by_conversation(
        self,
        conversation_id: str,
    ) -> List[HITLRequest]:
        """
        Get all HITL requests for a conversation (regardless of status).

        Args:
            conversation_id: Conversation ID

        Returns:
            List of HITL requests
        """
        pass

    @abstractmethod
    async def get_pending_by_conversation(
        self,
        conversation_id: str,
        tenant_id: str,
        project_id: str,
    ) -> List[HITLRequest]:
        """
        Get all pending HITL requests for a conversation.

        Args:
            conversation_id: Conversation ID
            tenant_id: Tenant ID for isolation
            project_id: Project ID for isolation

        Returns:
            List of pending HITL requests
        """
        pass

    @abstractmethod
    async def get_pending_by_project(
        self,
        tenant_id: str,
        project_id: str,
        limit: int = 50,
    ) -> List[HITLRequest]:
        """
        Get all pending HITL requests for a project.

        Args:
            tenant_id: Tenant ID for isolation
            project_id: Project ID for isolation
            limit: Maximum number of results

        Returns:
            List of pending HITL requests
        """
        pass

    @abstractmethod
    async def update_response(
        self,
        request_id: str,
        response: str,
        response_metadata: Optional[dict] = None,
    ) -> Optional[HITLRequest]:
        """
        Update an HITL request with a response.

        Args:
            request_id: Request ID
            response: User's response
            response_metadata: Optional additional metadata

        Returns:
            Updated request if found, None otherwise
        """
        pass

    @abstractmethod
    async def mark_timeout(
        self,
        request_id: str,
        default_response: Optional[str] = None,
    ) -> Optional[HITLRequest]:
        """
        Mark an HITL request as timed out.

        Args:
            request_id: Request ID
            default_response: Optional default response to use

        Returns:
            Updated request if found, None otherwise
        """
        pass

    @abstractmethod
    async def mark_cancelled(self, request_id: str) -> Optional[HITLRequest]:
        """
        Mark an HITL request as cancelled.

        Args:
            request_id: Request ID

        Returns:
            Updated request if found, None otherwise
        """
        pass

    @abstractmethod
    async def mark_expired_requests(self, before: datetime) -> int:
        """
        Mark all expired pending requests as timed out.

        Used by cleanup jobs to expire old requests.

        Args:
            before: Mark requests as expired if expires_at < before

        Returns:
            Number of requests marked as expired
        """
        pass

    @abstractmethod
    async def delete(self, request_id: str) -> bool:
        """
        Delete an HITL request.

        Args:
            request_id: Request ID

        Returns:
            True if deleted, False if not found
        """
        pass
