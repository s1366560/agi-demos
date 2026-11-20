"""Persistence helpers for canonical root and plan run authority."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.chat_permission_admission_v2 import prepare_chat_permission_snapshot
from src.domain.model.agent.execution.run_execution_placement import (
    CLOUD_RUN_EXECUTION_PLACEMENT,
    ExecutionTarget,
    RunExecutionPlacement,
    parse_execution_target,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanRunModel,
    AgentRunAuthorityModel,
    Conversation,
)


def placement_from_row(row: AgentRunAuthorityModel) -> RunExecutionPlacement:
    """Read the four execution-location columns. Missing values stay cloud and null."""

    return RunExecutionPlacement(
        execution_target=parse_execution_target(getattr(row, "execution_target", None)),
        execution_machine_id=getattr(row, "execution_machine_id", None),
        execution_environment_id=getattr(row, "execution_environment_id", None),
        local_root_label=getattr(row, "local_root_label", None),
    )


def execution_fields(row: AgentRunAuthorityModel) -> dict[str, str | None]:
    """Public contract shared by REST, session projection, and WebSocket envelopes."""

    return placement_from_row(row).public_dict()


class ConversationExecutionIndex:
    """Run placements for one conversation, keyed by run id and message id."""

    def __init__(self, by_key: dict[str, RunExecutionPlacement]) -> None:
        self._by_key = by_key

    def resolve(self, *keys: object) -> RunExecutionPlacement:
        for key in keys:
            if isinstance(key, str) and key in self._by_key:
                return self._by_key[key]
        return CLOUD_RUN_EXECUTION_PLACEMENT

    def public_dict(self, *keys: object) -> dict[str, str | None]:
        return self.resolve(*keys).public_dict()


def stamp_execution_fields(
    payload: dict[str, Any],
    placement: RunExecutionPlacement,
) -> dict[str, Any]:
    """Copy an event envelope and attach the run's execution location."""

    stamped = dict(payload)
    stamped.update(placement.public_dict())
    return stamped


def _event_execution_keys(event: dict[str, Any]) -> tuple[object, ...]:
    data = event.get("data")
    if not isinstance(data, dict):
        return ()
    return (data.get("execution_message_id"), data.get("message_id"), data.get("run_id"))


def stamp_event_envelope(
    event: dict[str, Any],
    index: ConversationExecutionIndex,
    *fallback_keys: object,
) -> dict[str, Any]:
    """Attach the owning run's execution location to one replay or live envelope."""

    placement = index.resolve(*_event_execution_keys(event), *fallback_keys)
    return stamp_execution_fields(event, placement)


async def ensure_chat_run_authority(
    db: AsyncSession,
    *,
    conversation: Conversation,
    run_id: str,
    request_message: str,
    client_message_id: str | None,
    app_model_context: dict[str, Any] | None,
    permission_mode: str | None = None,
    permission_snapshot: dict[str, Any] | None = None,
    execution_target: str | ExecutionTarget | None = None,
) -> AgentRunAuthorityModel:
    """Create or replay the canonical authority before acknowledging a chat turn."""

    requested_target = parse_execution_target(execution_target)
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
            or existing.authorization_snapshot.get("requested_permission_mode") != permission_mode
            or placement_from_row(existing).execution_target != requested_target
        ):
            raise ValueError("Chat run authority conflict")
        await db.commit()
        return existing

    permissions = permission_snapshot or await prepare_chat_permission_snapshot(
        conversation, permission_mode
    )
    permission_profile = permissions["permission_profile"]
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
        execution_target=requested_target.value,
        execution_machine_id=None,
        execution_environment_id=None,
        local_root_label=None,
        authorization_snapshot={
            "source": "chat_admission",
            "conversation_id": conversation.id,
            "project_id": conversation.project_id,
            "workspace_id": conversation.workspace_id,
            "permission_profile": permission_profile,
            **permissions,
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
        execution_target=ExecutionTarget.CLOUD.value,
        execution_machine_id=None,
        execution_environment_id=None,
        local_root_label=None,
        authorization_snapshot=dict(run.authorization_snapshot),
        created_at=run.created_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
        error=run.error,
    )
    db.add(row)
    return row


