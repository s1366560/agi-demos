"""Durable, replay-safe command boundary for automation mutations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol


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
        message = (
            f"Automation revision conflict: expected {expected_revision}, current {current_revision}"
        )
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


class AutomationCommandRepository(Protocol):
    """Atomic persistence port for durable automation commands."""

    async def queue_manual_run(
        self,
        *,
        actor: AutomationActor,
        command: QueueManualRunCommand,
        request_hash: str,
    ) -> AutomationRunReceipt: ...


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
