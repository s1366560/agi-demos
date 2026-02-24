"""Cancel handling for MCP requests.

This module provides utilities for handling cancellation of
in-progress MCP requests.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CancelHandler:
    """Handler for managing cancellable MCP requests.

    Tracks in-progress requests and handles cancellation notifications
    from the MCP server.
    """

    _pending_requests: dict[str, str] = field(default_factory=dict)
    """Maps request_id to server_id for tracking cancellable requests."""

    _cancelled_requests: set[str] = field(default_factory=set)
    """Set of request IDs that have been cancelled."""

    def register_request(self, request_id: str, server_id: str) -> None:
        """
        Register a request as cancellable.

        Args:
            request_id: Unique request identifier
            server_id: Server handling the request
        """
        self._pending_requests[request_id] = server_id
        logger.debug(f"Registered cancellable request: {request_id} on server {server_id}")

    def unregister_request(self, request_id: str) -> None:
        """
        Unregister a request (after completion or cancellation).

        Args:
            request_id: Unique request identifier
        """
        self._pending_requests.pop(request_id, None)
        self._cancelled_requests.discard(request_id)
        logger.debug(f"Unregistered request: {request_id}")

    def has_pending_request(self, request_id: str) -> bool:
        """
        Check if a request is pending.

        Args:
            request_id: Unique request identifier

        Returns:
            True if request is pending, False otherwise
        """
        return request_id in self._pending_requests

    def is_cancelled(self, request_id: str) -> bool:
        """
        Check if a request has been cancelled.

        Args:
            request_id: Unique request identifier

        Returns:
            True if request was cancelled, False otherwise
        """
        return request_id in self._cancelled_requests

    def get_pending_requests(self) -> list[tuple[str, str]]:
        """
        Get all pending requests.

        Returns:
            List of (request_id, server_id) tuples
        """
        return [(req_id, server_id) for req_id, server_id in self._pending_requests.items()]

    async def handle_cancel(self, request_id: str, client: Any) -> bool:
        """
        Handle a cancellation notification.

        Args:
            request_id: Request to cancel
            client: MCP client to send cancel request

        Returns:
            True if cancellation was sent, False otherwise
        """
        if request_id not in self._pending_requests:
            logger.warning(f"Cannot cancel unknown request: {request_id}")
            return False

        try:
            # Mark as cancelled before sending
            self._cancelled_requests.add(request_id)

            # Send cancel to server if client supports it
            if hasattr(client, "cancel_request"):
                await client.cancel_request(request_id)
                logger.info(f"Sent cancellation for request: {request_id}")
            else:
                logger.debug(
                    f"Client does not support cancel_request, marked as cancelled: {request_id}"
                )

            # Unregister the request after cancellation
            self.unregister_request(request_id)

            return True

        except Exception as e:
            logger.error(f"Failed to cancel request {request_id}: {e}")
            return False

    def cancel_all_for_server(self, server_id: str) -> list[str]:
        """
        Cancel all pending requests for a server.

        Args:
            server_id: Server to cancel requests for

        Returns:
            List of cancelled request IDs
        """
        cancelled = []
        for request_id, sid in list(self._pending_requests.items()):
            if sid == server_id:
                self._cancelled_requests.add(request_id)
                cancelled.append(request_id)

        logger.info(f"Cancelled {len(cancelled)} requests for server {server_id}")
        return cancelled

    def clear_all(self) -> None:
        """Clear all pending and cancelled requests."""
        self._pending_requests.clear()
        self._cancelled_requests.clear()
        logger.debug("Cleared all pending requests")
