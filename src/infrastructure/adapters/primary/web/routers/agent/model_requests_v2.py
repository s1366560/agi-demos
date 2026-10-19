"""Read immutable provider inputs with the existing conversation-history authority."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.model_request_log import prepared_model_request_v2
from src.infrastructure.plugins.v2.session_event_log_store import SqlSessionEventLogStoreV2

from .events import _get_accessible_conversation

router = APIRouter()


@router.get(
    "/conversations/{conversation_id}/messages/{message_id}/model-requests/{attempt_id}",
    response_model=dict[str, Any],
)
async def get_model_request_v2(
    conversation_id: str,
    message_id: str,
    attempt_id: str,
    request: Request,
    project_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    conversation = await _get_accessible_conversation(conversation_id, current_user, db, request)
    if project_id is not None and project_id != conversation.project_id:
        raise HTTPException(status_code=403, detail=_("Access denied to this conversation"))
    records = await SqlSessionEventLogStoreV2().read_message_events(
        conversation_id=conversation_id, message_id=message_id
    )
    # A historical request remains readable after its plugin generation is retired.
    # Recheck access after storage I/O so revocation cannot race the response.
    await _get_accessible_conversation(conversation_id, current_user, db, request)
    matches = [
        record.event_data
        for record in records
        if record.conversation_id == conversation_id
        and record.message_id == message_id
        and record.event_type == "model_request_prepared"
        and record.event_data.get("attempt_id") == attempt_id
        and record.event_data.get("schema_version") == 1
        and record.event_data.get("format") == "provider.http.json/v1"
    ]
    available = len(matches) == 1
    return {
        "schema_version": 1,
        "status": "available" if available else "snapshot_missing",
        "attempt_id": attempt_id,
        "request": {
            "protocol": matches[0].get("provider"),
            "model": matches[0].get("model"),
            "body": prepared_model_request_v2(matches[0]["request"]),
        }
        if available
        else None,
        "reason_code": None if available else "model_request_snapshot_missing",
    }
