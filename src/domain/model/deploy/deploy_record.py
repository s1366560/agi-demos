"""DeployRecord domain entity."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.shared_kernel import Entity

from .enums import DeployAction, DeployStatus


@dataclass(kw_only=True)
class DeployRecord(Entity):
    """Represents a single deployment operation against an instance.

    Attributes:
        instance_id: ID of the target instance being deployed.
        revision: Monotonically increasing revision number.
        action: The deployment action performed.
        image_version: Container image version used in this deploy.
        replicas: Desired replica count (for scale actions).
        config_snapshot: JSON snapshot of configuration at deploy time.
        status: Current lifecycle status of the deployment.
        message: Status message or error details.
        triggered_by: User ID of the person who triggered the deploy.
        started_at: Timestamp when execution started.
        finished_at: Timestamp when execution finished.
        created_at: Record creation timestamp.
        deleted_at: Soft-delete timestamp.
    """

    instance_id: str
    revision: int = 0
    action: DeployAction = DeployAction.create
    image_version: str | None = None
    replicas: int | None = None
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    status: DeployStatus = DeployStatus.pending
    message: str | None = None
    triggered_by: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.instance_id:
            raise ValueError("instance_id cannot be empty")

    def is_terminal(self) -> bool:
        """Return True if the deploy has reached a terminal status."""
        return self.status in (
            DeployStatus.success,
            DeployStatus.failed,
            DeployStatus.cancelled,
        )

    def mark_success(self, message: str | None = None) -> None:
        """Transition the deploy to success."""
        self.status = DeployStatus.success
        self.finished_at = datetime.now(UTC)
        self.message = message

    def mark_failed(self, message: str) -> None:
        """Transition the deploy to failed with an error message."""
        self.status = DeployStatus.failed
        self.finished_at = datetime.now(UTC)
        self.message = message

    def mark_cancelled(self) -> None:
        """Transition the deploy to cancelled."""
        self.status = DeployStatus.cancelled
        self.finished_at = datetime.now(UTC)

    def soft_delete(self) -> None:
        """Mark this record as soft-deleted."""
        self.deleted_at = datetime.now(UTC)
