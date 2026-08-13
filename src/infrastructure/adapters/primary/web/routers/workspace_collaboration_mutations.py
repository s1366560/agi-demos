"""Canonical Workspace Collaboration revision and mutation routes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal, TypedDict, cast

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.workspace_collaboration_capabilities import (
    WorkspaceCollaborationSurface,
)
from src.application.schemas.workspace_cyber_schemas import (
    CyberObjectiveCreate,
    CyberObjectiveUpdate,
)
from src.application.services.workspace_collaboration_authority import (
    WORKSPACE_COLLABORATION_CONTRACT_VERSION,
    WorkspaceCollaborationActor,
    WorkspaceCollaborationAuthorityCorruptError,
    WorkspaceCollaborationIdempotencyConflictError,
    WorkspaceCollaborationMutationCommand,
    WorkspaceCollaborationMutationError,
    WorkspaceCollaborationMutationReceipt,
    WorkspaceCollaborationMutationService,
    WorkspaceCollaborationRevisionConflictError,
    WorkspaceCollaborationTargetNotFoundError,
)
from src.domain.model.workspace.actor_identity import ActorIdentity
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_actor,
    get_current_user,
)
from src.infrastructure.adapters.primary.web.routers import (
    blackboard,
    cyber_objectives,
    workspace_tasks,
)
from src.infrastructure.adapters.primary.web.routers.workspace_access import (
    require_workspace_access,
)
from src.infrastructure.adapters.primary.web.routers.workspace_collaboration_payload import (
    require_workspace_payload_keys as _require_payload_keys,
    workspace_payload_id as _payload_id,
    workspace_payload_model as _payload_model,
)
from src.infrastructure.adapters.primary.web.routers.workspace_collaboration_secondary_dispatch import (
    dispatch_secondary_workspace_mutation,
)
from src.infrastructure.adapters.primary.web.routers.workspace_collaboration_transaction import (
    WorkspaceCollaborationUnitOfWork,
)
from src.infrastructure.adapters.primary.web.routers.workspace_collaboration_upload import (
    require_bounded_upload_content_length,
    stage_workspace_upload_request,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _
from src.infrastructure.workspace_core.legacy_runtime import legacy_workspace_runtime_retired

router = APIRouter(prefix="/{workspace_id}/collaboration", tags=["workspace-collaboration"])

ExpectedRevisionHeader = Annotated[int, Header(alias="X-Expected-Revision", ge=0)]
IdempotencyKeyHeader = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=256),
]


class _ScopedRouteArguments(TypedDict):
    tenant_id: str
    project_id: str
    workspace_id: str
    request: Request
    current_user: User
    db: AsyncSession


class _WorkspaceTaskRouteArguments(TypedDict):
    workspace_id: str
    request: Request
    current_user: User
    db: AsyncSession


class WorkspaceCollaborationMutationRequest(BaseModel):
    """One fail-closed surface mutation command."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["2.0.0"]
    surface: WorkspaceCollaborationSurface
    action: str = Field(min_length=1, max_length=64)
    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=256)
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkspaceCollaborationAuthorityResponse(BaseModel):
    """Canonical monotonic revision for a scoped workspace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["2.0.0"] = WORKSPACE_COLLABORATION_CONTRACT_VERSION
    tenant_id: str
    project_id: str
    workspace_id: str
    revision: int
    cursor: str


class WorkspaceCollaborationMutationReceiptResponse(BaseModel):
    """Stable committed mutation receipt returned to Desktop."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["2.0.0"] = WORKSPACE_COLLABORATION_CONTRACT_VERSION
    receipt_id: str
    workspace_id: str
    surface: WorkspaceCollaborationSurface
    action: str
    revision: int
    duplicate: bool


def get_workspace_collaboration_mutation_service(
    db: AsyncSession = Depends(get_db),
) -> WorkspaceCollaborationMutationService:
    """Reject the retired platform Collaboration mutation authority."""
    del db
    legacy_workspace_runtime_retired("Collaboration mutation service")


@router.get(
    "/authority",
    response_model=WorkspaceCollaborationAuthorityResponse,
)
async def get_workspace_collaboration_authority(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: WorkspaceCollaborationMutationService = Depends(
        get_workspace_collaboration_mutation_service
    ),
) -> WorkspaceCollaborationAuthorityResponse:
    """Read the canonical revision after verifying the full workspace scope."""
    await require_workspace_access(
        db,
        current_user,
        tenant_id,
        project_id,
        workspace_id,
    )
    actor = _actor(
        tenant_id=tenant_id,
        project_id=project_id,
        workspace_id=workspace_id,
        current_user=current_user,
    )
    try:
        revision = await service.current_revision(actor=actor)
    except WorkspaceCollaborationMutationError as exc:
        raise _authority_http_error(exc) from exc
    return _authority_response(actor=actor, revision=revision)


