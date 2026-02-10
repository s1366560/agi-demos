"""Tests for ProjectSandbox domain model."""

from datetime import datetime, timedelta, timezone

import pytest

from src.domain.model.sandbox.project_sandbox import (
    ProjectSandbox,
    ProjectSandboxStatus,
)


class TestProjectSandbox:
    """Tests for ProjectSandbox entity."""

    def test_create_default(self) -> None:
        """Should create with default values."""
        sandbox = ProjectSandbox(
            id="test-id",
            project_id="proj-123",
            tenant_id="tenant-456",
            sandbox_id="sb-789",
        )

        assert sandbox.status == ProjectSandboxStatus.STARTING
        assert sandbox.created_at is not None
        assert sandbox.last_accessed_at is not None
        assert sandbox.metadata == {}
        assert sandbox.error_message is None

    def test_mark_accessed(self) -> None:
        """Should update last_accessed_at timestamp."""
        sandbox = ProjectSandbox(
            id="test-id",
            project_id="proj-123",
            tenant_id="tenant-456",
            sandbox_id="sb-789",
            last_accessed_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        old_time = sandbox.last_accessed_at
        sandbox.mark_accessed()

        assert sandbox.last_accessed_at > old_time

    def test_mark_healthy(self) -> None:
        """Should mark as healthy."""
        sandbox = ProjectSandbox(
            id="test-id",
            project_id="proj-123",
            tenant_id="tenant-456",
            sandbox_id="sb-789",
            status=ProjectSandboxStatus.UNHEALTHY,
            error_message="Previous error",
        )

        sandbox.mark_healthy()

        assert sandbox.status == ProjectSandboxStatus.RUNNING
        assert sandbox.health_checked_at is not None
        assert sandbox.error_message is None

    def test_mark_unhealthy(self) -> None:
        """Should mark as unhealthy with reason."""
        sandbox = ProjectSandbox(
            id="test-id",
            project_id="proj-123",
            tenant_id="tenant-456",
            sandbox_id="sb-789",
            status=ProjectSandboxStatus.RUNNING,
        )

        sandbox.mark_unhealthy(reason="Connection timeout")

        assert sandbox.status == ProjectSandboxStatus.ERROR
        assert sandbox.error_message == "Connection timeout"

    def test_mark_error(self) -> None:
        """Should mark as error."""
        sandbox = ProjectSandbox(
            id="test-id",
            project_id="proj-123",
            tenant_id="tenant-456",
            sandbox_id="sb-789",
            status=ProjectSandboxStatus.CREATING,
        )

        sandbox.mark_error("Failed to start container")

        assert sandbox.status == ProjectSandboxStatus.ERROR
        assert sandbox.error_message == "Failed to start container"

    def test_mark_stopped(self) -> None:
        """Should mark as stopped."""
        sandbox = ProjectSandbox(
            id="test-id",
            project_id="proj-123",
            tenant_id="tenant-456",
            sandbox_id="sb-789",
            status=ProjectSandboxStatus.RUNNING,
        )

        sandbox.mark_stopped()

        assert sandbox.status == ProjectSandboxStatus.TERMINATED

    def test_mark_terminated(self) -> None:
        """Should mark as terminated."""
        sandbox = ProjectSandbox(
            id="test-id",
            project_id="proj-123",
            tenant_id="tenant-456",
            sandbox_id="sb-789",
            status=ProjectSandboxStatus.RUNNING,
        )

        sandbox.mark_terminated()

        assert sandbox.status == ProjectSandboxStatus.TERMINATED

    def test_is_active_running(self) -> None:
        """Should return True for active statuses."""
        running = ProjectSandbox(
            id="test-id",
            project_id="proj-123",
            tenant_id="tenant-456",
            sandbox_id="sb-789",
            status=ProjectSandboxStatus.RUNNING,
        )
        creating = ProjectSandbox(
            id="test-id",
            project_id="proj-123",
            tenant_id="tenant-456",
            sandbox_id="sb-789",
            status=ProjectSandboxStatus.CREATING,
        )

        assert running.is_active() is True
        assert creating.is_active() is True

    def test_is_active_inactive(self) -> None:
        """Should return False for inactive statuses."""
        stopped = ProjectSandbox(
            id="test-id",
            project_id="proj-123",
            tenant_id="tenant-456",
            sandbox_id="sb-789",
            status=ProjectSandboxStatus.STOPPED,
        )
        terminated = ProjectSandbox(
            id="test-id",
            project_id="proj-123",
            tenant_id="tenant-456",
            sandbox_id="sb-789",
            status=ProjectSandboxStatus.TERMINATED,
        )

        assert stopped.is_active() is False
        assert terminated.is_active() is False

    def test_is_usable_running(self) -> None:
        """Should return True only for RUNNING status."""
        running = ProjectSandbox(
            id="test-id",
            project_id="proj-123",
            tenant_id="tenant-456",
            sandbox_id="sb-789",
            status=ProjectSandboxStatus.RUNNING,
        )
        creating = ProjectSandbox(
            id="test-id",
            project_id="proj-123",
            tenant_id="tenant-456",
            sandbox_id="sb-789",
            status=ProjectSandboxStatus.CREATING,
        )
        unhealthy = ProjectSandbox(
            id="test-id",
            project_id="proj-123",
            tenant_id="tenant-456",
            sandbox_id="sb-789",
            status=ProjectSandboxStatus.UNHEALTHY,
        )

        assert running.is_usable() is True
        assert creating.is_usable() is False
        assert unhealthy.is_usable() is False

    def test_needs_health_check_no_previous_check(self) -> None:
        """Should return True if never checked."""
        sandbox = ProjectSandbox(
            id="test-id",
            project_id="proj-123",
            tenant_id="tenant-456",
            sandbox_id="sb-789",
            health_checked_at=None,
        )

        assert sandbox.needs_health_check(max_age_seconds=60) is True

    def test_needs_health_check_stale(self) -> None:
        """Should return True if check is stale."""
        sandbox = ProjectSandbox(
            id="test-id",
            project_id="proj-123",
            tenant_id="tenant-456",
            sandbox_id="sb-789",
            health_checked_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )

        assert sandbox.needs_health_check(max_age_seconds=60) is True

    def test_needs_health_check_fresh(self) -> None:
        """Should return False if check is fresh."""
        sandbox = ProjectSandbox(
            id="test-id",
            project_id="proj-123",
            tenant_id="tenant-456",
            sandbox_id="sb-789",
            health_checked_at=datetime.now(timezone.utc) - timedelta(seconds=30),
        )

        assert sandbox.needs_health_check(max_age_seconds=60) is False

    def test_to_dict(self) -> None:
        """Should convert to dictionary."""
        now = datetime.now(timezone.utc)
        sandbox = ProjectSandbox(
            id="test-id",
            project_id="proj-123",
            tenant_id="tenant-456",
            sandbox_id="sb-789",
            status=ProjectSandboxStatus.RUNNING,
            created_at=now,
            started_at=now,
            last_accessed_at=now,
            health_checked_at=now,
            error_message=None,
            metadata={"key": "value"},
        )

        data = sandbox.to_dict()

        assert data["id"] == "test-id"
        assert data["project_id"] == "proj-123"
        assert data["tenant_id"] == "tenant-456"
        assert data["sandbox_id"] == "sb-789"
        assert data["status"] == "running"
        assert data["created_at"] == now.isoformat()
        assert data["metadata"] == {"key": "value"}


class TestProjectSandboxStatus:
    """Tests for ProjectSandboxStatus enum."""

    def test_status_values(self) -> None:
        """Should have correct status values."""
        assert ProjectSandboxStatus.PENDING.value == "pending"
        assert ProjectSandboxStatus.CREATING.value == "creating"
        assert ProjectSandboxStatus.RUNNING.value == "running"
        assert ProjectSandboxStatus.UNHEALTHY.value == "unhealthy"
        assert ProjectSandboxStatus.STOPPED.value == "stopped"
        assert ProjectSandboxStatus.TERMINATED.value == "terminated"
        assert ProjectSandboxStatus.ERROR.value == "error"

    def test_from_value(self) -> None:
        """Should create enum from value."""
        status = ProjectSandboxStatus("running")
        assert status == ProjectSandboxStatus.RUNNING

    def test_invalid_value_raises(self) -> None:
        """Should raise ValueError for invalid status."""
        with pytest.raises(ValueError):
            ProjectSandboxStatus("invalid_status")
