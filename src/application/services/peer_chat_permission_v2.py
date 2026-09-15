"""Server-owned admission for agent-to-agent session execution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.approved_run_tool_permission_v2 import (
    _PROFILES,
    _current_plan_policy_ceiling,
    _read_run,
    current_approved_run_guard_v2,
)
from src.application.services.chat_permission_admission_v2 import (
    PERMISSION_PROFILES,
    load_chat_permission_policy,
)
from src.application.services.chat_run_tool_permission_v2 import current_chat_run_guard_v2
from src.domain.model.agent import Conversation as AgentConversation
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
    ensure_chat_run_authority,
)
from src.infrastructure.agent.orchestration.orchestrator import (
    SessionTurnExecutionRequest,
    SpawnExecutionRequest,
)
from src.infrastructure.plugins.v2.boundary import current_operation_context_v2
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error

_MODE_ORDER = ("ask", "automatic", "full_access")


def _denied() -> RuntimeV2Error:
    return RuntimeV2Error("peer_session_permission_denied", "Peer session authority is unavailable")


@dataclass(frozen=True)
class PeerSenderV2:
    operation: OperationContextV2
    identity: tuple[str, str, str, str]
    authority: dict[str, Any]
    sessions: async_sessionmaker[AsyncSession]


@dataclass
class _PeerDeliveryClaim:
    consumed: bool = False


@dataclass(frozen=True)
class PeerTurnAdmissionV2:
    sender: PeerSenderV2
    conversation: AgentConversation
    run_id: str
    message: str
    created: bool
    delivery: _PeerDeliveryClaim = field(
        default_factory=_PeerDeliveryClaim, repr=False, compare=False
    )


async def _sender() -> PeerSenderV2:
    approved = current_approved_run_guard_v2()
    chat = current_chat_run_guard_v2()
    guard = approved or chat
    if guard is None:
        raise _denied()
    if approved is not None:
        await approved.require("delegate")
        ceiling = await _current_plan_policy_ceiling(approved.sessions, approved.identity)
        source = await _read_run(
            approved.sessions, approved.run_id, approved.identity, approved.child_run_id
        )
        effective = min(
            _PROFILES[approved.profile], _PROFILES[source.permission_profile], _PROFILES[ceiling]
        )
        kind, profile = "plan", next(name for name, rank in _PROFILES.items() if rank == effective)
        mode = {"read_only": "ask", "workspace_write": "automatic", "full_access": "full_access"}[
            profile
        ]
    else:
        assert chat is not None
        if await chat.decision("delegate", "", {}) != "allow":
            raise _denied()
        kind, mode = "chat", chat.mode
        profile = PERMISSION_PROFILES[mode]
    tenant, project, conversation, user = guard.identity
    return PeerSenderV2(
        current_operation_context_v2(),
        guard.identity,
        {
            "schema_version": 1,
            "run_id": guard.run_id,
            "run_kind": kind,
            "tenant_id": tenant,
            "project_id": project,
            "conversation_id": conversation,
            "user_id": user,
            "permission_profile": profile,
            "permission_mode": mode,
        },
        guard.sessions,
    )


async def _load_peer_conversation(
    request: SpawnExecutionRequest | SessionTurnExecutionRequest,
    sender: PeerSenderV2,
    *,
    spawn: bool,
) -> AgentConversation:
    from src.application.services.agent.runtime_bootstrapper import AgentRuntimeBootstrapper

    tenant, project, parent, user = sender.identity
    if request.tenant_id != tenant or request.project_id != project:
        raise _denied()
    if spawn:
        if not isinstance(request, SpawnExecutionRequest):
            raise _denied()
        if request.parent_session_id != parent or request.user_id != user:
            raise _denied()
        return await AgentRuntimeBootstrapper.ensure_spawned_agent_conversation(
            child_session_id=request.child_session_id,
            parent_session_id=parent,
            project_id=project,
            tenant_id=tenant,
            user_id=user,
            parent_agent_id=request.parent_agent_id,
            child_agent_id=request.child_agent_id,
            child_agent_name=request.child_agent_name,
            mode=request.mode.value,
            metadata=request.metadata,
        )
    if not isinstance(request, SessionTurnExecutionRequest):
        raise _denied()
    return await AgentRuntimeBootstrapper.load_spawned_agent_conversation(
        child_session_id=request.child_session_id, project_id=project, tenant_id=tenant
    )


async def prepare_peer_execution_v2(
    request: SpawnExecutionRequest | SessionTurnExecutionRequest, *, spawn: bool
) -> PeerTurnAdmissionV2:
    sender = await _sender()
    tenant, project, _parent, user = sender.identity
    conversation = await _load_peer_conversation(request, sender, spawn=spawn)
    source_id = (
        f"spawn:{request.child_session_id}"
        if isinstance(request, SpawnExecutionRequest)
        else request.source_message_id
    )
    if not source_id:
        raise _denied()
    key = f"peer:{sender.authority['run_id']}:{conversation.id}:{source_id}"
    run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, key))
    async with sender.sessions() as db:
        peer = await db.scalar(
            select(Conversation)
            .where(
                Conversation.id == conversation.id,
                Conversation.tenant_id == tenant,
                Conversation.project_id == project,
                Conversation.user_id == user,
            )
            .with_for_update()
        )
        if peer is None or not peer.parent_conversation_id:
            raise _denied()
        existing = await db.get(AgentRunAuthorityModel, run_id)
        if existing is not None:
            if (
                existing.conversation_id != peer.id
                or existing.request_message != request.message
                or existing.authorization_snapshot.get("sender_authority") != sender.authority
            ):
                raise _denied()
            return PeerTurnAdmissionV2(sender, conversation, run_id, request.message, False)
        active = await db.scalar(
            select(AgentRunAuthorityModel.id)
            .where(
                AgentRunAuthorityModel.conversation_id == peer.id,
                AgentRunAuthorityModel.status.in_(("queued", "running")),
            )
            .limit(1)
        )
        if active is not None:
            raise RuntimeV2Error(
                "peer_session_active", "Peer session already has an active execution"
            )
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )

        if await SqlHITLRequestRepository(db).get_pending_by_conversation(
            conversation_id=peer.id, tenant_id=tenant, project_id=project
        ):
            raise RuntimeV2Error(
                "peer_session_waiting_for_input", "Peer session is waiting for input"
            )
        policy = await load_chat_permission_policy(peer)
        ceiling = policy.get("permission_mode")
        if ceiling not in _MODE_ORDER:
            raise _denied()
        mode = _MODE_ORDER[
            min(_MODE_ORDER.index(ceiling), _MODE_ORDER.index(sender.authority["permission_mode"]))
        ]
        # Parent read_only remains a separate hard ceiling in sender_authority;
        # ASK here describes only the receiving session's confirmation behavior.
        permissions = {
            "schema_version": 1,
            "requested_permission_mode": mode,
            "effective_permission_mode": mode,
            "permission_profile": PERMISSION_PROFILES[mode],
            "policy": policy,
            "sender_authority": sender.authority,
        }
        refreshed_sender = await _sender()
        if refreshed_sender.authority != sender.authority:
            raise _denied()
        _ = await ensure_chat_run_authority(
            db,
            conversation=peer,
            run_id=run_id,
            request_message=request.message,
            client_message_id=key,
            app_model_context=None,
            permission_mode=mode,
            permission_snapshot=permissions,
        )
    return PeerTurnAdmissionV2(sender, conversation, run_id, request.message, True)


async def resolve_peer_execution_v2(
    request: SpawnExecutionRequest | SessionTurnExecutionRequest, *, spawn: bool
) -> PeerTurnAdmissionV2:
    admission = getattr(request, "admission", None)
    if admission is None:
        admission = await prepare_peer_execution_v2(request, spawn=spawn)
    if (
        not isinstance(admission, PeerTurnAdmissionV2)
        or admission.sender.operation is not current_operation_context_v2()
        or admission.conversation.id != request.child_session_id
        or admission.message != request.message
    ):
        raise _denied()
    if admission.delivery.consumed:
        return replace(admission, created=False)
    admission.delivery.consumed = True
    return admission


async def preflight_spawned_session_v2(request: SpawnExecutionRequest) -> PeerTurnAdmissionV2:
    return await prepare_peer_execution_v2(request, spawn=True)


async def preflight_session_turn_v2(request: SessionTurnExecutionRequest) -> PeerTurnAdmissionV2:
    return await prepare_peer_execution_v2(request, spawn=False)


async def fail_peer_execution_v2(admission: object) -> None:
    from src.infrastructure.adapters.secondary.persistence.agent_run_settlement import (
        settle_agent_run,
    )

    if not isinstance(admission, PeerTurnAdmissionV2) or not admission.created:
        return
    async with admission.sender.sessions() as db:
        row = await db.get(AgentRunAuthorityModel, admission.run_id)
        if (
            row is None
            or row.conversation_id != admission.conversation.id
            or row.status != "queued"
            or row.authorization_snapshot.get("sender_authority") != admission.sender.authority
        ):
            return
        completed = datetime.now(UTC)
        row.status = "failed"
        row.error = "Peer session delivery or execution admission failed"
        row.completed_at = completed
        row.updated_at = completed
        row.revision += 1
        started_at = row.created_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        await settle_agent_run(
            db, run=row, started_at=started_at, succeeded=False, completed_at=completed
        )
        await db.commit()
