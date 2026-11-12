"""Tests for Docker sandbox event monitoring."""

from unittest.mock import AsyncMock, Mock

import pytest

from src.infrastructure.adapters.secondary.sandbox.docker_event_monitor import (
    CONTAINER_EVENTS,
    DockerEventMonitor,
)


@pytest.mark.unit
def test_oom_event_does_not_emit_error_status() -> None:
    """An OOM notification alone is not proof the sandbox container stopped."""
    assert "oom" not in CONTAINER_EVENTS

    on_status_change = AsyncMock()
    monitor = DockerEventMonitor(on_status_change=on_status_change)

    monitor._handle_event(
        {
            "Action": "oom",
            "Actor": {
                "ID": "dec5f284ab42",
                "Attributes": {
                    "memstack.sandbox": "true",
                    "memstack.project_id": "project-1",
                    "name": "mcp-sandbox-dec5f284ab42",
                },
            },
        }
    )

    on_status_change.assert_not_called()


@pytest.mark.unit
async def test_stop_closes_the_docker_client_the_monitor_owns() -> None:
    monitor = DockerEventMonitor()
    client = Mock()
    monitor._docker = client
    monitor._owns_docker = True
    monitor._running = True

    await monitor.stop()

    client.close.assert_called_once()
    assert monitor._docker is None
