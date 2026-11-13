"""Durable, replay-safe command boundary for automation mutations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from src.domain.model.cron.value_objects import (
    ConversationMode,
    CronDelivery,
    CronPayload,
    CronSchedule,
)


class AutomationCommandError(RuntimeError):
    """Base error for a rejected durable automation command."""


class AutomationCommandTargetNotFoundError(AutomationCommandError):
    """Raised when the scoped automation target does not exist."""


class AutomationCommandIdempotencyConflictError(AutomationCommandError):
    """Raised when one idempotency key is reused for a different intent."""


class AutomationCommandRevisionConflictError(AutomationCommandError):
    """Raised when the caller's expected revision is stale."""

    def __init__(self, *, expected_revision: int, current_revision: int) -> None:
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        message = f"Automation revision conflict: expected {expected_revision}, current {current_revision}"
        super().__init__(message)


@dataclass(frozen=True, kw_only=True)
class AutomationActor:
    """Trusted command authority derived from the authenticated request."""

    tenant_id: str
    project_id: str
    user_id: str
    api_key_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class QueueManualRunCommand:
    """One explicit request to queue a manual execution."""

    job_id: str
    expected_revision: int
    idempotency_key: str
    conversation_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class AutomationRunReceipt:
    """Stable receipt returned for an accepted or replayed run command."""

    receipt_id: str
    operation_id: str
    run_id: str
    runtime_execution_id: str
    job_id: str
    job_revision: int
    status: str
    duplicate: bool


@dataclass(frozen=True, kw_only=True)
class CreateAutomationJobCommand:
    """One explicit request to persist a cron job without starting it."""

    idempotency_key: str
    name: str
    schedule: CronSchedule
    payload: CronPayload
    description: str | None = None
    enabled: bool = True
    delete_after_run: bool = False
    delivery: CronDelivery | None = None
    conversation_mode: ConversationMode = ConversationMode.REUSE
    conversation_id: str | None = None
    timezone: str = "UTC"
    stagger_seconds: int = 0
    timeout_seconds: int = 300
    max_retries: int = 3


@dataclass(frozen=True, kw_only=True)
class UpdateAutomationJobCommand:
    """Revision-guarded partial update of one project-scoped job."""

    job_id: str
    expected_revision: int
    idempotency_key: str
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    schedule: CronSchedule | None = None
    payload: CronPayload | None = None


@dataclass(frozen=True, kw_only=True)
class DeleteAutomationJobCommand:
    """Revision-guarded deletion of one project-scoped job."""

    job_id: str
    expected_revision: int
    idempotency_key: str


@dataclass(frozen=True, kw_only=True)
class AutomationJobReceipt:
    """Stable receipt for a persisted or replayed job."""

    receipt_id: str
    operation_id: str
    job_id: str
    job_revision: int
    duplicate: bool


class AutomationCommandRepository(Protocol):
    """Atomic persistence port for durable automation commands."""

    async def queue_manual_run(
        self,
        *,
        actor: AutomationActor,
        command: QueueManualRunCommand,
        request_hash: str,
    ) -> AutomationRunReceipt: ...

    async def create_job(
        self,
        *,
        actor: AutomationActor,
        command: CreateAutomationJobCommand,
        request_hash: str,
    ) -> AutomationJobReceipt: ...

    async def update_job(
        self,
        *,
        actor: AutomationActor,
        command: UpdateAutomationJobCommand,
        request_hash: str,
    ) -> AutomationJobReceipt: ...

    async def delete_job(
        self,
        *,
        actor: AutomationActor,
        command: DeleteAutomationJobCommand,
        request_hash: str,
    ) -> AutomationJobReceipt: ...


