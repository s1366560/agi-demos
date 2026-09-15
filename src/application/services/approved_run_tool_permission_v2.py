"""Operation-owned permission ceilings for formally approved plan executions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanRunModel,
    AgentRunAuthorityModel,
    Conversation,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_operation_context_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error

_SERVICE = "service:operation.approved-run-tool-permission"
_PROFILES = {"read_only": 0, "workspace_write": 1, "full_access": 2}
# These are declared permission categories, never tool-name or input-text classifications.
_READ = frozenset(
    {
        "read",
        "glob",
        "grep",
        "web_search",
        "web_scrape",
        "memory_search",
        "entity_lookup",
        "episode_retrieval",
        "graph_query",
        "delegate",
        "conversation_progress",
    }
)
_MUTATION = frozenset(
    {
        "write",
        "edit",
        "patch",
        "multiedit",
        "bash",
        "code_executor",
        "mcp",
        "system_api",
        "plugin_manager",
        "skill",
        "memory_create",
        "external_directory",
        "workspace_task_write",
        "workspace_file_write",
    }
)


def _denied() -> RuntimeV2Error:
    return RuntimeV2Error(
        "approved_run_tool_permission_denied", "Approved run does not authorize this tool operation"
    )


def _identity(operation: OperationContextV2) -> tuple[str, str, str, str]:
    scope = operation.context.scope
    identity = operation.require(OPERATION_IDENTITY_SERVICE_V2)
    if not isinstance(identity, Mapping):
        raise _denied()
    user = identity.get("user_id")
    if (
        not scope.tenant_id
        or not scope.project_id
        or not scope.session_id
        or not isinstance(user, str)
        or not user
        or identity.get("tenant_id") != scope.tenant_id
        or identity.get("project_id") != scope.project_id
    ):
        raise _denied()
    return scope.tenant_id, scope.project_id, scope.session_id, user


async def _read_run(
    sessions: async_sessionmaker[AsyncSession],
    run_id: str,
    identity: tuple[str, str, str, str],
    child_run_id: str | None = None,
) -> AgentRunAuthorityModel:
    tenant, project, conversation, user = identity
    async with sessions() as db:
        allowed_statuses = {"queued", "running"}
        if child_run_id:
            from src.infrastructure.agent.subagent.owner_lease_v2 import (
                assert_owner_v2,
                current_owner_v2,
            )

            owner = current_owner_v2.get()
            if (
                owner is None
                or owner.run_id != child_run_id
                or owner.conversation_id != conversation
            ):
                raise _denied()
            await assert_owner_v2(db, owner)
            # Detached work retains its approved ceiling after successful parent
            # completion only while its independently registered owner is live.
            allowed_statuses |= {"completed", "ready_review"}
        row = await db.scalar(
            select(AgentRunAuthorityModel)
            .join(
                Conversation,
                Conversation.id == AgentRunAuthorityModel.conversation_id,
            )
            .join(User, (User.id == Conversation.user_id) & User.is_active.is_(True))
            .join(
                UserProject,
                (UserProject.project_id == Conversation.project_id) & (UserProject.user_id == user),
            )
            .join(
                UserTenant,
                (UserTenant.tenant_id == Conversation.tenant_id) & (UserTenant.user_id == user),
            )
            .where(
                AgentRunAuthorityModel.id == run_id,
                AgentRunAuthorityModel.tenant_id == tenant,
                AgentRunAuthorityModel.project_id == project,
                AgentRunAuthorityModel.conversation_id == conversation,
                Conversation.tenant_id == tenant,
                Conversation.project_id == project,
                Conversation.user_id == user,
            )
        )
        if row is None or row.status not in allowed_statuses:
            raise _denied()
        if row.run_kind == "plan":
            source = await db.get(AgentPlanRunModel, row.plan_run_id)
            if (
                source is None
                or source.id != row.id
                or source.conversation_id != conversation
                or source.project_id != project
                or source.plan_version_id != row.plan_version_id
                or source.status not in allowed_statuses
                or source.permission_profile != row.permission_profile
                or source.authorization_snapshot.get("approval_request")
                != row.authorization_snapshot.get("approval_request")
            ):
                raise _denied()
            approval = row.authorization_snapshot.get("approval_request")
            request = approval.get("request") if isinstance(approval, dict) else None
            if (
                not isinstance(approval, dict)
                or approval.get("schema_version") != 1
                or approval.get("tenant_id") != tenant
                or approval.get("user_id") != user
                or not isinstance(request, dict)
                or request.get("permission_profile") != row.permission_profile
                or request.get("conversation_id") != conversation
                or request.get("project_id") != project
                or request.get("plan_version_id") != row.plan_version_id
                or row.authorization_snapshot.get("cancellation_receipt")
            ):
                raise _denied()
        return row


async def _current_plan_policy_ceiling(
    sessions: async_sessionmaker[AsyncSession],
    identity: tuple[str, str, str, str],
) -> str:
    from src.application.services.agent.runtime_model_route import load_workspace_policy

    async with sessions() as db:
        conversation = await db.get(Conversation, identity[2])
        if (
            conversation is None
            or (
                conversation.tenant_id,
                conversation.project_id,
                conversation.id,
                conversation.user_id,
            )
            != identity
        ):
            raise _denied()
        if not conversation.workspace_id:
            return "read_only"
        policy = await load_workspace_policy(conversation)
    profiles = {"ask": "read_only", "automatic": "workspace_write", "full_access": "full_access"}
    permission_mode = policy.get("permission_mode")
    profile = profiles.get(permission_mode) if isinstance(permission_mode, str) else None
    if profile is None:
        raise _denied()
    return profile


@dataclass(frozen=True)
class ApprovedRunToolPermissionV2:
    operation: OperationContextV2
    run_id: str
    identity: tuple[str, str, str, str]
    profile: str
    sessions: async_sessionmaker[AsyncSession]
    child_run_id: str | None = None

    async def require(self, permission: str | None) -> None:
        operation = current_operation_context_v2()
        if operation is not self.operation or _identity(operation) != self.identity:
            raise _denied()
        current_policy = await _current_plan_policy_ceiling(self.sessions, self.identity)
        # Policy transport can wait; re-read cancellation and membership afterwards.
        row = await _read_run(self.sessions, self.run_id, self.identity, self.child_run_id)
        if row.permission_profile not in _PROFILES:
            raise _denied()
        effective = min(
            _PROFILES[self.profile], _PROFILES[row.permission_profile], _PROFILES[current_policy]
        )
        if permission in _READ:
            return
        # A generic write declaration supplies no confinement proof. Workspace-write
        # cannot authorize arbitrary filesystem, shell, network or MCP mutations.
        if effective >= 1 and permission in {"workspace_task_write", "workspace_file_write"}:
            return
        if effective == 2 and permission in _MUTATION:
            return
        raise _denied()

    def for_child(self, child: OperationContextV2) -> ApprovedRunToolPermissionV2:
        if child.descriptor != self.operation.descriptor or _identity(child) != self.identity:
            raise _denied()
        metadata = child.require(OPERATION_METADATA_SERVICE_V2)
        run_id = metadata.get("run_id") if isinstance(metadata, Mapping) else None
        if not isinstance(run_id, str) or not run_id or run_id == self.run_id:
            raise _denied()
        return replace(self, operation=child, child_run_id=run_id)


def current_approved_run_guard_v2() -> ApprovedRunToolPermissionV2 | None:
    try:
        operation = current_operation_context_v2()
    except RuntimeV2Error as exc:
        if exc.code == "operation_context_not_pinned":
            return None
        raise
    try:
        guard = operation.require(_SERVICE)
    except RuntimeV2Error as exc:
        if exc.code == "missing_service":
            return None
        raise
    if not isinstance(guard, ApprovedRunToolPermissionV2):
        raise _denied()
    return guard


async def prepare_approved_run_guard_v2(
    operation: OperationContextV2,
    run_id: str | None,
    *,
    sessions: async_sessionmaker[AsyncSession] = async_session_factory,
) -> None:
    if not run_id:
        return
    existing = current_approved_run_guard_v2()
    if existing is not None:
        if existing.run_id != run_id:
            raise _denied()
        return
    identity = _identity(operation)
    row = await _read_run(sessions, run_id, identity)
    if row.run_kind != "plan":
        return
    if row.permission_profile not in _PROFILES:
        raise _denied()
    operation.provide(
        _SERVICE,
        ApprovedRunToolPermissionV2(operation, run_id, identity, row.permission_profile, sessions),
    )


def inherit_approved_run_guard_v2(
    parent: ApprovedRunToolPermissionV2 | None, child: OperationContextV2
) -> None:
    if parent is not None:
        child.provide(_SERVICE, parent.for_child(child))


async def restore_approved_child_guard_v2(operation: OperationContextV2) -> None:
    """Rebuild only from durable host-bound provenance and this child's live owner."""
    from src.infrastructure.adapters.secondary.persistence.subagent_run_snapshot_model_v2 import (
        SubAgentRunSnapshotV2,
    )
    from src.infrastructure.agent.subagent.owner_lease_v2 import assert_owner_v2, current_owner_v2

    owner = current_owner_v2.get()
    if owner is None:
        return
    tenant, project, conversation, _user = _identity(operation)
    metadata = operation.require(OPERATION_METADATA_SERVICE_V2)
    if (
        owner.conversation_id != conversation
        or not isinstance(metadata, Mapping)
        or metadata.get("run_id") != owner.run_id
    ):
        raise _denied()
    async with owner.sessions() as db:
        await assert_owner_v2(db, owner)
        snapshot = await db.get(SubAgentRunSnapshotV2, conversation)
        if snapshot is None or snapshot.tenant_id != tenant or snapshot.project_id != project:
            raise _denied()
        child = snapshot.runs.get(owner.run_id)
        if not isinstance(child, dict) or child.get("status") not in {"pending", "running"}:
            raise _denied()
        binding = child.get("metadata")
        if not isinstance(binding, dict):
            raise _denied()
        root_run_id = binding.get("approved_plan_run_id")
        if root_run_id is None:
            return  # Ordinary child: preserve its separate existing permission contract.
        ceiling = binding.get("approved_plan_permission_ceiling")
        if not isinstance(root_run_id, str) or not root_run_id or ceiling not in _PROFILES:
            raise _denied()
    await _read_run(owner.sessions, root_run_id, _identity(operation), owner.run_id)
    operation.provide(
        _SERVICE,
        ApprovedRunToolPermissionV2(
            operation,
            root_run_id,
            _identity(operation),
            ceiling,
            owner.sessions,
            owner.run_id,
        ),
    )


async def require_approved_run_tool_permission_v2(
    permission: str | None,
    *,
    required_run_id: str | None = None,
    required: bool = False,
) -> None:
    guard = current_approved_run_guard_v2()
    if guard is None:
        try:
            operation = current_operation_context_v2()
        except RuntimeV2Error:
            if required or required_run_id:
                raise _denied() from None
        else:
            await restore_approved_child_guard_v2(operation)
            guard = current_approved_run_guard_v2()
    if guard is None and required_run_id:
        operation = current_operation_context_v2()
        await prepare_approved_run_guard_v2(operation, required_run_id)
        guard = current_approved_run_guard_v2()
    if guard is not None:
        await guard.require(permission)
    elif required:
        raise _denied()
