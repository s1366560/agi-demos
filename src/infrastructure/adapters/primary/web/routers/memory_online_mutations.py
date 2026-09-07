"""Enrolled PATCH/delete adapters; legacy callers keep their existing branch."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response

from src.domain.model.knowledge_sync.contracts import (
    MAX_REVISION,
    KnowledgeSyncError,
    KnowledgeSyncOutcome,
    MemorySyncVersion,
    require_change_id,
)
from src.domain.model.knowledge_sync.online_patch import MemoryOnlinePatch
from src.infrastructure.adapters.secondary.persistence.models import Memory, TaskLog
from src.infrastructure.i18n import gettext as _

if TYPE_CHECKING:
    from src.domain.ports.repositories.online_memory_repository import OnlineMemoryContext
    from src.infrastructure.adapters.primary.web.memory_application_authority_v2 import (
        MemoryApplicationAuthorityV2,
    )
    from src.infrastructure.adapters.primary.web.routers.memories import MemoryUpdate

logger = logging.getLogger(__name__)


def mutation_preconditions(change_id: str | None, expected_revision: str | None) -> tuple[str, int]:
    if change_id is None or expected_revision is None:
        raise HTTPException(
            status_code=428,
            detail={
                "code": "memory_command_precondition_required",
                "message": _("An idempotency key and expected revision are required"),
            },
        )
    require_change_id(change_id)
    try:
        revision = int(expected_revision)
        if str(revision) != expected_revision or not 1 <= revision < MAX_REVISION:
            raise ValueError("noncanonical revision")
    except (TypeError, ValueError) as error:
        raise KnowledgeSyncError("knowledge_sync_input_invalid") from error
    return change_id, revision


async def try_enrolled_memory_mutation(
    *,
    memory_id: str,
    actor_id: str,
    authority: MemoryApplicationAuthorityV2,
    change_id: str | None,
    expected_revision: str | None,
    patch_data: MemoryUpdate | None = None,
    expected_project_id: str | None = None,
) -> Response | None:
    from .knowledge_sync import error_response
    from .memory_command_preconditions import require_memory_command_availability

    db = authority.db
    try:
        context = await authority.services.online_commands.open_memory(actor_id, memory_id)
        if context is None:
            return None
        if expected_project_id is not None and context.scope.project_id != expected_project_id:
            raise HTTPException(status_code=404, detail=_("Memory not found"))
        require_memory_command_availability(
            enabled=context.enabled, change_id=change_id, expected_revision=expected_revision
        )
        if not context.enabled:
            return None
        key, revision = mutation_preconditions(change_id, expected_revision)
        if patch_data is None:
            outcome = await authority.services.online_commands.delete(
                context, key, memory_id, revision
            )
        else:
            if patch_data.version != revision:
                raise KnowledgeSyncError("knowledge_sync_input_invalid")
            # Presence survives model validation: explicit null is rejected,
            # whereas absent fields are kept out of the command identity.
            fields = patch_data.model_dump(exclude_unset=True, exclude={"version"})
            patch = MemoryOnlinePatch(
                memory_id=memory_id, expected_revision=revision, fields_json=json.dumps(fields)
            )
            outcome = await authority.services.online_commands.patch(context, key, patch)
        return await finish_memory_mutation(authority, context, outcome)
    except KnowledgeSyncError as error:
        await db.rollback()
        return error_response(error)
    except HTTPException:
        await db.rollback()
        raise
    except Exception as error:
        await db.rollback()
        logger.exception("Enrolled memory command failed")
        raise HTTPException(status_code=500, detail=_("Failed to change memory")) from error


async def finish_memory_mutation(
    authority: MemoryApplicationAuthorityV2,
    context: OnlineMemoryContext,
    outcome: KnowledgeSyncOutcome,
) -> Response:
    from .memories import MemoryResponse

    receipt = outcome.to_dict()["receipt"]
    version = MemorySyncVersion.from_dict(receipt["version"])
    task_id = str(
        uuid5(
            NAMESPACE_URL,
            f"memstack:online-memory-projection:{version.memory_id}:{version.revision}",
        )
    )
    db = authority.db
    if not outcome.replayed:
        # This dedicated type cannot be dispatched by legacy dashboard recovery.
        db.add(
            TaskLog(
                id=task_id,
                group_id=context.scope.project_id,
                task_type="memory_revision_projection",
                status="PENDING",
                message=_("Processing is deferred until revision-safe processing is available"),
                entity_type="episode",
                created_at=datetime.now(UTC),
                payload={
                    "task_id": task_id,
                    "tenant_id": context.scope.tenant_id,
                    "project_id": context.scope.project_id,
                    "user_id": context.scope.actor_id,
                    "memory_id": version.memory_id,
                    "source_revision": version.revision,
                    "deleted": version.deleted,
                    "dispatch_policy": "await_revision_fenced_worker",
                    "version": version.to_dict(),
                },
            )
        )
        if not version.deleted:
            memory = await db.get(Memory, version.memory_id)
            if memory is None:
                raise RuntimeError("Admitted memory is missing in its transaction")
            memory.task_id = task_id
    headers = {
        "Idempotency-Replayed": str(outcome.replayed).lower(),
        "Memory-Processing-State": "deferred",
    }
    if version.deleted:
        await db.commit()
        return Response(status_code=204, headers=headers)
    retained: dict[str, Any] = receipt["retained_fields"]
    response = MemoryResponse(
        id=version.memory_id,
        project_id=context.scope.project_id,
        title=version.content.title,
        content=version.content.content,
        content_type=version.content.content_type,
        tags=list(version.content.tags),
        entities=retained["entities"],
        relationships=retained["relationships"],
        version=version.revision,
        author_id=version.author_id,
        collaborators=retained["collaborators"],
        is_public=retained["is_public"],
        status=version.content.status,
        processing_status="PENDING",
        meta=json.loads(version.content.metadata_json),
        created_at=datetime.fromtimestamp(version.created_at_ms / 1000, UTC),
        updated_at=retained["updated_at"],
        task_id=task_id,
    )
    await db.commit()
    return JSONResponse(
        status_code=200, content=response.model_dump(mode="json", by_alias=True), headers=headers
    )
