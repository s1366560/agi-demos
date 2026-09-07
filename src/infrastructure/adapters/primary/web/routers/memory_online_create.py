"""Enrolled HTTP create adapter with explicit client command identity."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from src.domain.model.knowledge_sync.contracts import MemorySyncContent, MemorySyncVersion
from src.infrastructure.adapters.secondary.persistence.models import Memory, TaskLog
from src.infrastructure.i18n import gettext as _

if TYPE_CHECKING:
    from src.domain.ports.repositories.online_memory_repository import OnlineMemoryContext
    from src.infrastructure.adapters.primary.web.memory_application_authority_v2 import (
        MemoryApplicationAuthorityV2,
    )
    from src.infrastructure.adapters.primary.web.routers.memories import MemoryCreate


async def create_enrolled_memory(
    data: MemoryCreate,
    authority: MemoryApplicationAuthorityV2,
    context: OnlineMemoryContext,
    change_id: str | None,
    expected_revision: str | None,
) -> JSONResponse:
    from src.infrastructure.adapters.primary.web.routers.memories import MemoryResponse

    if change_id is None or expected_revision is None:
        raise HTTPException(
            status_code=428,
            detail={
                "code": "memory_command_precondition_required",
                "message": _("An idempotency key and expected revision are required"),
            },
        )
    if expected_revision != "0":
        raise HTTPException(
            status_code=422,
            detail={"code": "memory_command_revision_invalid", "message": _("Invalid revision")},
        )
    if data.entities or data.relationships or data.collaborators or data.is_public:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "memory_command_fields_unsupported",
                "message": _("These fields are not supported for enrolled memory creation"),
            },
        )
    outcome = await authority.services.online_commands.create(
        context,
        change_id,
        0,
        MemorySyncContent(
            title=data.title,
            content=data.content,
            content_type=data.content_type,
            tags=tuple(data.tags),
            metadata_json=json.dumps(data.metadata),
        ),
    )
    receipt = outcome.to_dict()["receipt"]
    version = MemorySyncVersion.from_dict(receipt["version"])
    scope = context.scope
    task_id = str(uuid5(NAMESPACE_URL, "memstack:online-memory-task:" + version.memory_id))
    # Build the response from the immutable receipt, including on retry after
    # later edits/deletion. Replays never reschedule derived processing.
    created_at = datetime.fromtimestamp(version.created_at_ms / 1000, UTC)
    response = MemoryResponse(
        id=version.memory_id,
        project_id=scope.project_id,
        title=version.content.title,
        content=version.content.content,
        content_type=version.content.content_type,
        tags=list(version.content.tags),
        entities=[],
        relationships=[],
        version=version.revision,
        author_id=version.author_id,
        collaborators=[],
        is_public=False,
        status=version.content.status,
        processing_status="PENDING",
        meta=json.loads(version.content.metadata_json),
        created_at=created_at,
        updated_at=None,
        task_id=task_id,
    )
    db = authority.db
    if not outcome.replayed:
        payload = {
            "task_id": task_id,
            "source_revision": version.revision,
            "dispatch_policy": "await_revision_fenced_worker",
            "group_id": scope.project_id,
            "name": version.content.title,
            "content": version.content.content,
            "source_description": "User input",
            "episode_type": version.content.content_type,
            "entity_types": None,
            "uuid": version.memory_id,
            "tenant_id": scope.tenant_id,
            "project_id": scope.project_id,
            "user_id": scope.actor_id,
            "memory_id": version.memory_id,
        }
        db.add(
            TaskLog(
                id=task_id,
                group_id=scope.project_id,
                task_type="memory_revision_projection",
                status="PENDING",
                payload=payload,
                message=_("Processing is deferred until revision-safe processing is available"),
                entity_type="episode",
                created_at=created_at,
            )
        )
        memory = await db.get(Memory, version.memory_id)
        if memory is None:
            raise RuntimeError("Admitted memory is missing in its transaction")
        # Persist the link so legacy orphan recovery cannot enqueue add_episode.
        # The dedicated task type is not admitted by legacy task retry handlers.
        memory.task_id = task_id
    await db.commit()
    return JSONResponse(
        status_code=201,
        content=response.model_dump(mode="json", by_alias=True),
        headers={
            "Idempotency-Replayed": str(outcome.replayed).lower(),
            "Memory-Processing-State": "deferred",
        },
    )