async def fail_unstarted_chat_authority(
    db: AsyncSession,
    *,
    run_id: str,
    tenant_id: str,
    project_id: str,
    conversation_id: str,
    cause: str,
) -> bool:
    """Fail a chat authority that is still queued and has never started.

    A row that has already been marked running is left to that worker. The
    conditional update loses to ``mark_agent_run_running`` instead of
    cancelling a durable execution.
    """
    now = datetime.now(UTC)
    result = await db.execute(
        update(AgentRunAuthorityModel)
        .where(
            AgentRunAuthorityModel.id == run_id,
            AgentRunAuthorityModel.tenant_id == tenant_id,
            AgentRunAuthorityModel.project_id == project_id,
            AgentRunAuthorityModel.conversation_id == conversation_id,
            AgentRunAuthorityModel.run_kind == "chat",
            AgentRunAuthorityModel.status == "queued",
            AgentRunAuthorityModel.started_at.is_(None),
        )
        .values(
            status="failed",
            error=cause[:500],
            completed_at=now,
            updated_at=now,
        )
        .returning(AgentRunAuthorityModel.id)
    )
    closed = result.scalar_one_or_none() is not None
    if closed:
        await db.commit()
    return closed


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


async def latest_execution_placements(
    db: AsyncSession,
    *,
    tenant_id: str,
    project_id: str,
    conversation_ids: Sequence[str],
) -> dict[str, RunExecutionPlacement]:
    """Latest run placement per conversation. One query, no per-row round trips."""

    if not conversation_ids:
        return {}
    ranked = (
        select(
            AgentRunAuthorityModel.conversation_id.label("conversation_id"),
            AgentRunAuthorityModel.execution_target.label("execution_target"),
            AgentRunAuthorityModel.execution_machine_id.label("execution_machine_id"),
            AgentRunAuthorityModel.execution_environment_id.label("execution_environment_id"),
            AgentRunAuthorityModel.local_root_label.label("local_root_label"),
            func.row_number()
            .over(
                partition_by=AgentRunAuthorityModel.conversation_id,
                order_by=(
                    AgentRunAuthorityModel.created_at.desc(),
                    AgentRunAuthorityModel.id.desc(),
                ),
            )
            .label("placement_rank"),
        )
        .where(
            AgentRunAuthorityModel.tenant_id == tenant_id,
            AgentRunAuthorityModel.project_id == project_id,
            AgentRunAuthorityModel.conversation_id.in_(tuple(conversation_ids)),
        )
        .subquery()
    )
    result = await db.execute(
        refresh_select_statement(select(ranked).where(ranked.c.placement_rank == 1))
    )
    placements: dict[str, RunExecutionPlacement] = {}
    for row in result.all():
        placements[str(row.conversation_id)] = RunExecutionPlacement(
            execution_target=parse_execution_target(row.execution_target),
            execution_machine_id=row.execution_machine_id,
            execution_environment_id=row.execution_environment_id,
            local_root_label=row.local_root_label,
        )
    return placements


async def load_conversation_execution_index(
    db: AsyncSession,
    *,
    conversation_id: str,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> ConversationExecutionIndex:
    """Index every run in a conversation by its id and message id."""

    query = select(AgentRunAuthorityModel).where(
        AgentRunAuthorityModel.conversation_id == conversation_id
    )
    if tenant_id is not None:
        query = query.where(AgentRunAuthorityModel.tenant_id == tenant_id)
    if project_id is not None:
        query = query.where(AgentRunAuthorityModel.project_id == project_id)
    result = await db.execute(refresh_select_statement(query))
    by_key: dict[str, RunExecutionPlacement] = {}
    for row in result.scalars().all():
        placement = placement_from_row(row)
        by_key[row.id] = placement
        by_key[row.message_id] = placement
    return ConversationExecutionIndex(by_key)


__all__ = [
    "ConversationExecutionIndex",
    "ensure_chat_run_authority",
    "ensure_plan_run_authority",
    "execution_fields",
    "latest_execution_placements",
    "load_conversation_execution_index",
    "mark_agent_run_running",
    "mark_chat_run_running",
    "placement_from_row",
    "stamp_event_envelope",
    "stamp_execution_fields",
]
