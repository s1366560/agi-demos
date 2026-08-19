"""Cloud task-session saga with Avernet Workspace Core as Workspace authority."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.task_sessions import CreateTaskSessionRequest
from src.infrastructure.adapters.primary.web.workspace_authority import (
    workspace_core_unavailable_error,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    TaskSessionCreationReceiptModel,
    UserProject,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.workspace_core.client import (
    WorkspaceCoreClient,
    WorkspaceCoreClientError,
    WorkspaceCoreConflictError,
    WorkspaceCoreForbiddenError,
    WorkspaceCoreNotFoundError,
    WorkspaceCoreTaskSessionRequest,
    WorkspaceCoreTaskSessionResponse,
)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/projects/{project_id}/task-sessions",
    tags=["task-sessions"],
)

_TASK_SESSION_NAMESPACE = uuid.UUID("f583658d-976f-4589-a385-750a3b0b8e74")


@router.get("/capabilities")
async def avernet_task_session_capabilities() -> dict[str, Any]:
    """Advertise the Core-owned atomic task-session command."""
    return {
        "schema_version": 2,
        "atomic_creation": True,
        "initial_conversation_mode": "workspace",
        "initial_plan_mode": "plan",
        "workspace_agent_policy": True,
        "workspace_authority": "avernet",
        "capability_version": "avernet-task-session-v1",
    }


@router.post("", response_model=None)
async def create_avernet_task_session(
    tenant_id: str,
    project_id: str,
    body: CreateTaskSessionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any] | JSONResponse:
    """Commit Core state first, then recoverably correlate the platform Conversation."""
    project_membership_role = await _require_project_access(db, current_user, tenant_id, project_id)
    client = getattr(request.app.state, "workspace_core_client", None)
    if not isinstance(client, WorkspaceCoreClient):
        raise workspace_core_unavailable_error()

    actor_id = str(current_user.id)
    payload_hash = _payload_hash(body)
    conversation_id = _stable_id(
        "conversation",
        tenant_id=tenant_id,
        project_id=project_id,
        actor_id=actor_id,
        idempotency_key=body.idempotency_key,
    )
    message_id = _stable_id(
        "message",
        tenant_id=tenant_id,
        project_id=project_id,
        actor_id=actor_id,
        idempotency_key=body.idempotency_key,
    )
    workspace = body.workspace.model_dump(mode="json", exclude_none=True)
    if body.workspace.kind == "create":
        workspace["workspace_id"] = _stable_id(
            "workspace",
            tenant_id=tenant_id,
            project_id=project_id,
            actor_id=actor_id,
            idempotency_key=body.idempotency_key,
        )
    expected_workspace_id = workspace.get("workspace_id")
    if not isinstance(expected_workspace_id, str):
        raise HTTPException(status_code=422, detail=_("Workspace is invalid"))
    journal = await _reserve_saga_journal(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        actor_id=actor_id,
        idempotency_key=body.idempotency_key,
        payload_hash=payload_hash,
        workspace_id=expected_workspace_id,
    )
    core_request = WorkspaceCoreTaskSessionRequest(
        workspace=workspace,
        conversation_id=conversation_id,
        initial_message={
            "message_id": message_id,
            "content": body.initial_message.content.strip(),
            "context_items": [
                item.model_dump(mode="json", exclude_none=True)
                for item in body.initial_message.context_items
            ],
        },
        workspace_policy=(
            body.workspace_policy.model_dump(mode="json")
            if body.workspace_policy is not None
            else None
        ),
        capability_mode=body.conversation.capability_mode,
    )
    try:
        core_response = await client.create_task_session(
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=actor_id,
            user_email=current_user.email,
            idempotency_key=body.idempotency_key,
            request=core_request,
            project_membership_role=project_membership_role,
        )
        workspace_id = _validate_core_response(
            core_response,
            tenant_id=tenant_id,
            project_id=project_id,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        _validate_saga_journal(
            journal,
            tenant_id=tenant_id,
            project_id=project_id,
            actor_id=actor_id,
            idempotency_key=body.idempotency_key,
            payload_hash=payload_hash,
            workspace_id=workspace_id,
        )
    except WorkspaceCoreConflictError:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "code": "TASK_SESSION_IDEMPOTENCY_CONFLICT",
                "detail": _("Task session idempotency conflict"),
            },
        )
    except WorkspaceCoreForbiddenError as exc:
        raise HTTPException(status_code=403, detail=_("Workspace access required")) from exc
    except WorkspaceCoreNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_("Workspace not found")) from exc
    except WorkspaceCoreClientError as exc:
        raise workspace_core_unavailable_error() from exc

    await _record_core_commit(
        db,
        journal=journal,
        response=core_response,
        workspace_id=workspace_id,
        message_id=message_id,
    )
    conversation = await _complete_platform_saga(
        db,
        journal=journal,
        conversation_id=conversation_id,
        title=body.conversation.title.strip(),
        capability_mode=body.conversation.capability_mode,
        payload_hash=payload_hash,
        receipt_id=core_response.receipt_id,
        message_id=message_id,
    )
    return {
        "replayed": core_response.replayed,
        "workspace": core_response.workspace,
        "conversation": _conversation_json(conversation),
        "initial_message": core_response.initial_message,
        "policy": core_response.policy,
        "capability_version": core_response.capability_version,
    }


async def _require_project_access(
    db: AsyncSession,
    current_user: User,
    tenant_id: str,
    project_id: str,
) -> str | None:
    project = (
        await db.execute(
            refresh_select_statement(
                select(Project.id).where(Project.id == project_id, Project.tenant_id == tenant_id)
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail=_("Project not found"))
    if getattr(current_user, "is_superuser", False):
        return None
    role = (
        await db.execute(
            refresh_select_statement(
                select(UserProject.role).where(
                    UserProject.project_id == project_id,
                    UserProject.user_id == current_user.id,
                )
            )
        )
    ).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=403, detail=_("Access denied"))
    return str(role)


def _stable_id(
    kind: str,
    *,
    tenant_id: str,
    project_id: str,
    actor_id: str,
    idempotency_key: str,
) -> str:
    identity = ":".join((kind, tenant_id, project_id, actor_id, idempotency_key))
    return str(uuid.uuid5(_TASK_SESSION_NAMESPACE, identity))


def _payload_hash(body: CreateTaskSessionRequest) -> str:
    encoded = json.dumps(
        body.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate_core_response(
    response: WorkspaceCoreTaskSessionResponse,
    *,
    tenant_id: str,
    project_id: str,
    conversation_id: str,
    message_id: str,
) -> str:
    workspace_id = response.workspace.get("id")
    if (
        not isinstance(workspace_id, str)
        or response.workspace.get("tenant_id") != tenant_id
        or response.workspace.get("project_id") != project_id
        or response.initial_message.get("id") != message_id
        or response.initial_message.get("workspace_id") != workspace_id
        or not isinstance(response.initial_message.get("metadata"), dict)
        or response.initial_message["metadata"].get("conversation_id") != conversation_id
    ):
        raise WorkspaceCoreClientError("Workspace Core returned an invalid task-session scope")
    return workspace_id


async def _load_conversation(db: AsyncSession, conversation_id: str) -> Conversation | None:
    result = await db.execute(
        refresh_select_statement(select(Conversation).where(Conversation.id == conversation_id))
    )
    return result.scalar_one_or_none()


async def _load_saga_journal(
    db: AsyncSession,
    *,
    tenant_id: str,
    project_id: str,
    actor_id: str,
    idempotency_key: str,
) -> TaskSessionCreationReceiptModel | None:
    result = await db.execute(
        refresh_select_statement(
            select(TaskSessionCreationReceiptModel).where(
                TaskSessionCreationReceiptModel.actor_user_id == actor_id,
                TaskSessionCreationReceiptModel.tenant_id == tenant_id,
                TaskSessionCreationReceiptModel.project_id == project_id,
                TaskSessionCreationReceiptModel.idempotency_key == idempotency_key,
            )
        )
    )
    return result.scalar_one_or_none()


async def _record_core_commit(
    db: AsyncSession,
    *,
    journal: TaskSessionCreationReceiptModel,
    response: WorkspaceCoreTaskSessionResponse,
    workspace_id: str,
    message_id: str,
) -> None:
    journal.workspace_id = workspace_id
    journal.initial_message_id = message_id
    journal.core_receipt_id = response.receipt_id
    journal.status = "core_committed"
    journal.last_error = None
    journal.response_json = response.model_dump(mode="json")
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _platform_saga_unavailable() from exc


async def _complete_platform_saga(
    db: AsyncSession,
    *,
    journal: TaskSessionCreationReceiptModel,
    conversation_id: str,
    title: str,
    capability_mode: str,
    payload_hash: str,
    receipt_id: str,
    message_id: str,
) -> Conversation:
    tenant_id = journal.tenant_id
    project_id = journal.project_id
    actor_id = journal.actor_user_id
    workspace_id = journal.workspace_id
    idempotency_key = journal.idempotency_key
    conversation = await _load_conversation(db, conversation_id)
    if conversation is None:
        conversation = _new_conversation(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            project_id=project_id,
            actor_id=actor_id,
            title=title,
            capability_mode=capability_mode,
            workspace_id=workspace_id,
            receipt_id=receipt_id,
            message_id=message_id,
            payload_hash=payload_hash,
            idempotency_key=idempotency_key,
        )
        db.add(conversation)
    _validate_conversation_saga(
        conversation,
        tenant_id=tenant_id,
        project_id=project_id,
        actor_id=actor_id,
        workspace_id=workspace_id,
        payload_hash=payload_hash,
        receipt_id=receipt_id,
    )
    journal.conversation_id = conversation_id
    journal.status = "completed"
    journal.last_error = None
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        persisted = await _load_conversation(db, conversation_id)
        if persisted is None:
            raise _platform_saga_unavailable() from exc
        _validate_conversation_saga(
            persisted,
            tenant_id=tenant_id,
            project_id=project_id,
            actor_id=actor_id,
            workspace_id=workspace_id,
            payload_hash=payload_hash,
            receipt_id=receipt_id,
        )
        persisted_journal = await _load_saga_journal(
            db,
            tenant_id=tenant_id,
            project_id=project_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
        if persisted_journal is None:
            raise _platform_saga_unavailable() from exc
        _validate_saga_journal(
            persisted_journal,
            tenant_id=tenant_id,
            project_id=project_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            workspace_id=workspace_id,
        )
        persisted_journal.conversation_id = conversation_id
        persisted_journal.status = "completed"
        persisted_journal.last_error = None
        try:
            await db.commit()
        except Exception as journal_exc:
            await db.rollback()
            raise _platform_saga_unavailable() from journal_exc
        conversation = persisted
    except Exception as exc:
        await db.rollback()
        raise _platform_saga_unavailable() from exc
    return conversation


async def _reserve_saga_journal(
    db: AsyncSession,
    *,
    tenant_id: str,
    project_id: str,
    actor_id: str,
    idempotency_key: str,
    payload_hash: str,
    workspace_id: str,
) -> TaskSessionCreationReceiptModel:
    journal = await _load_saga_journal(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
    )
    if journal is None:
        journal = TaskSessionCreationReceiptModel(
            id=_stable_id(
                "journal",
                tenant_id=tenant_id,
                project_id=project_id,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
            ),
            actor_user_id=actor_id,
            tenant_id=tenant_id,
            project_id=project_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            workspace_id=workspace_id,
            status="pending",
            response_json={},
        )
        db.add(journal)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            journal = await _load_saga_journal(
                db,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
            )
            if journal is None:
                raise _platform_saga_unavailable() from exc
    _validate_saga_journal(
        journal,
        tenant_id=tenant_id,
        project_id=project_id,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        workspace_id=workspace_id,
    )
    return journal


def _validate_saga_journal(
    journal: TaskSessionCreationReceiptModel,
    *,
    tenant_id: str,
    project_id: str,
    actor_id: str,
    idempotency_key: str,
    payload_hash: str,
    workspace_id: str,
) -> None:
    if (
        journal.tenant_id != tenant_id
        or journal.project_id != project_id
        or journal.actor_user_id != actor_id
        or journal.idempotency_key != idempotency_key
        or journal.payload_hash != payload_hash
        or journal.workspace_id != workspace_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_("Task session idempotency conflict"),
        )


def _platform_saga_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "TASK_SESSION_SAGA_RETRYABLE",
            "reason": "task_session_platform_commit_failed",
        },
    )


def _new_conversation(
    *,
    conversation_id: str,
    tenant_id: str,
    project_id: str,
    actor_id: str,
    title: str,
    capability_mode: str,
    workspace_id: str,
    receipt_id: str,
    message_id: str,
    payload_hash: str,
    idempotency_key: str,
) -> Conversation:
    now = datetime.now(UTC)
    return Conversation(
        id=conversation_id,
        project_id=project_id,
        tenant_id=tenant_id,
        user_id=actor_id,
        title=title,
        status="active",
        agent_config={
            "selected_agent_id": "builtin:all-access",
            "capability_mode": capability_mode,
        },
        meta={
            "source": "task_session",
            "task_session_saga": {
                "status": "committed",
                "receipt_id": receipt_id,
                "payload_hash": payload_hash,
                "idempotency_key": idempotency_key,
                "initial_message_id": message_id,
            },
        },
        message_count=1,
        current_mode="plan",
        conversation_mode="workspace",
        workspace_id=workspace_id,
        created_at=now,
        updated_at=now,
    )


def _validate_conversation_saga(
    conversation: Conversation,
    *,
    tenant_id: str,
    project_id: str,
    actor_id: str,
    workspace_id: str,
    payload_hash: str,
    receipt_id: str,
) -> None:
    saga = conversation.meta.get("task_session_saga") if isinstance(conversation.meta, dict) else None
    if (
        conversation.tenant_id != tenant_id
        or conversation.project_id != project_id
        or conversation.user_id != actor_id
        or conversation.workspace_id != workspace_id
        or not isinstance(saga, dict)
        or saga.get("status") != "committed"
        or saga.get("payload_hash") != payload_hash
        or saga.get("receipt_id") != receipt_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_("Task session idempotency conflict"),
        )


def _conversation_json(conversation: Conversation) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "tenant_id": conversation.tenant_id,
        "project_id": conversation.project_id,
        "user_id": conversation.user_id,
        "title": conversation.title,
        "status": conversation.status,
        "message_count": conversation.message_count,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
        "summary": conversation.summary,
        "agent_config": conversation.agent_config,
        "metadata": conversation.meta,
        "conversation_mode": conversation.conversation_mode,
        "current_mode": conversation.current_mode,
        "workspace_id": conversation.workspace_id,
        "linked_workspace_task_id": conversation.linked_workspace_task_id,
        "participant_agents": conversation.participant_agents,
        "coordinator_agent_id": conversation.coordinator_agent_id,
        "focused_agent_id": conversation.focused_agent_id,
    }


def register_task_session_routes(app: FastAPI) -> None:
    """Register the Avernet-owned task-session authority."""
    app.include_router(router)