@router.post(
    "/mutations",
    response_model=WorkspaceCollaborationMutationReceiptResponse,
)
async def mutate_workspace_collaboration_surface(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    body: WorkspaceCollaborationMutationRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    expected_revision: ExpectedRevisionHeader,
    idempotency_key: IdempotencyKeyHeader,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: WorkspaceCollaborationMutationService = Depends(
        get_workspace_collaboration_mutation_service
    ),
) -> WorkspaceCollaborationMutationReceiptResponse:
    """Reserve, execute, and finalize one canonical surface command."""
    if body.expected_revision != expected_revision or body.idempotency_key != idempotency_key:
        raise _invalid_command("workspace_collaboration_authority_header_mismatch")
    actor = _actor(
        tenant_id=tenant_id,
        project_id=project_id,
        workspace_id=workspace_id,
        current_user=current_user,
    )
    command = _command_from_request(body)
    await require_workspace_access(
        db,
        current_user,
        tenant_id,
        project_id,
        workspace_id,
        require_editor=True,
    )
    return await _execute_command(
        actor=actor,
        command=command,
        request=request,
        background_tasks=background_tasks,
        current_user=current_user,
        db=db,
        service=service,
    )


@router.post(
    "/mutations/files/upload",
    response_model=WorkspaceCollaborationMutationReceiptResponse,
)
async def upload_workspace_collaboration_file(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    request: Request,
    expected_revision: ExpectedRevisionHeader,
    idempotency_key: IdempotencyKeyHeader,
    current_user: User = Depends(get_current_user),
    current_actor: ActorIdentity = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
    service: WorkspaceCollaborationMutationService = Depends(
        get_workspace_collaboration_mutation_service
    ),
) -> WorkspaceCollaborationMutationReceiptResponse:
    """Upload with content-bound idempotency while keeping file bytes out of JSON."""
    unit_of_work = WorkspaceCollaborationUnitOfWork(db, background_tasks=None)
    require_bounded_upload_content_length(request)
    await unit_of_work.prepare()
    await require_workspace_access(
        db,
        current_user,
        tenant_id,
        project_id,
        workspace_id,
        require_editor=True,
    )
    staged = await stage_workspace_upload_request(request)
    actor = _actor(
        tenant_id=tenant_id,
        project_id=project_id,
        workspace_id=workspace_id,
        current_user=current_user,
    )
    command = WorkspaceCollaborationMutationCommand(
        contract_version=WORKSPACE_COLLABORATION_CONTRACT_VERSION,
        surface="files",
        action="upload_file",
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
        payload={
            "parent_path": staged.parent_path,
            "file_name": staged.filename,
            "content_type": staged.content_type,
            "size_bytes": staged.size_bytes,
            "sha256": staged.checksum_sha256,
        },
    )
    try:
        reserved = await service.reserve(actor=actor, command=command)
        if reserved.dispatch_required:
            await blackboard.upload_staged_file(
                tenant_id=tenant_id,
                project_id=project_id,
                workspace_id=workspace_id,
                request=request,
                staged_path=staged.path,
                parent_path=staged.parent_path,
                filename=staged.filename,
                size_bytes=staged.size_bytes,
                checksum_sha256=staged.checksum_sha256,
                current_user=current_user,
            current_actor=current_actor,
            db=unit_of_work.session,
        )
        finalized = await service.finalize(
            actor=actor,
            command=command,
            duplicate=reserved.duplicate,
        )
        await unit_of_work.commit()
    except HTTPException:
        await unit_of_work.rollback()
        raise
    except (ValueError, ValidationError) as exc:
        await unit_of_work.rollback()
        raise _invalid_command("workspace_collaboration_payload_invalid") from exc
    except WorkspaceCollaborationMutationError as exc:
        await unit_of_work.rollback()
        raise _authority_http_error(exc) from exc
    finally:
        staged.path.unlink(missing_ok=True)
    return _receipt_response(finalized)


async def _execute_command(
    *,
    actor: WorkspaceCollaborationActor,
    command: WorkspaceCollaborationMutationCommand,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User,
    db: AsyncSession,
    service: WorkspaceCollaborationMutationService,
) -> WorkspaceCollaborationMutationReceiptResponse:
    unit_of_work = WorkspaceCollaborationUnitOfWork(db, background_tasks)
    try:
        await unit_of_work.prepare()
        reserved = await service.reserve(actor=actor, command=command)
        if reserved.dispatch_required:
            await _dispatch_mutation(
                actor=actor,
                command=command,
                request=request,
                background_tasks=unit_of_work.background_tasks,
                current_user=current_user,
                db=unit_of_work.session,
            )
        finalized = await service.finalize(
            actor=actor,
            command=command,
            duplicate=reserved.duplicate,
        )
        await unit_of_work.commit()
    except HTTPException:
        await unit_of_work.rollback()
        raise
    except (ValueError, ValidationError) as exc:
        await unit_of_work.rollback()
        raise _invalid_command("workspace_collaboration_payload_invalid") from exc
    except WorkspaceCollaborationMutationError as exc:
        await unit_of_work.rollback()
        raise _authority_http_error(exc) from exc
    return _receipt_response(finalized)


