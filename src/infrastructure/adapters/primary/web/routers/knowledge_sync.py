"""Uninstalled sync router factory for a future generation-pinned application.

No router singleton is exported and no root/legacy service fallback is allowed.
The owner must supply a request-scoped application and transaction commit.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from src.application.services.knowledge_sync_service import KnowledgeSyncApplication
from src.domain.model.knowledge_sync.contracts import (
    MAX_REVISION,
    KnowledgeSyncError,
    KnowledgeSyncResolution,
    MemorySyncContent,
    MemorySyncMutation,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _


class SyncContentBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=1_048_576)
    content_type: Literal["text", "document", "image", "video"] = "text"
    tags: list[str] = Field(default_factory=list, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: Literal["ENABLED", "DISABLED"] = "ENABLED"

    def domain(self) -> MemorySyncContent:
        return MemorySyncContent(
            title=self.title,
            content=self.content,
            content_type=self.content_type,
            tags=tuple(self.tags),
            metadata_json=json.dumps(self.metadata),
            status=self.status,
        )


class SyncMutationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    change_id: str
    operation: Literal["create", "update", "delete"]
    memory_id: str
    expected_revision: int = Field(ge=0, lt=MAX_REVISION)
    content: SyncContentBody | None = None


class SyncResolutionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    change_id: str
    expected_current_revision: int = Field(ge=0, le=MAX_REVISION)
    decision: Literal["keep_current", "use_proposed", "merged", "keep_both"]
    content: SyncContentBody | None = None


def error_response(error: KnowledgeSyncError) -> JSONResponse:
    if error.code in {"knowledge_sync_not_enrolled", "knowledge_sync_fence_missing"}:
        status = 503
    elif error.code == "knowledge_sync_forbidden":
        status = 403
    elif error.code == "knowledge_sync_conflict_not_found":
        status = 404
    elif error.code in {
        "knowledge_sync_write_conflict",
        "knowledge_sync_id_collision",
        "knowledge_sync_idempotency_conflict",
        "knowledge_sync_conflict_pending",
        "knowledge_sync_conflict_resolved",
        "knowledge_sync_resolution_stale",
    }:
        status = 409
    else:
        status = 422
    return JSONResponse(
        status_code=status,
        content={
            "detail": {"code": error.code, "message": _("Knowledge synchronization request failed")}
        },
    )


def create_knowledge_sync_router(application_dependency: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/knowledge-sync", tags=["knowledge-sync"])

    async def changes(
        project_id: str,
        after: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        application: KnowledgeSyncApplication = Depends(application_dependency),
        user: User = Depends(get_current_user),
    ) -> JSONResponse:
        try:
            scope = await application.service.resolve_scope(user.id, project_id)
            page = await application.service.changes(scope, after, limit)
            return JSONResponse(content=page.to_dict())
        except KnowledgeSyncError as error:
            return error_response(error)

    async def mutate(
        project_id: str,
        body: SyncMutationBody,
        application: KnowledgeSyncApplication = Depends(application_dependency),
        user: User = Depends(get_current_user),
    ) -> JSONResponse:
        try:
            scope = await application.service.resolve_scope(user.id, project_id)
            outcome = await application.service.mutate(
                scope,
                body.change_id,
                MemorySyncMutation(
                    operation=body.operation,
                    memory_id=body.memory_id,
                    expected_revision=body.expected_revision,
                    content=body.content.domain() if body.content else None,
                ),
            )
            # Conflict receipts must survive HTTP 409; raising HTTPException would
            # allow a generic request dependency to roll back the durable conflict.
            await application.commit()
            response = outcome.to_dict()
            return JSONResponse(
                status_code=409 if response["receipt"]["status"] == "conflict" else 200,
                content=response,
            )
        except KnowledgeSyncError as error:
            return error_response(error)

    async def conflict(
        project_id: str,
        conflict_id: str,
        application: KnowledgeSyncApplication = Depends(application_dependency),
        user: User = Depends(get_current_user),
    ) -> JSONResponse:
        try:
            scope = await application.service.resolve_scope(user.id, project_id)
            return JSONResponse(content=await application.service.conflict(scope, conflict_id))
        except KnowledgeSyncError as error:
            return error_response(error)

    async def resolve(
        project_id: str,
        conflict_id: str,
        body: SyncResolutionBody,
        application: KnowledgeSyncApplication = Depends(application_dependency),
        user: User = Depends(get_current_user),
    ) -> JSONResponse:
        try:
            scope = await application.service.resolve_scope(user.id, project_id)
            outcome = await application.service.resolve(
                scope,
                body.change_id,
                KnowledgeSyncResolution(
                    conflict_id=conflict_id,
                    expected_current_revision=body.expected_current_revision,
                    decision=body.decision,
                    content=body.content.domain() if body.content else None,
                ),
            )
            await application.commit()
            return JSONResponse(content=outcome.to_dict())
        except KnowledgeSyncError as error:
            return error_response(error)

    router.add_api_route("/changes", changes, methods=["GET"])
    router.add_api_route("/mutations", mutate, methods=["POST"])
    router.add_api_route("/conflicts/{conflict_id}", conflict, methods=["GET"])
    router.add_api_route("/conflicts/{conflict_id}/resolve", resolve, methods=["POST"])
    return router
