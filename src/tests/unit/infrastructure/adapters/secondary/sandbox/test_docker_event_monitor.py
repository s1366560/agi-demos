"""Tests for Docker sandbox event monitoring."""

from unittest.mock import AsyncMock

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