async def _dispatch_mutation(
    *,
    actor: WorkspaceCollaborationActor,
    command: WorkspaceCollaborationMutationCommand,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User,
    db: AsyncSession,
) -> None:
    if command.action in {
        "create_task",
        "update_task",
        "delete_task",
        "assign_task_agent",
        "unassign_task_agent",
        "apply_task_recovery_action",
    }:
        await _dispatch_task(
            actor=actor,
            action=command.action,
            payload=command.payload,
            request=request,
            current_user=current_user,
            db=db,
        )
    elif command.surface == "goals":
        await _dispatch_goal(
            actor=actor,
            action=command.action,
            payload=command.payload,
            request=request,
            current_user=current_user,
            db=db,
        )
    elif command.surface == "discussion":
        await _dispatch_discussion(
            actor=actor,
            action=command.action,
            payload=command.payload,
            request=request,
            current_user=current_user,
            db=db,
        )
    elif await dispatch_secondary_workspace_mutation(
        actor=actor,
        command=command,
        request=request,
        background_tasks=background_tasks,
        current_user=current_user,
        db=db,
    ):
        pass
    else:
        raise ValueError("surface action is unavailable")


async def _dispatch_goal(
    *,
    actor: WorkspaceCollaborationActor,
    action: str,
    payload: Mapping[str, object],
    request: Request,
    current_user: User,
    db: AsyncSession,
) -> None:
    common: _ScopedRouteArguments = {
        "tenant_id": actor.tenant_id,
        "project_id": actor.project_id,
        "workspace_id": actor.workspace_id,
        "request": request,
        "current_user": current_user,
        "db": db,
    }
    if action == "create_objective":
        await cyber_objectives.create_objective(
            payload=_payload_model(
                CyberObjectiveCreate,
                payload,
            ),
            **common,
        )
    elif action == "update_objective":
        await cyber_objectives.update_objective(
            objective_id=_payload_id(payload, "objective_id"),
            payload=_payload_model(
                CyberObjectiveUpdate,
                payload,
                excluded=("objective_id",),
            ),
            **common,
        )
    elif action == "delete_objective":
        objective_id = _payload_id(payload, "objective_id")
        _require_payload_keys(payload, {"objective_id"})
        await cyber_objectives.delete_objective(objective_id=objective_id, **common)
    elif action == "project_objective_to_task":
        await cyber_objectives.project_objective_to_task(
            objective_id=_payload_id(payload, "objective_id"),
            response=Response(),
            body=_payload_model(
                cyber_objectives.ProjectObjectiveToTaskRequest,
                payload,
                excluded=("objective_id",),
            ),
            **common,
        )
    else:
        raise ValueError("goal action is unavailable")


async def _dispatch_task(
    *,
    actor: WorkspaceCollaborationActor,
    action: str,
    payload: Mapping[str, object],
    request: Request,
    current_user: User,
    db: AsyncSession,
) -> None:
    common: _WorkspaceTaskRouteArguments = {
        "workspace_id": actor.workspace_id,
        "request": request,
        "current_user": current_user,
        "db": db,
    }
    if action == "create_task":
        await workspace_tasks.create_workspace_task(
            body=_payload_model(workspace_tasks.WorkspaceTaskCreateRequest, payload),
            **common,
        )
        return
    task_id = _payload_id(payload, "task_id")
    if action == "update_task":
        await workspace_tasks.update_workspace_task(
            task_id=task_id,
            body=_payload_model(
                workspace_tasks.WorkspaceTaskUpdateRequest,
                payload,
                excluded=("task_id",),
            ),
            **common,
        )
    elif action == "delete_task":
        _require_payload_keys(payload, {"task_id"})
        await workspace_tasks.delete_workspace_task(task_id=task_id, **common)
    elif action == "assign_task_agent":
        await workspace_tasks.assign_workspace_task_to_agent(
            task_id=task_id,
            body=_payload_model(
                workspace_tasks.AssignAgentRequest,
                payload,
                excluded=("task_id",),
            ),
            **common,
        )
    elif action == "unassign_task_agent":
        _require_payload_keys(payload, {"task_id"})
        await workspace_tasks.unassign_workspace_task_from_agent(
            task_id=task_id,
            **common,
        )
    elif action == "apply_task_recovery_action":
        await workspace_tasks.apply_workspace_task_recovery_action(
            task_id=task_id,
            body=_payload_model(
                workspace_tasks.TaskRecoveryActionRequest,
                payload,
                excluded=("task_id",),
            ),
            **common,
        )
    else:
        raise ValueError("task action is unavailable")


