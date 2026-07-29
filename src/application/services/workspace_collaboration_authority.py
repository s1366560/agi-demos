"""Durable revision and idempotency contract for Workspace Collaboration mutations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Protocol

WORKSPACE_COLLABORATION_CONTRACT_VERSION: Final = "2.0.0"

WORKSPACE_COLLABORATION_MUTATION_ACTIONS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "goals": (
            "create_objective",
            "update_objective",
            "delete_objective",
            "project_objective_to_task",
            "create_task",
            "update_task",
            "delete_task",
            "assign_task_agent",
            "unassign_task_agent",
        ),
        "discussion": (
            "create_post",
            "update_post",
            "delete_post",
            "pin_post",
            "unpin_post",
            "create_reply",
            "update_reply",
            "delete_reply",
        ),
        "status": ("update_task", "apply_task_recovery_action"),
        "collaboration": (
            "bind_agent",
            "update_agent_binding",
            "unbind_agent",
            "add_member",
            "update_member_role",
            "remove_member",
            "create_task",
            "update_task",
            "delete_task",
            "assign_task_agent",
            "unassign_task_agent",
        ),
        "members": ("add_member", "update_member_role", "remove_member"),
        "genes": ("create_gene", "update_gene", "delete_gene"),
        "files": (
            "create_directory",
            "upload_file",
            "update_file",
            "delete_file",
            "copy_file",
        ),
        "notes": (),
        "topology": (
            "create_node",
            "update_node",
            "delete_node",
            "create_edge",
            "update_edge",
            "delete_edge",
        ),
        "settings": ("update_workspace",),
    }
)


class WorkspaceCollaborationMutationError(RuntimeError):
    """Base error for a rejected Workspace Collaboration mutation."""

    reason_code = "workspace_collaboration_mutation_rejected"


class WorkspaceCollaborationTargetNotFoundError(WorkspaceCollaborationMutationError):
    """Raised when the workspace does not exist in the command scope."""

    reason_code = "workspace_collaboration_scope_mismatch"


class WorkspaceCollaborationIdempotencyConflictError(WorkspaceCollaborationMutationError):
    """Raised when an idempotency key is reused for a different intent."""

    reason_code = "workspace_collaboration_idempotency_conflict"


class WorkspaceCollaborationRevisionConflictError(WorkspaceCollaborationMutationError):
    """Raised when the caller's expected revision is stale."""

    reason_code = "workspace_collaboration_revision_conflict"

    def __init__(self, *, expected_revision: int, current_revision: int) -> None:
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        super().__init__(
            f"Workspace Collaboration revision conflict: expected "
            f"{expected_revision}, current {current_revision}"
        )


class WorkspaceCollaborationAuthorityCorruptError(WorkspaceCollaborationMutationError):
    """Raised when persisted authority state violates the monotonic contract."""

    reason_code = "workspace_collaboration_authority_corrupt"


@dataclass(frozen=True, kw_only=True)
class WorkspaceCollaborationActor:
    """Authenticated Workspace Collaboration command scope."""

    tenant_id: str
    project_id: str
    workspace_id: str
    user_id: str


@dataclass(frozen=True, kw_only=True)
class WorkspaceCollaborationMutationCommand:
    """One versioned and replay-safe surface mutation."""

    contract_version: str
    surface: str
    action: str
    expected_revision: int
    idempotency_key: str
    payload: Mapping[str, object]


@dataclass(frozen=True, kw_only=True)
class WorkspaceCollaborationMutationReceipt:
    """Stable receipt for a reserved or committed surface mutation."""

    receipt_id: str
    workspace_id: str
    surface: str
    action: str
    expected_revision: int
    revision: int | None
    duplicate: bool
    dispatch_required: bool


