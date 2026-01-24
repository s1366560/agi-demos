"""Worker state management for Temporal Activities.

This module provides global state management for Temporal Workers,
allowing Activities to access shared services like graph_service.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Global state for worker
_graph_service: Optional[Any] = None
_queue_service: Optional[Any] = None


def set_graph_service(service: Any) -> None:
    """Set the global graph service instance.

    Called during Worker initialization to make graph_service
    available to all Activities.

    Args:
        service: The graph service (NativeGraphAdapter) instance
    """
    global _graph_service
    _graph_service = service
    logger.info("Graph service registered for Activities")


def get_graph_service() -> Optional[Any]:
    """Get the global graph service instance.

    Returns:
        The graph service instance or None if not initialized
    """
    return _graph_service


def set_queue_service(service: Any) -> None:
    """Set the global queue service instance.

    Called during Worker initialization for backward compatibility
    with TaskHandler context pattern.

    Args:
        service: The queue service instance
    """
    global _queue_service
    _queue_service = service
    logger.info("Queue service registered for Activities")


def get_queue_service() -> Optional[Any]:
    """Get the global queue service instance.

    Returns:
        The queue service instance or None if not initialized
    """
    return _queue_service


def clear_state() -> None:
    """Clear all global state.

    Called during Worker shutdown for cleanup.
    """
    global _graph_service, _queue_service
    _graph_service = None
    _queue_service = None
    logger.info("Worker state cleared")
