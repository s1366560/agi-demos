"""Desktop-local run registration, event upload, and terminal settlement."""

from __future__ import annotations

from typing import Any, Literal, NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.artifact_service import ArtifactService
from src.application.services.local_run_protocol import (
    LocalArtifactWriter,
    LocalRunProtocolError,
    append_local_run_events,
    list_local_run_events,
    register_local_run,
    settle_local_run,
    stop_local_run,
)
from src.domain.ports.services.storage_service_port import UploadResult
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import Conversation, User
from src.infrastructure.i18n import gettext as _

from .run_authority_common import _load_scoped_run

router = APIRouter()


class _MemoryObjectStorage:
    """Process-local object store used when the app has not injected one.

    ``ArtifactService.create_artifact`` still runs. The redacted bytes also
    stay on the event row so a restart can replay them.
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def upload_file(
        self,
        file_content: bytes,
        object_key: str,
        content_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> UploadResult:
        del metadata
        self.objects[object_key] = file_content
        return UploadResult(
            object_key=object_key,
            size_bytes=len(file_content),
            content_type=content_type,
            etag="local-run",
        )

    async def generate_presigned_url(self, object_key: str, expiration_seconds: int) -> str:
        del expiration_seconds
        return f"https://local-run.invalid/{object_key}"


class _ServiceArtifactWriter:
    def __init__(self, service: ArtifactService) -> None:
        self._service = service

    async def create_artifact(
        self,
        *,
        file_content: bytes,
        filename: str,
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        source_tool: str | None,
        source_path: str | None,
        metadata: dict[str, Any],
    ) -> str:
        artifact = await self._service.create_artifact(
            file_content=file_content,
            filename=filename,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            source_tool=source_tool,
            source_path=source_path,
            metadata=metadata,
        )
        return artifact.id


class RegisterLocalRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str
    message: str
    execution_machine_id: str
    local_root_label: str
    permission_mode: Literal["ask", "automatic", "full_access"] | None = None


class LocalRunEventBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=1)
    kind: Literal[
        "user_message",
        "assistant_message",
        "tool_call",
        "tool_result",
        "log",
        "artifact",
        "error",
        "status",
    ]
    payload: dict[str, Any]


class LocalRunEventBatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_machine_id: str
    events: list[LocalRunEventBody]


class SettleLocalRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    status: Literal["completed", "failed", "cancelled"]
    execution_machine_id: str
    error: str | None = None


class StopLocalRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    execution_machine_id: str


def _raise_protocol(error: LocalRunProtocolError) -> NoReturn:
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": _(str(error))},
    ) from error


def _writer_for(request: Request) -> LocalArtifactWriter:
    injected = getattr(request.app.state, "local_run_artifact_writer", None)
    if injected is not None:
        return injected
    service = getattr(request.app.state, "artifact_service", None)
    if isinstance(service, ArtifactService):
        return _ServiceArtifactWriter(service)
    return _ServiceArtifactWriter(ArtifactService(storage_service=_MemoryObjectStorage()))


async def _owned_conversation(
    db: AsyncSession,
    *,
    conversation_id: str,
    user_id: str,
) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise HTTPException(
            status_code=404 if conversation is None else 403,
            detail=_("Agent run access denied"),
        )
    return conversation


@router.post("/conversations/{conversation_id}/local-runs")
async def post_local_run(
    conversation_id: str,
    body: RegisterLocalRunBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    x_agi_surface: str | None = Header(default=None),
) -> dict[str, Any]:
    conversation = await _owned_conversation(
        db, conversation_id=conversation_id, user_id=current_user.id
    )
    try:
        created = await register_local_run(
            db,
            conversation=conversation,
            user_id=current_user.id,
            surface=x_agi_surface,
            idempotency_key=body.idempotency_key,
            message=body.message,
            execution_machine_id=body.execution_machine_id,
            local_root_label=body.local_root_label,
            permission_mode=body.permission_mode,
        )
    except LocalRunProtocolError as error:
        _raise_protocol(error)
    return {
        "run_id": created.run_id,
        "revision": created.revision,
        "status": created.status,
        "permission_profile": created.permission_profile,
        "execution_target": "local",
        "execution_machine_id": created.execution_machine_id,
        "execution_environment_id": None,
        "local_root_label": created.local_root_label,
        "upload_state": created.upload_state,
    }


@router.post("/runs/{run_id}/events:batch")
async def post_local_run_events(
    run_id: str,
    body: LocalRunEventBatchBody,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    x_agi_surface: str | None = Header(default=None),
) -> dict[str, Any]:
    run, conversation = await _load_scoped_run(db, run_id=run_id, user_id=current_user.id)
    raw_size = len(body.model_dump_json().encode("utf-8"))
    try:
        receipt = await append_local_run_events(
            db,
            run=run,
            conversation=conversation,
            user_id=current_user.id,
            surface=x_agi_surface,
            execution_machine_id=body.execution_machine_id,
            events=[event.model_dump() for event in body.events],
            raw_size=raw_size,
            artifacts=_writer_for(request),
        )
    except LocalRunProtocolError as error:
        await db.rollback()
        _raise_protocol(error)
    return {
        "accepted_through_seq": receipt.accepted_through_seq,
        "revision": receipt.revision,
        "status": receipt.status,
        "idempotent": receipt.idempotent,
        "upload_state": receipt.upload_state,
    }


@router.patch("/runs/{run_id}/local-terminal")
async def patch_local_run_terminal(
    run_id: str,
    body: SettleLocalRunBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    x_agi_surface: str | None = Header(default=None),
) -> dict[str, Any]:
    run, conversation = await _load_scoped_run(
        db, run_id=run_id, user_id=current_user.id, lock=True
    )
    try:
        receipt = await settle_local_run(
            db,
            run=run,
            conversation=conversation,
            user_id=current_user.id,
            surface=x_agi_surface,
            expected_revision=body.expected_revision,
            status=body.status,
            execution_machine_id=body.execution_machine_id,
            error=body.error,
        )
    except LocalRunProtocolError as error:
        await db.rollback()
        _raise_protocol(error)
    return {
        "status": receipt.status,
        "revision": receipt.revision,
        "late_terminal": receipt.late_terminal,
        "upload_state": receipt.upload_state,
    }


@router.post("/runs/{run_id}/local-stop")
async def post_local_run_stop(
    run_id: str,
    body: StopLocalRunBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    x_agi_surface: str | None = Header(default=None),
) -> dict[str, Any]:
    run, conversation = await _load_scoped_run(
        db, run_id=run_id, user_id=current_user.id, lock=True
    )
    try:
        receipt = await stop_local_run(
            db,
            run=run,
            conversation=conversation,
            user_id=current_user.id,
            surface=x_agi_surface,
            expected_revision=body.expected_revision,
            execution_machine_id=body.execution_machine_id,
        )
    except LocalRunProtocolError as error:
        await db.rollback()
        _raise_protocol(error)
    return {
        "status": receipt.status,
        "revision": receipt.revision,
        "late_terminal": receipt.late_terminal,
        "upload_state": receipt.upload_state,
    }


@router.get("/runs/{run_id}/local-events")
async def get_local_run_events(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    run, conversation = await _load_scoped_run(db, run_id=run_id, user_id=current_user.id)
    try:
        events = await list_local_run_events(
            db,
            run=run,
            conversation=conversation,
            user_id=current_user.id,
        )
    except LocalRunProtocolError as error:
        _raise_protocol(error)
    return {
        "run_id": run.id,
        "status": run.status,
        "revision": run.revision,
        "execution_target": run.execution_target,
        "local_root_label": run.local_root_label,
        "events": events,
    }