class WorkspaceCollaborationAuthorityRepository(Protocol):
    """Atomic persistence boundary used by the mutation service."""

    async def current_revision(self, *, actor: WorkspaceCollaborationActor) -> int: ...

    async def reserve(
        self,
        *,
        actor: WorkspaceCollaborationActor,
        command: WorkspaceCollaborationMutationCommand,
        request_hash: str,
    ) -> WorkspaceCollaborationMutationReceipt: ...

    async def finalize(
        self,
        *,
        actor: WorkspaceCollaborationActor,
        command: WorkspaceCollaborationMutationCommand,
        request_hash: str,
        duplicate: bool,
    ) -> WorkspaceCollaborationMutationReceipt: ...


class WorkspaceCollaborationMutationService:
    """Validate and hash commands before entering the durable SQL boundary."""

    _MAX_CANONICAL_PAYLOAD_BYTES = 1024 * 1024

    def __init__(self, repository: WorkspaceCollaborationAuthorityRepository) -> None:
        self._repository = repository

    async def current_revision(self, *, actor: WorkspaceCollaborationActor) -> int:
        self._validate_actor(actor)
        return await self._repository.current_revision(actor=actor)

    async def reserve(
        self,
        *,
        actor: WorkspaceCollaborationActor,
        command: WorkspaceCollaborationMutationCommand,
    ) -> WorkspaceCollaborationMutationReceipt:
        self._validate_actor(actor)
        request_hash = self._request_hash(actor=actor, command=command)
        return await self._repository.reserve(
            actor=actor,
            command=command,
            request_hash=request_hash,
        )

    async def finalize(
        self,
        *,
        actor: WorkspaceCollaborationActor,
        command: WorkspaceCollaborationMutationCommand,
        duplicate: bool,
    ) -> WorkspaceCollaborationMutationReceipt:
        self._validate_actor(actor)
        request_hash = self._request_hash(actor=actor, command=command)
        return await self._repository.finalize(
            actor=actor,
            command=command,
            request_hash=request_hash,
            duplicate=duplicate,
        )

    @classmethod
    def _request_hash(
        cls,
        *,
        actor: WorkspaceCollaborationActor,
        command: WorkspaceCollaborationMutationCommand,
    ) -> str:
        cls._validate_command(command)
        canonical_input = {
            "contract_version": command.contract_version,
            "tenant_id": actor.tenant_id,
            "project_id": actor.project_id,
            "workspace_id": actor.workspace_id,
            "surface": command.surface,
            "action": command.action,
            "expected_revision": command.expected_revision,
            "payload": command.payload,
        }
        try:
            canonical = json.dumps(
                canonical_input,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must contain only JSON values") from exc
        if len(canonical) > cls._MAX_CANONICAL_PAYLOAD_BYTES:
            raise ValueError("payload exceeds the Workspace Collaboration command limit")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _validate_actor(actor: WorkspaceCollaborationActor) -> None:
        for field_name, value in (
            ("tenant_id", actor.tenant_id),
            ("project_id", actor.project_id),
            ("workspace_id", actor.workspace_id),
            ("user_id", actor.user_id),
        ):
            if not value.strip() or len(value) > 512:
                raise ValueError(f"{field_name} is invalid")

    @staticmethod
    def _validate_command(command: WorkspaceCollaborationMutationCommand) -> None:
        if command.contract_version != WORKSPACE_COLLABORATION_CONTRACT_VERSION:
            raise ValueError("contract_version is unsupported")
        allowed_actions = WORKSPACE_COLLABORATION_MUTATION_ACTIONS.get(command.surface)
        if allowed_actions is None or command.action not in allowed_actions:
            raise ValueError("surface action is unavailable")
        if (
            isinstance(command.expected_revision, bool)
            or not isinstance(command.expected_revision, int)
            or command.expected_revision < 0
        ):
            raise ValueError("expected_revision must be a non-negative integer")
        key = command.idempotency_key
        if (
            len(key) < 8
            or len(key) > 256
            or key != key.strip()
            or any(ord(character) < 33 or ord(character) > 126 for character in key)
        ):
            raise ValueError("idempotency_key must contain 8 to 256 visible ASCII characters")
        if not isinstance(command.payload, Mapping):
            raise ValueError("payload must be a JSON object")
