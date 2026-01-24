"""Unit tests for Temporal worker state management."""

import pytest

from src.infrastructure.adapters.secondary.temporal.worker_state import (
    clear_state,
    get_graph_service,
    get_queue_service,
    set_graph_service,
    set_queue_service,
)


@pytest.mark.unit
class TestWorkerState:
    """Test cases for worker state management."""

    def setup_method(self):
        """Clear state before each test."""
        clear_state()

    def teardown_method(self):
        """Clear state after each test."""
        clear_state()

    def test_set_and_get_graph_service(self):
        """Test setting and getting graph service."""
        # Arrange
        mock_service = object()

        # Act
        set_graph_service(mock_service)
        result = get_graph_service()

        # Assert
        assert result is mock_service

    def test_get_graph_service_when_not_set(self):
        """Test getting graph service when not initialized."""
        # Act
        result = get_graph_service()

        # Assert
        assert result is None

    def test_set_and_get_queue_service(self):
        """Test setting and getting queue service."""
        # Arrange
        mock_service = object()

        # Act
        set_queue_service(mock_service)
        result = get_queue_service()

        # Assert
        assert result is mock_service

    def test_get_queue_service_when_not_set(self):
        """Test getting queue service when not initialized."""
        # Act
        result = get_queue_service()

        # Assert
        assert result is None

    def test_clear_state(self):
        """Test clearing all state."""
        # Arrange
        set_graph_service(object())
        set_queue_service(object())

        # Act
        clear_state()

        # Assert
        assert get_graph_service() is None
        assert get_queue_service() is None

    def test_overwrite_graph_service(self):
        """Test overwriting graph service with new instance."""
        # Arrange
        old_service = object()
        new_service = object()
        set_graph_service(old_service)

        # Act
        set_graph_service(new_service)
        result = get_graph_service()

        # Assert
        assert result is new_service
        assert result is not old_service

    def test_multiple_services_independent(self):
        """Test that graph and queue services are independent."""
        # Arrange
        graph_service = object()
        queue_service = object()

        # Act
        set_graph_service(graph_service)
        set_queue_service(queue_service)

        # Assert
        assert get_graph_service() is graph_service
        assert get_queue_service() is queue_service
        assert get_graph_service() is not get_queue_service()