class AutomationCommandService:
    """Canonical command service shared by HTTP and Agent adapters."""

    _SCHEMA_VERSION = 1

    def __init__(self, repository: AutomationCommandRepository) -> None:
        super().__init__()
        self._repository = repository

    async def queue_manual_run(
        self,
        *,
        actor: AutomationActor,
        command: QueueManualRunCommand,
    ) -> AutomationRunReceipt:
        """Queue one manual run using revision and idempotency guards."""
        self._validate_actor(actor)
        self._validate_manual_run(command)
        request_hash = self._manual_run_hash(actor=actor, command=command)
        return await self._repository.queue_manual_run(
            actor=actor,
            command=command,
            request_hash=request_hash,
        )

    async def create_job(
        self,
        *,
        actor: AutomationActor,
        command: CreateAutomationJobCommand,
    ) -> AutomationJobReceipt:
        """Persist one job using the caller's project scope and idempotency key."""
        self._validate_actor(actor)
        self._validate_create(command)
        request_hash = self._create_hash(actor=actor, command=command)
        return await self._repository.create_job(
            actor=actor,
            command=command,
            request_hash=request_hash,
        )

    async def update_job(
        self,
        *,
        actor: AutomationActor,
        command: UpdateAutomationJobCommand,
    ) -> AutomationJobReceipt:
        """Apply one partial update without writing a second revision on replay."""
        self._validate_actor(actor)
        self._validate_revision_command(
            command.job_id, command.expected_revision, command.idempotency_key
        )
        if (
            command.name is None
            and command.description is None
            and command.enabled is None
            and command.schedule is None
            and command.payload is None
        ):
            raise ValueError("update has no fields")
        if command.name is not None and not command.name.strip():
            raise ValueError("name is required")
        request_hash = self._revision_hash(
            actor=actor,
            operation="update_job",
            job_id=command.job_id,
            expected_revision=command.expected_revision,
            body={
                "name": command.name,
                "description": command.description,
                "enabled": command.enabled,
                "schedule": command.schedule.to_dict() if command.schedule else None,
                "payload": command.payload.to_dict() if command.payload else None,
            },
        )
        return await self._repository.update_job(
            actor=actor,
            command=command,
            request_hash=request_hash,
        )

    async def delete_job(
        self,
        *,
        actor: AutomationActor,
        command: DeleteAutomationJobCommand,
    ) -> AutomationJobReceipt:
        """Delete one job once. Replaying the same key does not delete another job."""
        self._validate_actor(actor)
        self._validate_revision_command(
            command.job_id, command.expected_revision, command.idempotency_key
        )
        request_hash = self._revision_hash(
            actor=actor,
            operation="delete_job",
            job_id=command.job_id,
            expected_revision=command.expected_revision,
            body={},
        )
        return await self._repository.delete_job(
            actor=actor,
            command=command,
            request_hash=request_hash,
        )

    @classmethod
    def _manual_run_hash(
        cls,
        *,
        actor: AutomationActor,
        command: QueueManualRunCommand,
    ) -> str:
        payload = {
            "schema_version": cls._SCHEMA_VERSION,
            "operation": "run_now",
            "tenant_id": actor.tenant_id,
            "project_id": actor.project_id,
            "job_id": command.job_id,
            "expected_revision": command.expected_revision,
            "conversation_id": command.conversation_id,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def _create_hash(
        cls,
        *,
        actor: AutomationActor,
        command: CreateAutomationJobCommand,
    ) -> str:
        delivery = command.delivery or CronDelivery.none()
        payload = {
            "schema_version": cls._SCHEMA_VERSION,
            "operation": "create_job",
            "tenant_id": actor.tenant_id,
            "project_id": actor.project_id,
            "name": command.name,
            "description": command.description,
            "enabled": command.enabled,
            "delete_after_run": command.delete_after_run,
            "schedule": command.schedule.to_dict(),
            "payload": command.payload.to_dict(),
            "delivery": delivery.to_dict(),
            "conversation_mode": command.conversation_mode.value,
            "conversation_id": command.conversation_id,
            "timezone": command.timezone,
            "stagger_seconds": command.stagger_seconds,
            "timeout_seconds": command.timeout_seconds,
            "max_retries": command.max_retries,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_actor(actor: AutomationActor) -> None:
        for field_name, value in (
            ("tenant_id", actor.tenant_id),
            ("project_id", actor.project_id),
            ("user_id", actor.user_id),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} is required")

    @staticmethod
    def _validate_manual_run(command: QueueManualRunCommand) -> None:
        if not command.job_id.strip():
            raise ValueError("job_id is required")
        if command.expected_revision < 1:
            raise ValueError("expected_revision must be positive")
        key = command.idempotency_key
        if (
            not key
            or len(key) > 255
            or any(ord(character) < 33 or ord(character) > 126 for character in key)
        ):
            raise ValueError("idempotency_key must contain 1 to 255 visible ASCII characters")
        if command.conversation_id is not None and not command.conversation_id.strip():
            raise ValueError("conversation_id cannot be blank")

    @classmethod
    def _revision_hash(
        cls,
        *,
        actor: AutomationActor,
        operation: str,
        job_id: str,
        expected_revision: int,
        body: dict[str, object],
    ) -> str:
        payload = {
            "schema_version": cls._SCHEMA_VERSION,
            "operation": operation,
            "tenant_id": actor.tenant_id,
            "project_id": actor.project_id,
            "job_id": job_id,
            "expected_revision": expected_revision,
            "body": body,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_revision_command(
        job_id: str, expected_revision: int, idempotency_key: str
    ) -> None:
        if not job_id.strip():
            raise ValueError("job_id is required")
        if expected_revision < 1:
            raise ValueError("expected_revision must be positive")
        if (
            not idempotency_key
            or len(idempotency_key) > 255
            or any(ord(character) < 33 or ord(character) > 126 for character in idempotency_key)
        ):
            raise ValueError("idempotency_key must contain 1 to 255 visible ASCII characters")

    @staticmethod
    def _validate_create(command: CreateAutomationJobCommand) -> None:
        key = command.idempotency_key
        if (
            not key
            or len(key) > 255
            or any(ord(character) < 33 or ord(character) > 126 for character in key)
        ):
            raise ValueError("idempotency_key must contain 1 to 255 visible ASCII characters")
        if not command.name.strip():
            raise ValueError("name is required")
        if command.timeout_seconds < 1 or command.max_retries < 0 or command.stagger_seconds < 0:
            raise ValueError("execution limits are invalid")
        if command.conversation_id is not None and not command.conversation_id.strip():
            raise ValueError("conversation_id cannot be blank")