async def _dispatch_discussion(
    *,
    actor: WorkspaceCollaborationActor,
    action: str,
    payload: Mapping[str, object],
    request: Request,
    current_user: User,
    db: AsyncSession,
) -> None:
    common: _ScopedRouteArguments = {
        "tenant_id": actor.tenant_id,
        "project_id": actor.project_id,
        "workspace_id": actor.workspace_id,
        "request": request,
        "current_user": current_user,
        "db": db,
    }
    if action == "create_post":
        await blackboard.create_post(
            payload=_payload_model(blackboard.BlackboardPostCreateRequest, payload),
            **common,
        )
        return
    post_id = _payload_id(payload, "post_id")
    if action == "update_post":
        await blackboard.update_post(
            post_id=post_id,
            payload=_payload_model(
                blackboard.BlackboardPostUpdateRequest,
                payload,
                excluded=("post_id",),
            ),
            **common,
        )
    elif action == "delete_post":
        _require_payload_keys(payload, {"post_id"})
        await blackboard.delete_post(post_id=post_id, **common)
    elif action in {"pin_post", "unpin_post"}:
        _require_payload_keys(payload, {"post_id"})
        handler = blackboard.pin_post if action == "pin_post" else blackboard.unpin_post
        await handler(post_id=post_id, **common)
    elif action == "create_reply":
        await blackboard.create_reply(
            post_id=post_id,
            payload=_payload_model(
                blackboard.BlackboardReplyCreateRequest,
                payload,
                excluded=("post_id",),
            ),
            **common,
        )
    elif action in {"update_reply", "delete_reply"}:
        reply_id = _payload_id(payload, "reply_id")
        if action == "update_reply":
            await blackboard.update_reply(
                post_id=post_id,
                reply_id=reply_id,
                payload=_payload_model(
                    blackboard.BlackboardReplyUpdateRequest,
                    payload,
                    excluded=("post_id", "reply_id"),
                ),
                **common,
            )
        else:
            _require_payload_keys(payload, {"post_id", "reply_id"})
            await blackboard.delete_reply(
                post_id=post_id,
                reply_id=reply_id,
                **common,
            )
    else:
        raise ValueError("discussion action is unavailable")


def _actor(
    *,
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    current_user: User,
) -> WorkspaceCollaborationActor:
    return WorkspaceCollaborationActor(
        tenant_id=tenant_id,
        project_id=project_id,
        workspace_id=workspace_id,
        user_id=current_user.id,
    )


def _command_from_request(
    body: WorkspaceCollaborationMutationRequest,
) -> WorkspaceCollaborationMutationCommand:
    return WorkspaceCollaborationMutationCommand(
        contract_version=body.contract_version,
        surface=body.surface,
        action=body.action,
        expected_revision=body.expected_revision,
        idempotency_key=body.idempotency_key,
        payload=body.payload,
    )


def _authority_response(
    *,
    actor: WorkspaceCollaborationActor,
    revision: int,
) -> WorkspaceCollaborationAuthorityResponse:
    return WorkspaceCollaborationAuthorityResponse(
        tenant_id=actor.tenant_id,
        project_id=actor.project_id,
        workspace_id=actor.workspace_id,
        revision=revision,
        cursor=f"workspace:{actor.workspace_id}:revision:{revision}",
    )


def _receipt_response(
    receipt: WorkspaceCollaborationMutationReceipt,
) -> WorkspaceCollaborationMutationReceiptResponse:
    if receipt.revision is None:
        raise _authority_http_error(
            WorkspaceCollaborationAuthorityCorruptError(
                "Workspace Collaboration receipt was not committed"
            )
        )
    return WorkspaceCollaborationMutationReceiptResponse(
        receipt_id=receipt.receipt_id,
        workspace_id=receipt.workspace_id,
        surface=cast(WorkspaceCollaborationSurface, receipt.surface),
        action=receipt.action,
        revision=receipt.revision,
        duplicate=receipt.duplicate,
    )


def _invalid_command(reason_code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "reason_code": reason_code,
            "message": _("Invalid Workspace Collaboration mutation"),
        },
    )


def _authority_http_error(exc: WorkspaceCollaborationMutationError) -> HTTPException:
    detail: dict[str, object] = {
        "reason_code": exc.reason_code,
        "message": _("Workspace Collaboration mutation rejected"),
    }
    if isinstance(exc, WorkspaceCollaborationRevisionConflictError):
        detail["expected_revision"] = exc.expected_revision
        detail["current_revision"] = exc.current_revision
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    if isinstance(exc, WorkspaceCollaborationIdempotencyConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    if isinstance(exc, WorkspaceCollaborationTargetNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail)
