"""Canonical Cloud authority for Queue/Steer run inputs."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.agent_run_authority import (
    CreateRunInputRequest,
    PromoteRunInputRequest,
    PromoteRunInputResponse,
    RunInputAck,
    RunInputListResponse,
    RunInputReceipt,
)
from src.configuration.di_container import DIContainer
from src.domain.model.agent.run_input import AgentRunInputDelivery, AgentRunInputStatus
from src.domain.model.agent.tool_policy import ControlMessageType
from src.domain.ports.agent.control_channel_port import ControlMessage
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.attachment_model import AttachmentModel
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    AgentPlanRunModel,
    AgentPlanVersionModel,
    AgentRunAuthorityModel,
    AgentRunInputModel,
    Conversation,
    User,
)
from src.infrastructure.agent.subagent.control_channel import RedisControlChannel
from src.infrastructure.i18n import gettext as _

from .plans import _execute_approved_plan
from .run_authority_common import _canonical_hash, _explicit_change_payloads, _load_scoped_run

router = APIRouter()
_PROMOTED_RUN_TASKS: set[asyncio.Task[None]] = set()
_ACTIVE_RUN_STATUSES = frozenset({"queued", "running"})
_RUN_INPUT_DISPATCH_LEASE = timedelta(seconds=30)


async def _validate_run_input_authorities(
    db: AsyncSession,
    *,
    body: CreateRunInputRequest,
    run: AgentRunAuthorityModel,
    conversation: Conversation,
    user_id: str,
) -> None:
    """Fail closed unless every structured reference belongs to the run scope."""

    environment = run.authorization_snapshot.get("environment")
    environment_id = (
        environment.get("id")
        if isinstance(environment, dict) and isinstance(environment.get("id"), str)
        else None
    )
    if body.references:
        event_result = await db.execute(
            refresh_select_statement(
                select(AgentExecutionEvent).where(
                    AgentExecutionEvent.conversation_id == run.conversation_id,
                    AgentExecutionEvent.message_id == run.message_id,
                )
            )
        )
        known_changes = {
            (path, digest)
            for event in event_result.scalars().all()
            for payload in _explicit_change_payloads(event)
            if isinstance((path := payload.get("path") or payload.get("file_path")), str)
            and isinstance((digest := payload.get("patch_digest")), str)
        }
        if environment_id is None:
            raise HTTPException(
                status_code=409,
                detail=_("Run reference authority is unavailable"),
            )
        for reference in body.references:
            if (
                reference.environment_id != environment_id
                or (reference.path, reference.patch_digest) not in known_changes
            ):
                raise HTTPException(
                    status_code=409,
                    detail=_("Run reference authority conflict"),
                )

    attachments = {item.resource_id for item in body.context_items if item.kind == "attachment"}
    if attachments:
        attachment_result = await db.execute(
            refresh_select_statement(
                select(AttachmentModel.id).where(
                    AttachmentModel.id.in_(attachments),
                    AttachmentModel.tenant_id == conversation.tenant_id,
                    AttachmentModel.project_id == conversation.project_id,
                    AttachmentModel.conversation_id == conversation.id,
                    AttachmentModel.status.in_(["uploaded", "ready"]),
                )
            )
        )
        if set(attachment_result.scalars().all()) != attachments:
            raise HTTPException(
                status_code=409,
                detail=_("Attachment context authority conflict"),
            )

    thread_ids = {item.resource_id for item in body.context_items if item.kind == "thread"}
    if thread_ids:
        thread_result = await db.execute(
            refresh_select_statement(
                select(Conversation.id).where(
                    Conversation.id.in_(thread_ids),
                    Conversation.tenant_id == conversation.tenant_id,
                    Conversation.project_id == conversation.project_id,
                    Conversation.user_id == user_id,
                )
            )
        )
        if set(thread_result.scalars().all()) != thread_ids:
            raise HTTPException(
                status_code=409,
                detail=_("Thread context authority conflict"),
            )

    roster = set(conversation.participant_agents)
    if any(item.kind == "agent" and item.resource_id not in roster for item in body.context_items):
        raise HTTPException(
            status_code=409,
            detail=_("Agent context authority conflict"),
        )

    declared = run.authorization_snapshot.get("context_authorities")
    declared_items = declared if isinstance(declared, list) else []
    declared_authorities = {
        (item.get("kind"), item.get("resource_id"))
        for item in declared_items
        if isinstance(item, dict)
        and isinstance(item.get("kind"), str)
        and isinstance(item.get("resource_id"), str)
    }
    if any(
        item.kind in {"skill", "plugin", "command"}
        and (item.kind, item.resource_id) not in declared_authorities
        for item in body.context_items
    ):
        raise HTTPException(
            status_code=409,
            detail=_("Run context authority conflict"),
        )


def _input_receipt(row: AgentRunInputModel) -> RunInputReceipt:
    return RunInputReceipt(
        id=row.id,
        conversation_id=row.conversation_id,
        run_id=row.run_id,
        expected_run_revision=row.expected_run_revision,
        message_id=row.message_id,
        idempotency_key=row.idempotency_key,
        delivery=cast(Literal["steer_now", "queue_next"], row.delivery),
        status=cast(
            Literal[
                "pending_boundary",
                "queued",
                "applied",
                "ready",
                "blocked",
                "promoted_to_plan",
            ],
            row.status,
        ),
        sequence=row.sequence,
        queue_position=row.queue_position,
        content=row.message,
        references=list(row.references_json),
        context_items=list(row.context_items_json),
        applied_round=row.applied_round,
        applied_at=row.applied_at,
        injected_via=row.injected_via,
        dispatch_status=cast(
            Literal["not_required", "dispatching", "dispatched", "failed"],
            row.dispatch_status,
        ),
        dispatch_attempts=row.dispatch_attempts,
        dispatch_lease_expires_at=row.dispatch_lease_expires_at,
        dispatch_error_code=row.dispatch_error_code,
        promotion_idempotency_key=row.promotion_key,
        promoted_at=row.promoted_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _input_ack(
    row: AgentRunInputModel,
    *,
    run_revision: int,
    created: bool,
) -> RunInputAck:
    return RunInputAck(
        accepted=True,
        created=created,
        conversation_id=row.conversation_id,
        message_id=row.message_id,
        delivery_mode=cast(Literal["steer_now", "queue_next"], row.delivery),
        run_id=row.run_id,
        run_revision=run_revision,
        queue_position=row.queue_position,
        input=_input_receipt(row),
    )


def _run_input_dispatch_rejection(
    *,
    status_code: int,
    reason_code: str,
    detail: str,
    row: AgentRunInputModel,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "accepted": False,
            "reason_code": reason_code,
            "detail": _(detail),
            "run_id": row.run_id,
            "run_revision": row.expected_run_revision,
            "input_id": row.id,
            "idempotency_key": row.idempotency_key,
            "dispatch_status": row.dispatch_status,
            "retryable": status_code == status.HTTP_503_SERVICE_UNAVAILABLE,
        },
    )


def _dispatch_lease_is_active(row: AgentRunInputModel, *, now: datetime) -> bool:
    lease = row.dispatch_lease_expires_at
    if lease is None:
        return False
    if lease.tzinfo is None:
        lease = lease.replace(tzinfo=UTC)
    return lease > now


async def _dispatch_persisted_steer(
    *,
    request: Request,
    db: AsyncSession,
    row: AgentRunInputModel,
    current_user: User,
    created: bool,
) -> RunInputAck | JSONResponse:
    """Dispatch a committed steer row, then settle its retryable transport state."""

    base_container = cast(DIContainer, request.app.state.container)
    accepted = False
    error_code = "control_channel_unavailable"
    if base_container.redis_client is not None:
        accepted = await RedisControlChannel(base_container.redis_client).send_control(
            ControlMessage(
                run_id=row.run_id,
                message_type=ControlMessageType.STEER,
                payload=row.message,
                sender_id=current_user.id,
                run_input_id=row.id,
                delivery_mode="steer_now",
                run_revision=row.expected_run_revision,
                message_id=row.message_id,
                idempotency_key=row.idempotency_key,
            )
        )
        error_code = "control_channel_rejected"

    now = datetime.now(UTC)
    row.dispatch_lease_expires_at = None
    row.updated_at = now
    if not accepted:
        row.dispatch_status = "failed"
        row.dispatch_error_code = error_code
        await db.commit()
        return _run_input_dispatch_rejection(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            reason_code="run_input_dispatch_failed",
            detail="Run input delivery failed",
            row=row,
        )

    row.dispatch_status = "dispatched"
    row.dispatch_error_code = None
    await db.commit()
    return _input_ack(
        row,
        run_revision=row.expected_run_revision,
        created=created,
    )


def _promotion_response(
    row: AgentRunInputModel,
    *,
    conversation: Conversation,
    source_run: AgentRunAuthorityModel,
    created: bool,
) -> PromoteRunInputResponse:
    return PromoteRunInputResponse(
        accepted=True,
        created=created,
        input=_input_receipt(row),
        conversation={
            "id": conversation.id,
            "tenant_id": conversation.tenant_id,
            "project_id": conversation.project_id,
            "user_id": conversation.user_id,
            "title": conversation.title,
            "status": conversation.status,
            "current_mode": conversation.current_mode,
            "workspace_id": conversation.workspace_id,
            "linked_workspace_task_id": conversation.linked_workspace_task_id,
        },
        source_run={
            "id": source_run.id,
            "conversation_id": source_run.conversation_id,
            "project_id": source_run.project_id,
            "plan_version_id": source_run.plan_version_id,
            "message_id": source_run.message_id,
            "status": source_run.status,
            "revision": source_run.revision,
            "permission_profile": source_run.permission_profile,
            "created_at": source_run.created_at.isoformat(),
            "updated_at": source_run.updated_at.isoformat(),
            "completed_at": (
                source_run.completed_at.isoformat() if source_run.completed_at else None
            ),
        },
    )


@router.post("/runs/{run_id}/inputs", response_model=RunInputAck)
async def create_run_input(
    run_id: str,
    body: CreateRunInputRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RunInputAck | JSONResponse:
    """Accept one idempotent Queue/Steer input after full scope and revision checks."""

    run, conversation = await _load_scoped_run(
        db,
        run_id=run_id,
        user_id=current_user.id,
        lock=True,
    )
    payload_hash = _canonical_hash(body.model_dump(mode="json"))
    existing_result = await db.execute(
        refresh_select_statement(
            select(AgentRunInputModel)
            .where(
                AgentRunInputModel.run_id == run.id,
                AgentRunInputModel.idempotency_key == body.idempotency_key,
            )
            .with_for_update()
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise HTTPException(status_code=409, detail=_("Run input idempotency conflict"))
        if existing.delivery == "queue_next" or existing.dispatch_status == "dispatched":
            return _input_ack(
                existing,
                run_revision=existing.expected_run_revision,
                created=False,
            )
        if run.revision != existing.expected_run_revision:
            raise HTTPException(status_code=409, detail=_("Agent run revision conflict"))
        if run.status != "running":
            raise HTTPException(status_code=409, detail=_("Agent run is not ready for steering"))
        await _validate_run_input_authorities(
            db,
            body=body,
            run=run,
            conversation=conversation,
            user_id=current_user.id,
        )
        now = datetime.now(UTC)
        if existing.dispatch_status == "dispatching" and _dispatch_lease_is_active(
            existing,
            now=now,
        ):
            return _run_input_dispatch_rejection(
                status_code=status.HTTP_409_CONFLICT,
                reason_code="run_input_dispatch_in_progress",
                detail="Run input delivery is already in progress",
                row=existing,
            )
        existing.dispatch_status = "dispatching"
        existing.dispatch_attempts += 1
        existing.dispatch_lease_expires_at = now + _RUN_INPUT_DISPATCH_LEASE
        existing.dispatch_error_code = None
        existing.updated_at = now
        await db.commit()
        return await _dispatch_persisted_steer(
            request=request,
            db=db,
            row=existing,
            current_user=current_user,
            created=False,
        )
    if run.revision != body.expected_run_revision:
        raise HTTPException(status_code=409, detail=_("Agent run revision conflict"))
    if run.status not in _ACTIVE_RUN_STATUSES:
        raise HTTPException(status_code=409, detail=_("Agent run is not active"))
    if body.delivery == "steer_now" and run.status != "running":
        raise HTTPException(status_code=409, detail=_("Agent run is not ready for steering"))
    await _validate_run_input_authorities(
        db,
        body=body,
        run=run,
        conversation=conversation,
        user_id=current_user.id,
    )

    sequence_result = await db.execute(
        refresh_select_statement(
            select(func.coalesce(func.max(AgentRunInputModel.sequence), 0)).where(
                AgentRunInputModel.run_id == run.id
            )
        )
    )
    sequence = int(sequence_result.scalar_one()) + 1
    queue_position: int | None = None
    if body.delivery == "queue_next":
        queue_result = await db.execute(
            refresh_select_statement(
                select(func.count(AgentRunInputModel.id)).where(
                    AgentRunInputModel.run_id == run.id,
                    AgentRunInputModel.delivery == AgentRunInputDelivery.QUEUE_NEXT,
                    AgentRunInputModel.status.in_(
                        [AgentRunInputStatus.QUEUED, AgentRunInputStatus.READY]
                    ),
                )
            )
        )
        queue_position = int(queue_result.scalar_one()) + 1
    now = datetime.now(UTC)
    row = AgentRunInputModel(
        id=str(uuid.uuid4()),
        tenant_id=conversation.tenant_id,
        project_id=run.project_id,
        conversation_id=run.conversation_id,
        run_id=run.id,
        actor_user_id=current_user.id,
        expected_run_revision=body.expected_run_revision,
        message=body.message,
        message_id=body.message_id,
        idempotency_key=body.idempotency_key,
        payload_hash=payload_hash,
        delivery=body.delivery,
        references_json=[item.model_dump(mode="json") for item in body.references],
        context_items_json=[item.model_dump(mode="json") for item in body.context_items],
        status=(
            AgentRunInputStatus.PENDING_BOUNDARY
            if body.delivery == "steer_now"
            else AgentRunInputStatus.QUEUED
        ),
        sequence=sequence,
        queue_position=queue_position,
        dispatch_status="dispatching" if body.delivery == "steer_now" else "not_required",
        dispatch_attempts=1 if body.delivery == "steer_now" else 0,
        dispatch_lease_expires_at=(
            now + _RUN_INPUT_DISPATCH_LEASE if body.delivery == "steer_now" else None
        ),
        dispatch_error_code=None,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    if body.delivery == "steer_now":
        return await _dispatch_persisted_steer(
            request=request,
            db=db,
            row=row,
            current_user=current_user,
            created=True,
        )
    return _input_ack(row, run_revision=run.revision, created=True)


@router.get("/runs/{run_id}/inputs", response_model=RunInputListResponse)
async def list_run_inputs(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RunInputListResponse:
    """List accepted inputs for one fully scoped run."""

    run, _conversation = await _load_scoped_run(
        db,
        run_id=run_id,
        user_id=current_user.id,
    )
    result = await db.execute(
        refresh_select_statement(
            select(AgentRunInputModel)
            .where(AgentRunInputModel.run_id == run.id)
            .order_by(AgentRunInputModel.created_at.asc(), AgentRunInputModel.id.asc())
        )
    )
    inputs = [_input_receipt(item) for item in result.scalars().all()]
    return RunInputListResponse(
        run_id=run.id,
        run_revision=run.revision,
        inputs=inputs,
        total_count=len(inputs),
    )


@router.post(
    "/runs/{run_id}/inputs/{input_id}/promote",
    response_model=PromoteRunInputResponse,
)
async def promote_run_input(
    run_id: str,
    input_id: str,
    body: PromoteRunInputRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PromoteRunInputResponse:
    """Explicitly and idempotently promote one ready queued input."""

    run, conversation = await _load_scoped_run(
        db,
        run_id=run_id,
        user_id=current_user.id,
        lock=True,
    )
    input_result = await db.execute(
        refresh_select_statement(
            select(AgentRunInputModel)
            .where(
                AgentRunInputModel.id == input_id,
                AgentRunInputModel.run_id == run.id,
                AgentRunInputModel.tenant_id == conversation.tenant_id,
                AgentRunInputModel.project_id == run.project_id,
                AgentRunInputModel.conversation_id == run.conversation_id,
                AgentRunInputModel.actor_user_id == current_user.id,
            )
            .with_for_update()
        )
    )
    row = input_result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=_("Run input not found"))
    if row.status == AgentRunInputStatus.PROMOTED_TO_PLAN:
        if row.promotion_key != body.idempotency_key or row.promoted_run_id is None:
            raise HTTPException(status_code=409, detail=_("Run input promotion conflict"))
        promoted = await db.get(AgentPlanRunModel, row.promoted_run_id)
        if promoted is None:
            raise HTTPException(status_code=409, detail=_("Promoted run is missing"))
        return _promotion_response(
            row,
            conversation=conversation,
            source_run=run,
            created=False,
        )
    if run.revision != body.expected_source_run_revision:
        raise HTTPException(status_code=409, detail=_("Agent run revision conflict"))
    if row.status != AgentRunInputStatus.READY:
        raise HTTPException(status_code=409, detail=_("Run input is not ready for promotion"))

    now = datetime.now(UTC)
    latest_plan_version = await db.scalar(
        select(func.max(AgentPlanVersionModel.version)).where(
            AgentPlanVersionModel.conversation_id == run.conversation_id
        )
    )
    promoted_plan = AgentPlanVersionModel(
        id=str(uuid.uuid4()),
        conversation_id=run.conversation_id,
        version=(latest_plan_version or 0) + 1,
        status="draft",
        tasks_json=[],
        policy_revision=None,
        created_at=now,
    )
    db.add(promoted_plan)
    await db.flush()
    conversation.current_mode = "plan"
    conversation.current_plan_id = promoted_plan.id
    conversation.updated_at = now
    promoted = AgentPlanRunModel(
        id=str(uuid.uuid4()),
        conversation_id=run.conversation_id,
        project_id=run.project_id,
        plan_version_id=promoted_plan.id,
        idempotency_key=f"run-input:{row.id}:{body.idempotency_key}",
        message_id=row.message_id,
        request_message=row.message,
        status="running",
        revision=1,
        permission_profile="read_only",
        authorization_snapshot={
            **dict(run.authorization_snapshot),
            "mode": "plan",
            "permission_profile": "read_only",
            "plan_version_id": promoted_plan.id,
            "source_run_id": run.id,
            "source_run_input_id": row.id,
        },
        created_at=now,
        updated_at=now,
    )
    db.add(promoted)
    promoted_authority = AgentRunAuthorityModel(
        id=promoted.id,
        tenant_id=conversation.tenant_id,
        project_id=promoted.project_id,
        conversation_id=promoted.conversation_id,
        run_kind="plan",
        plan_run_id=promoted.id,
        plan_version_id=promoted.plan_version_id,
        idempotency_key=promoted.idempotency_key,
        message_id=promoted.message_id,
        request_message=promoted.request_message,
        status=promoted.status,
        revision=promoted.revision,
        permission_profile=promoted.permission_profile,
        authorization_snapshot=dict(promoted.authorization_snapshot),
        created_at=promoted.created_at,
        started_at=now,
        updated_at=promoted.updated_at,
    )
    db.add(promoted_authority)
    row.status = AgentRunInputStatus.PROMOTED_TO_PLAN
    row.promoted_run_id = promoted.id
    row.promotion_key = body.idempotency_key
    row.promoted_at = now
    row.updated_at = now
    await db.commit()

    base_container = cast(DIContainer, request.app.state.container)
    task = asyncio.create_task(
        _execute_approved_plan(
            base_container=base_container,
            run_id=promoted.id,
            conversation_id=promoted.conversation_id,
            project_id=promoted.project_id,
            tenant_id=conversation.tenant_id,
            user_id=current_user.id,
            message=promoted.request_message,
            message_id=promoted.message_id,
        ),
        name=f"promoted-run-input-{promoted.id}",
    )
    _PROMOTED_RUN_TASKS.add(task)
    task.add_done_callback(_PROMOTED_RUN_TASKS.discard)
    await db.refresh(row)
    return _promotion_response(
        row,
        conversation=conversation,
        source_run=run,
        created=True,
    )


__all__ = [
    "_PROMOTED_RUN_TASKS",
    "_RUN_INPUT_DISPATCH_LEASE",
    "RedisControlChannel",
    "_canonical_hash",
    "_dispatch_lease_is_active",
    "_dispatch_persisted_steer",
    "_input_ack",
    "_input_receipt",
    "_promotion_response",
    "_run_input_dispatch_rejection",
    "_validate_run_input_authorities",
    "create_run_input",
    "list_run_inputs",
    "promote_run_input",
    "router",
]
