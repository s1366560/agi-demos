"""Fresh canonical chat authorization and invocation-scoped human approval."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.approved_run_tool_permission_v2 import (
    _MUTATION,
    _READ,
    _identity,
    _read_run,
)
from src.application.services.chat_permission_admission_v2 import (
    PERMISSION_PROFILES,
    load_chat_permission_policy,
    require_chat_permission_mode,
)
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import Conversation
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_METADATA_SERVICE_V2,
    current_operation_context_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error

_SERVICE = "service:operation.chat-run-tool-permission"


@dataclass
class _InvocationApproval:
    identity: tuple[OperationContextV2, str, str, str]
    consumed: bool = False


_approval: ContextVar[_InvocationApproval | None] = ContextVar(
    "chat_tool_single_invocation_approval", default=None
)
Decision = Literal["allow", "deny", "ask"]


def _denied() -> RuntimeV2Error:
    return RuntimeV2Error(
        "chat_tool_permission_denied", "Chat run does not authorize this operation"
    )


def _arguments(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, sort_keys=True, ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True)
class ChatRunToolPermissionV2:
    operation: OperationContextV2
    run_id: str
    identity: tuple[str, str, str, str]
    mode: str
    sessions: async_sessionmaker[AsyncSession]
    child_run_id: str | None = None

    async def decision(
        self, permission: str | None, tool_name: str, arguments: dict[str, Any]
    ) -> Decision:
        operation = current_operation_context_v2()
        if operation is not self.operation or _identity(operation) != self.identity:
            raise _denied()
        row = await _read_run(self.sessions, self.run_id, self.identity, self.child_run_id)
        snapshot = row.authorization_snapshot
        if (
            row.run_kind != "chat"
            or snapshot.get("schema_version") != 1
            or snapshot.get("source") != "chat_admission"
            or snapshot.get("effective_permission_mode") != self.mode
            or snapshot.get("permission_profile") != row.permission_profile
            or row.permission_profile != PERMISSION_PROFILES.get(self.mode)
            or snapshot.get("cancellation_receipt")
        ):
            raise _denied()
        async with self.sessions() as db:
            conversation = await db.get(Conversation, self.identity[2])
            if conversation is None or conversation.workspace_id != snapshot.get("workspace_id"):
                raise _denied()
            policy = await load_chat_permission_policy(conversation)
        # A resumed invocation never inherits an obsolete, broader policy. ASK
        # remains an interactive mode, not the plan API's permanent read-only profile.
        _ = require_chat_permission_mode(policy, self.mode)
        from src.application.services.peer_chat_permission_validation_v2 import (
            require_peer_sender_permission_v2,
        )

        await require_peer_sender_permission_v2(row, permission, self.identity, self.sessions)
        latest = await _read_run(self.sessions, self.run_id, self.identity, self.child_run_id)
        if (
            latest.authorization_snapshot != snapshot
            or latest.permission_profile != row.permission_profile
        ):
            raise _denied()
        if permission in _READ:
            return "allow"
        if permission not in _MUTATION:
            return "deny"
        if self.mode == "full_access":
            return "allow"
        if self.mode == "automatic":
            # This category is emitted only by the formal workspace tool's
            # argument-aware resolver after binding to its authorized scope.
            return (
                "allow"
                if permission in {"workspace_task_write", "workspace_file_write"}
                else "deny"
            )
        approved = _approval.get()
        if (
            approved is not None
            and not approved.consumed
            and approved.identity
            == (
                operation,
                self.run_id,
                tool_name,
                _arguments(arguments),
            )
        ):
            return "allow"
        return "ask"

    def for_child(self, operation: OperationContextV2) -> ChatRunToolPermissionV2:
        if (
            operation.descriptor != self.operation.descriptor
            or _identity(operation) != self.identity
        ):
            raise _denied()
        metadata = operation.require(OPERATION_METADATA_SERVICE_V2)
        run_id = (
            cast(Mapping[str, object], metadata).get("run_id")
            if isinstance(metadata, Mapping)
            else None
        )
        if not isinstance(run_id, str) or not run_id or run_id == self.run_id:
            raise _denied()
        return replace(self, operation=operation, child_run_id=run_id)


def current_chat_run_guard_v2() -> ChatRunToolPermissionV2 | None:
    try:
        operation = current_operation_context_v2()
        guard = operation.require(_SERVICE)
    except RuntimeV2Error as exc:
        if exc.code in {"operation_context_not_pinned", "missing_service"}:
            return None
        raise
    if not isinstance(guard, ChatRunToolPermissionV2):
        raise _denied()
    return guard


async def prepare_chat_run_guard_v2(
    operation: OperationContextV2,
    run_id: str | None,
    *,
    sessions: async_sessionmaker[AsyncSession] = async_session_factory,
) -> None:
    if not run_id:
        return
    existing = current_chat_run_guard_v2()
    if existing is not None:
        if existing.run_id != run_id or existing.operation is not operation:
            raise _denied()
        return
    identity = _identity(operation)
    row = await _read_run(sessions, run_id, identity)
    if row.run_kind != "chat":
        return
    mode = row.authorization_snapshot.get("effective_permission_mode")
    if (
        row.authorization_snapshot.get("schema_version") != 1
        or not isinstance(mode, str)
        or mode not in PERMISSION_PROFILES
    ):
        raise _denied()
    _ = operation.provide(
        _SERVICE, ChatRunToolPermissionV2(operation, run_id, identity, mode, sessions)
    )


def inherit_chat_run_guard_v2(
    parent: ChatRunToolPermissionV2 | None, child: OperationContextV2
) -> None:
    if parent is not None:
        _ = child.provide(_SERVICE, parent.for_child(child))


async def restore_chat_child_guard_v2(operation: OperationContextV2) -> None:
    from src.infrastructure.adapters.secondary.persistence.subagent_run_snapshot_model_v2 import (
        SubAgentRunSnapshotV2,
    )
    from src.infrastructure.agent.subagent.owner_lease_v2 import assert_owner_v2, current_owner_v2

    owner = current_owner_v2.get()
    if owner is None:
        return
    identity = _identity(operation)
    metadata = operation.require(OPERATION_METADATA_SERVICE_V2)
    if (
        owner.conversation_id != identity[2]
        or not isinstance(metadata, Mapping)
        or cast(Mapping[str, object], metadata).get("run_id") != owner.run_id
    ):
        raise _denied()
    async with owner.sessions() as db:
        _ = await assert_owner_v2(db, owner)
        snapshot = await db.get(SubAgentRunSnapshotV2, identity[2])
        if snapshot is None or (snapshot.tenant_id, snapshot.project_id) != identity[:2]:
            raise _denied()
        child_raw = snapshot.runs.get(owner.run_id)
        child = cast(dict[str, Any], child_raw) if isinstance(child_raw, dict) else {}
        if not isinstance(child, dict) or child.get("status") not in {"pending", "running"}:
            raise _denied()
        binding = child.get("metadata")
        if not isinstance(binding, dict):
            raise _denied()
        binding = cast(dict[str, Any], binding)
        run_id = binding.get("chat_permission_run_id")
        if run_id is None:
            return
        mode = binding.get("chat_permission_mode")
        if (
            not isinstance(run_id, str)
            or not run_id
            or not isinstance(mode, str)
            or mode not in PERMISSION_PROFILES
        ):
            raise _denied()
    row = await _read_run(owner.sessions, run_id, identity, owner.run_id)
    if (
        row.run_kind != "chat"
        or row.authorization_snapshot.get("effective_permission_mode") != mode
    ):
        raise _denied()
    _ = operation.provide(
        _SERVICE,
        ChatRunToolPermissionV2(operation, run_id, identity, mode, owner.sessions, owner.run_id),
    )


async def decision_for_current_chat_tool_v2(
    permission: str | None, tool_name: str, arguments: dict[str, Any], *, required: bool = False
) -> Decision:
    guard = current_chat_run_guard_v2()
    if guard is None:
        try:
            operation = current_operation_context_v2()
        except RuntimeV2Error as exc:
            if exc.code == "operation_context_not_pinned":
                return "deny" if required else "allow"
            raise
        await restore_chat_child_guard_v2(operation)
        guard = current_chat_run_guard_v2()
    if guard is None:
        return "deny" if required else "allow"
    return await guard.decision(permission, tool_name, arguments)


@contextmanager
def approved_chat_tool_call_v2(
    tool_name: str, arguments: dict[str, Any], *, supersede_previous: bool = False
) -> Iterator[None]:
    guard = current_chat_run_guard_v2()
    if guard is None:
        raise _denied()
    previous = _approval.get()
    if (
        supersede_previous
        and previous is not None
        and previous.identity[0] is guard.operation
        and previous.identity[1:3] == (guard.run_id, tool_name)
    ):
        # A later explicit confirmation supersedes the earlier invocation grant.
        # Context restoration must not make that earlier grant reusable.
        previous.consumed = True
    grant = _InvocationApproval((guard.operation, guard.run_id, tool_name, _arguments(arguments)))
    token = _approval.set(grant)
    try:
        yield
    finally:
        grant.consumed = True
        _approval.reset(token)


def claim_chat_tool_invocation_v2(
    tool_name: str, arguments: dict[str, Any], *, permission: str | None = None
) -> None:
    """Consume a human approval exactly at the actual invocation boundary."""
    if permission in _READ:
        return
    approved = _approval.get()
    if approved is None:
        return  # Read/automatic calls still pass their separate fresh decision.
    guard = current_chat_run_guard_v2()
    if (
        guard is None
        or approved.consumed
        or approved.identity != (guard.operation, guard.run_id, tool_name, _arguments(arguments))
    ):
        raise _denied()
    approved.consumed = True
