"""Fresh sender ceilings for persisted peer execution authority chains."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.approved_run_tool_permission_v2 import _MUTATION, _PROFILES, _READ
from src.application.services.chat_permission_admission_v2 import (
    PERMISSION_PROFILES,
    load_chat_permission_policy,
    require_chat_permission_mode,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanRunModel,
    AgentRunAuthorityModel,
    Conversation,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


def _denied() -> RuntimeV2Error:
    return RuntimeV2Error(
        "peer_sender_permission_denied", "Sending run no longer authorizes this operation"
    )


async def _source(
    sessions: async_sessionmaker[AsyncSession],
    binding: dict[str, Any],
    identity: tuple[str, str, str, str],
) -> tuple[AgentRunAuthorityModel, Conversation]:
    tenant, project, _receiver, user = identity
    if (
        binding.get("schema_version") != 1
        or binding.get("tenant_id") != tenant
        or binding.get("project_id") != project
        or binding.get("user_id") != user
        or binding.get("permission_profile") not in _PROFILES
        or binding.get("permission_mode") not in PERMISSION_PROFILES
    ):
        raise _denied()
    async with sessions() as db:
        found = (
            await db.execute(
                refresh_select_statement(
                    select(AgentRunAuthorityModel, Conversation)
                    .join(Conversation, Conversation.id == AgentRunAuthorityModel.conversation_id)
                    .join(User, User.id == Conversation.user_id)
                    .join(
                        UserProject,
                        (UserProject.user_id == user) & (UserProject.project_id == project),
                    )
                    .join(
                        UserTenant, (UserTenant.user_id == user) & (UserTenant.tenant_id == tenant)
                    )
                    .where(
                        AgentRunAuthorityModel.id == binding.get("run_id"),
                        AgentRunAuthorityModel.tenant_id == tenant,
                        AgentRunAuthorityModel.project_id == project,
                        AgentRunAuthorityModel.conversation_id == binding.get("conversation_id"),
                        Conversation.tenant_id == tenant,
                        Conversation.project_id == project,
                        Conversation.user_id == user,
                        User.is_active.is_(True),
                    )
                )
            )
        ).first()
        if found is None:
            raise _denied()
        run, conversation = found
        if (
            run.status not in {"queued", "running", "completed", "ready_review"}
            or run.run_kind != binding.get("run_kind")
            or run.permission_profile not in _PROFILES
            or run.authorization_snapshot.get("cancellation_receipt")
        ):
            raise _denied()
        if run.run_kind == "plan":
            plan = await db.get(AgentPlanRunModel, run.plan_run_id)
            raw_approval = run.authorization_snapshot.get("approval_request")
            approval = cast(dict[str, Any], raw_approval) if isinstance(raw_approval, dict) else {}
            raw_request = approval.get("request")
            request = cast(dict[str, Any], raw_request) if isinstance(raw_request, dict) else {}
            if (
                plan is None
                or plan.id != run.id
                or plan.status != run.status
                or plan.authorization_snapshot.get("approval_request") != approval
                or plan.conversation_id != run.conversation_id
                or plan.project_id != project
                or plan.plan_version_id != run.plan_version_id
                or plan.permission_profile != run.permission_profile
                or not isinstance(approval, dict)
                or approval.get("schema_version") != 1
                or approval.get("tenant_id") != tenant
                or approval.get("user_id") != user
                or not isinstance(request, dict)
                or request.get("permission_profile") != run.permission_profile
                or request.get("conversation_id") != run.conversation_id
                or request.get("project_id") != project
                or request.get("plan_version_id") != run.plan_version_id
            ):
                raise _denied()
        elif run.run_kind != "chat" or run.authorization_snapshot.get("schema_version") != 1:
            raise _denied()
        return run, conversation


async def require_peer_sender_permission_v2(
    receiver: AgentRunAuthorityModel,
    permission: str | None,
    identity: tuple[str, str, str, str],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    binding = receiver.authorization_snapshot.get("sender_authority")
    visited = {receiver.id}
    while binding is not None:
        if not isinstance(binding, dict) or not isinstance(binding.get("run_id"), str):
            raise _denied()
        if binding["run_id"] in visited:
            raise _denied()
        binding = cast(dict[str, Any], binding)
        visited.add(binding["run_id"])
        source, conversation = await _source(sessions, binding, identity)
        policy = await load_chat_permission_policy(conversation)
        policy_mode = policy.get("permission_mode")
        if not isinstance(policy_mode, str) or policy_mode not in PERMISSION_PROFILES:
            raise _denied()
        ceiling = PERMISSION_PROFILES[policy_mode]
        if source.run_kind == "chat":
            mode = source.authorization_snapshot.get("effective_permission_mode")
            if (
                mode not in PERMISSION_PROFILES
                or PERMISSION_PROFILES[mode] != source.permission_profile
            ):
                raise _denied()
            _ = require_chat_permission_mode(policy, mode)
            if permission not in _READ:
                if (
                    mode == "ask" or binding["permission_mode"] == "ask"
                ) and receiver.authorization_snapshot.get("effective_permission_mode") != "ask":
                    raise _denied()
                if (
                    mode == "automatic" or binding["permission_mode"] == "automatic"
                ) and permission not in {"workspace_task_write", "workspace_file_write"}:
                    raise _denied()
        else:
            effective = min(
                _PROFILES[binding["permission_profile"]],
                _PROFILES[source.permission_profile],
                _PROFILES[ceiling],
            )
            if permission not in _READ and not (
                (effective >= 1 and permission in {"workspace_task_write", "workspace_file_write"})
                or (effective == 2 and permission in _MUTATION)
            ):
                raise _denied()
        latest, _ = await _source(sessions, binding, identity)
        if (
            latest.authorization_snapshot != source.authorization_snapshot
            or latest.permission_profile != source.permission_profile
        ):
            raise _denied()
        binding = source.authorization_snapshot.get("sender_authority")
