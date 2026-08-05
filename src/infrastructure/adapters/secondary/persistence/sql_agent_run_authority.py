"""Persistence helpers for canonical root and plan run authority."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanRunModel,
    AgentRunAuthorityModel,
    Conversation,
    WorkspaceAgentPolicyModel,
)


def _permission_profile(permission_mode: str) -> str:
    return {
        "ask": "read_only",
        "automatic": "workspace_write",
        "full_access": "full_access",
    }.get(permission_mode, "read_only")


async def ensure_chat_run_authority(
    db: AsyncSession,
    *,
    conversation: Conversation,
    run_id: str,
    request_message: str,
    client_message_id: str | None,
    app_model_context: dict[str, Any] | None,
    permission_mode: str | None = None,
) -> AgentRunAuthorityModel:
    """Create or replay the canonical authority before acknowledging a chat turn."""

    existing = await db.get(AgentRunAuthorityModel, run_id)
    idempotency_key = (
        f"client-message:{client_message_id}" if client_message_id else f"execution:{run_id}"
    )
    if existing is not None:
        if (
            existing.run_kind != "chat"
            or existing.conversation_id != conversation.id
            or existing.project_id != conversation.project_id
            or existing.tenant_id != conversation.tenant_id
            or existing.message_id != run_id
            or existing.request_message != request_message
            or existing.idempotency_key != idempotency_key
        ):
            raise ValueError("Chat run authority conflict")
        await db.commit()
        return existing

    policy = (
        await db.get(WorkspaceAgentPolicyModel, conversation.workspace_id)
        if conversation.workspace_id
        else None
    )
    policy_permission_mode = policy.permission_mode if policy is not None else "ask"
    effective_permission_mode = permission_mode or policy_permission_mode
    permission_profile = _permission_profile(effective_permission_mode)
    now = datetime.now(UTC)
    row = AgentRunAuthorityModel(
        id=run_id,
        tenant_id=conversation.tenant_id,
        project_id=conversation.project_id,
        conversation_id=conversation.id,
        run_kind="chat",
        plan_run_id=None,
        plan_version_id=None,
        idempotency_key=idempotency_key,
        message_id=run_id,
        request_message=request_message,
        status="queued",
        revision=1,
        permission_profile=permission_profile,
        authorization_snapshot={
            "source": "chat_admission",
            "conversation_id": conversation.id,
            "project_id": conversation.project_id,
            "workspace_id": conversation.workspace_id,
            "permission_profile": permission_profile,
            "requested_permission_mode": permission_mode,
            "effective_permission_mode": effective_permission_mode,
            "policy": {
                "revision": policy.revision if policy is not None else 0,
                "permission_mode": policy_permission_mode,
            },
            "context_authorities": (
                list(app_model_context.get("context_items", []))
                if isinstance(app_model_context, dict)
                and isinstance(app_model_context.get("context_items"), list)
                else []
            ),
        },
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    return row


async def ensure_plan_run_authority(
    db: AsyncSession,
    *,
    run: AgentPlanRunModel,
    tenant_id: str,
) -> AgentRunAuthorityModel:
    """Mirror a plan-run into the canonical authority without changing plan semantics."""

    result = await db.execute(
        refresh_select_statement(
            select(AgentRunAuthorityModel).where(AgentRunAuthorityModel.id == run.id)
        )
    )
    existing = cast(AgentRunAuthorityModel | None, result.scalar_one_or_none())
    if existing is not None:
        return existing
    row = AgentRunAuthorityModel(
        id=run.id,
        tenant_id=tenant_id,
        project_id=run.project_id,
        conversation_id=run.conversation_id,
        run_kind="plan",
        plan_run_id=run.id,
        plan_version_id=run.plan_version_id,
        idempotency_key=run.idempotency_key,
        message_id=run.message_id,
        request_message=run.request_message,
        status=run.status,
        revision=run.revision,
        permission_profile=run.permission_profile,
        authorization_snapshot=dict(run.authorization_snapshot),
        created_at=run.created_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
        error=run.error,
    )
    db.add(row)
    return row


async def mark_agent_run_running(
    db: AsyncSession,
    *,
    run_id: str,
    tenant_id: str,
    project_id: str,
    conversation_id: str,
) -> AgentRunAuthorityModel | None:
    """Transition a canonical chat or plan authority to running in its exact scope."""

    result = await db.execute(
        refresh_select_statement(
            select(AgentRunAuthorityModel)
            .where(
                AgentRunAuthorityModel.id == run_id,
                AgentRunAuthorityModel.tenant_id == tenant_id,
                AgentRunAuthorityModel.project_id == project_id,
                AgentRunAuthorityModel.conversation_id == conversation_id,
            )
            .with_for_update()
        )
    )
    run = cast(AgentRunAuthorityModel | None, result.scalar_one_or_none())
    if run is None:
        return None
    if run.status not in {"queued", "running"}:
        raise ValueError("Agent run is not startable")
    run.status = "running"
    now = datetime.now(UTC)
    run.started_at = run.started_at or now
    run.updated_at = now
    await db.commit()
    return run


async def mark_chat_run_running(
    db: AsyncSession,
    *,
    run_id: str,
    tenant_id: str,
    project_id: str,
    conversation_id: str,
) -> AgentRunAuthorityModel | None:
    """Transition an admitted root chat run to running in its exact scope."""

    result = await db.execute(
        refresh_select_statement(
            select(AgentRunAuthorityModel)
            .where(
                AgentRunAuthorityModel.id == run_id,
                AgentRunAuthorityModel.tenant_id == tenant_id,
                AgentRunAuthorityModel.project_id == project_id,
                AgentRunAuthorityModel.conversation_id == conversation_id,
                AgentRunAuthorityModel.run_kind == "chat",
            )
            .with_for_update()
        )
    )
    run = cast(AgentRunAuthorityModel | None, result.scalar_one_or_none())
    if run is None:
        return None
    if run.status not in {"queued", "running"}:
        raise ValueError("Chat run is not startable")
    run.status = "running"
    now = datetime.now(UTC)
    run.started_at = run.started_at or now
    run.updated_at = now
    await db.commit()
    return run


__all__ = [
    "ensure_chat_run_authority",
    "ensure_plan_run_authority",
    "mark_agent_run_running",
    "mark_chat_run_running",
]
