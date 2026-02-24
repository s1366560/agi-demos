"""
HITL Service Port - Domain port for Human-in-the-Loop interactions.

This port defines the contract for HITL operations, abstracting away the
underlying implementation (Redis Streams, Ray Actors, etc.).

Architecture:
    - Domain layer defines this port
    - Application layer uses this port for HITL operations
    - Infrastructure layer implements this port (Ray/Redis adapter)
"""

from abc import ABC, abstractmethod
from typing import Any

from src.domain.model.agent.hitl_types import (
    HITLRequest,
    HITLResponse,
)


class HITLServicePort(ABC):
    """
    Port for HITL service operations.

    This port provides a unified interface for all HITL interactions,
    hiding the complexity of cross-process communication and state management.

    Implementation Requirements:
    - Thread-safe and async-safe
    - Handles timeout and cancellation gracefully
    - Supports recovery after process restart
    - Emits SSE events for frontend updates
    """

    # =========================================================================
    # Request Creation
    # =========================================================================

    @abstractmethod
    async def create_request(
        self,
        request: HITLRequest,
    ) -> str:
        """
        Create a new HITL request and emit SSE event.

        This method:
        1. Persists the request (for recovery)
        2. Emits SSE event to frontend
        3. Returns immediately (does not wait for response)

        Args:
            request: The HITL request to create

        Returns:
            request_id for tracking

        Raises:
            HITLServiceError: If request creation fails
        """
        pass

    # =========================================================================
    # Response Handling
    # =========================================================================

    @abstractmethod
    async def submit_response(
        self,
        response: HITLResponse,
    ) -> bool:
        """
        Submit a user response to an HITL request.

        This method:
        1. Validates the response
        2. Routes response to the active agent runtime
        3. Emits SSE event for frontend

        Args:
            response: The user's response

        Returns:
            True if response was accepted

        Raises:
            HITLRequestNotFoundError: If request doesn't exist
            HITLRequestExpiredError: If request has expired
            HITLServiceError: If response submission fails
        """
        pass

    @abstractmethod
    async def wait_for_response(
        self,
        request_id: str,
        timeout_seconds: float | None = None,
    ) -> HITLResponse:
        """
        Wait for user response to an HITL request.

        This method blocks until:
        - User provides a response
        - Request times out
        - Request is cancelled

        Args:
            request_id: The request to wait for
            timeout_seconds: Override default timeout

        Returns:
            The user's response

        Raises:
            HITLTimeoutError: If request times out
            HITLCancelledError: If request is cancelled
            HITLRequestNotFoundError: If request doesn't exist
        """
        pass

    # =========================================================================
    # Request Management
    # =========================================================================

    @abstractmethod
    async def get_pending_requests(
        self,
        conversation_id: str,
    ) -> list[HITLRequest]:
        """
        Get all pending HITL requests for a conversation.

        Used for recovery after page refresh.

        Args:
            conversation_id: The conversation ID

        Returns:
            List of pending requests
        """
        pass

    @abstractmethod
    async def get_request(
        self,
        request_id: str,
    ) -> HITLRequest | None:
        """
        Get an HITL request by ID.

        Args:
            request_id: The request ID

        Returns:
            The request, or None if not found
        """
        pass

    @abstractmethod
    async def cancel_request(
        self,
        request_id: str,
        reason: str | None = None,
    ) -> bool:
        """
        Cancel a pending HITL request.

        Args:
            request_id: The request to cancel
            reason: Optional cancellation reason

        Returns:
            True if request was cancelled
        """
        pass

    # =========================================================================
    # Convenience Methods (with default implementations)
    # =========================================================================

    async def create_and_wait(
        self,
        request: HITLRequest,
    ) -> Any:
        """
        Create request and wait for response in one call.

        This is the most common pattern for HITL interactions.

        Args:
            request: The HITL request

        Returns:
            The response value (type depends on HITL type)
        """
        await self.create_request(request)
        response = await self.wait_for_response(
            request.request_id,
            timeout_seconds=request.timeout_seconds,
        )
        return response.response_value

    async def get_pending_count(
        self,
        conversation_id: str,
    ) -> int:
        """Get count of pending requests for a conversation."""
        requests = await self.get_pending_requests(conversation_id)
        return len(requests)


# =============================================================================
# Exceptions
# =============================================================================


class HITLServiceError(Exception):
    """Base exception for HITL service errors."""

    pass


class HITLRequestNotFoundError(HITLServiceError):
    """Raised when HITL request is not found."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        super().__init__(f"HITL request not found: {request_id}")


class HITLRequestExpiredError(HITLServiceError):
    """Raised when HITL request has expired."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        super().__init__(f"HITL request has expired: {request_id}")


class HITLTimeoutError(HITLServiceError):
    """Raised when HITL request times out."""

    def __init__(self, request_id: str, timeout_seconds: float) -> None:
        self.request_id = request_id
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"HITL request timed out after {timeout_seconds}s: {request_id}"
        )


class HITLCancelledError(HITLServiceError):
    """Raised when HITL request is cancelled."""

    def __init__(self, request_id: str, reason: str | None = None) -> None:
        self.request_id = request_id
        self.reason = reason
        msg = f"HITL request cancelled: {request_id}"
        if reason:
            msg += f" - {reason}"
        super().__init__(msg)


class HITLValidationError(HITLServiceError):
    """Raised when HITL request/response validation fails."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        self.details = details or {}
        super().__init__(message)
