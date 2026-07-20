"""Human-in-the-loop (HITL) endpoints for Agent API.

Provides endpoints for human intervention during agent execution:
- get_pending_hitl_requests: Get pending requests for a conversation
- get_project_pending_hitl_requests: Get pending requests for a project
- respond_to_hitl: Unified endpoint to respond to any HITL request

Architecture (Ray-based, Redis Streams only):
    Frontend → POST /hitl/respond
                    └─ Redis Stream (primary, ~30ms) → Ray Actor → Session
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.hitl_request import HITLRequest
from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
    SqlConversationRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
    SqlHITLRequestRepository,
)
from src.infrastructure.i18n import gettext as _

from .schemas import (
    HITLCancelRequest,
    HITLRequestResponse,
    HITLResponseRequest,
    HumanInteractionResponse,
    PendingHITLResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _user_has_hitl_access(
    *,
    db: AsyncSession,
    user_id: str,
    tenant_id: str,
    project_id: str | None,
    conversation_id: str,
) -> bool:
    """Return True when the user owns the target conversation in the same tenant."""
    from src.infrastructure.adapters.secondary.persistence.models import Conversation

    conversation_query = select(Conversation.id).where(
        Conversation.id == conversation_id,
        Conversation.tenant_id == tenant_id,
        Conversation.user_id == user_id,
    )
    conversation_result = await db.execute(refresh_select_statement(conversation_query))
    return conversation_result.scalar_one_or_none() is not None


async def _user_has_project_access(
    *,
    db: AsyncSession,
    user_id: str,
    project_id: str,
) -> bool:
    """Return True when the user belongs to the project."""
    from src.infrastructure.adapters.secondary.persistence.models import UserProject

    project_membership_query = select(UserProject.id).where(
        UserProject.user_id == user_id,
        UserProject.project_id == project_id,
    )
    project_membership = await db.execute(refresh_select_statement(project_membership_query))
    return project_membership.scalar_one_or_none() is not None


def _validate_hitl_response_shape(*, hitl_type: str, response_data: dict[str, Any]) -> None:
    """Reject malformed HITL ingress payloads before validation/publish."""
    has_cancelled = response_data.get("cancelled") is True
    has_timeout = response_data.get("timeout") is True

    if hitl_type != "env_var" and (has_cancelled or has_timeout):
        raise HTTPException(
            status_code=400,
            detail=_("cancelled/timeout responses are only supported for env_var HITL"),
        )

    if hitl_type == "permission":
        action = response_data.get("action")
        granted = response_data.get("granted")
        scope = response_data.get("scope")
        if action is None and isinstance(granted, bool):
            return
        expected = {
            "allow": (True, "once"),
            "allow_always": (True, "workspace_tool"),
            "deny": (False, "once"),
        }
        if action not in expected or (granted, scope) != expected[action]:
            raise HTTPException(
                status_code=400,
                detail=_("Invalid permission response"),
            )
        if {"tool", "tool_name", "canonical_tool_name"}.intersection(response_data):
            raise HTTPException(
                status_code=400,
                detail=_("Permission response must not provide a tool name"),
            )
        return

    if hitl_type != "env_var":
        return

    has_values = "values" in response_data
    variant_count = sum((has_values, has_cancelled, has_timeout))
    if variant_count != 1:
        raise HTTPException(
            status_code=400,
            detail=_("env_var responses must include exactly one of values/cancelled/timeout"),
        )

    if has_values and not isinstance(response_data.get("values"), dict):
        raise HTTPException(
            status_code=400,
            detail=_("env_var values must be an object"),
        )


async def _persist_workspace_tool_grant_if_requested(
    *,
    db: AsyncSession,
    hitl_request: HITLRequest,
    response_data: dict[str, Any],
    current_user: User,
) -> None:
    if response_data.get("action") != "allow_always":
        return

    from src.domain.model.trust.trust_policy import TrustPolicy
    from src.infrastructure.adapters.secondary.persistence.models import (
        Conversation,
        TrustPolicyModel,
        UserProject,
        WorkspaceMemberModel,
        WorkspaceModel,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_trust_policy_repository import (
        SqlTrustPolicyRepository,
    )
    from src.infrastructure.agent.hitl.utils import build_hitl_request_data_from_record

    request_data = build_hitl_request_data_from_record(hitl_request)
    canonical_tool_name = request_data.get("tool_name")
    if not isinstance(canonical_tool_name, str) or not canonical_tool_name.strip():
        raise HTTPException(status_code=400, detail=_("Permission request has no canonical tool"))
    if request_data.get("allow_remember") is not True:
        raise HTTPException(status_code=403, detail=_("This permission cannot be remembered"))

    conversation_result = await db.execute(
        refresh_select_statement(
            select(Conversation.workspace_id).where(
                Conversation.id == hitl_request.conversation_id,
                Conversation.tenant_id == hitl_request.tenant_id,
                Conversation.project_id == hitl_request.project_id,
            )
        )
    )
    workspace_id = conversation_result.scalar_one_or_none()
    if not workspace_id:
        raise HTTPException(status_code=400, detail=_("Conversation has no workspace"))
    workspace_result = await db.execute(
        refresh_select_statement(
            select(WorkspaceModel).where(
                WorkspaceModel.id == workspace_id,
                WorkspaceModel.tenant_id == hitl_request.tenant_id,
                WorkspaceModel.project_id == hitl_request.project_id,
                WorkspaceModel.is_archived.is_(False),
            )
        )
    )
    workspace = workspace_result.scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail=_("Workspace not found"))

    user_id = str(current_user.id)
    if workspace.created_by != user_id:
        workspace_role_result = await db.execute(
            refresh_select_statement(
                select(WorkspaceMemberModel.role).where(
                    WorkspaceMemberModel.workspace_id == workspace_id,
                    WorkspaceMemberModel.user_id == user_id,
                )
            )
        )
        project_role_result = await db.execute(
            refresh_select_statement(
                select(UserProject.role).where(
                    UserProject.project_id == hitl_request.project_id,
                    UserProject.user_id == user_id,
                )
            )
        )
        if workspace_role_result.scalar_one_or_none() not in {
            "manager",
            "owner",
        } and project_role_result.scalar_one_or_none() not in {"admin", "owner"}:
            raise HTTPException(
                status_code=403,
                detail=_("Workspace manager permission is required"),
            )

    canonical_tool_name = canonical_tool_name.strip()
    existing_result = await db.execute(
        refresh_select_statement(
            select(TrustPolicyModel.id).where(
                TrustPolicyModel.tenant_id == hitl_request.tenant_id,
                TrustPolicyModel.workspace_id == workspace_id,
                TrustPolicyModel.scope == "workspace_tool",
                TrustPolicyModel.canonical_tool_name == canonical_tool_name,
                TrustPolicyModel.grant_type == "always",
                TrustPolicyModel.revoked_at.is_(None),
                TrustPolicyModel.deleted_at.is_(None),
            )
        )
    )
    if existing_result.scalar_one_or_none() is not None:
        return
    await SqlTrustPolicyRepository(db).save(
        TrustPolicy(
            tenant_id=hitl_request.tenant_id,
            workspace_id=workspace_id,
            agent_instance_id="*",
            action_type=canonical_tool_name,
            granted_by=user_id,
            grant_type="always",
            scope="workspace_tool",
            canonical_tool_name=canonical_tool_name,
            source_hitl_request_id=hitl_request.id,
            revision=1,
        )
    )


async def _mark_hitl_timeout_if_expired(
    *,
    db: AsyncSession,
    repo: SqlHITLRequestRepository,
    hitl_request: HITLRequest,
) -> bool:
    """Persist TIMEOUT once a pending request has passed its expiry timestamp."""
    expires_at = hitl_request.expires_at
    if expires_at is None or expires_at > datetime.now(UTC):
        return False
    timed_out_request = await repo.mark_timeout(hitl_request.id)
    if timed_out_request is not None:
        await db.commit()
    return True


async def _load_authorized_pending_hitl_request(
    *,
    db: AsyncSession,
    request_id: str,
    user_id: str,
    tenant_id: str,
) -> HITLRequest:
    """Load a pending HITL request after tenant/project/conversation authorization."""
    from src.domain.model.agent.hitl_request import HITLRequestStatus

    repo = SqlHITLRequestRepository(db)
    hitl_request = await repo.get_by_id(request_id)

    if not hitl_request:
        logger.warning(f"HITL request not found in database: {request_id}")
        raise HTTPException(
            status_code=404,
            detail=_("HITL request not found"),
        )

    logger.info(
        f"Found HITL request: id={hitl_request.id}, tenant={hitl_request.tenant_id}, "
        f"project={hitl_request.project_id}, status={hitl_request.status}"
    )

    if hitl_request.tenant_id != tenant_id:
        raise HTTPException(
            status_code=403,
            detail=_("Access denied to this HITL request"),
        )

    if hitl_request.user_id:
        if hitl_request.user_id != user_id:
            raise HTTPException(
                status_code=403,
                detail=_("Access denied to this HITL request"),
            )
        has_access = bool(hitl_request.project_id) and await _user_has_project_access(
            db=db,
            user_id=user_id,
            project_id=hitl_request.project_id,
        )
    else:
        has_access = await _user_has_hitl_access(
            db=db,
            user_id=user_id,
            tenant_id=tenant_id,
            project_id=hitl_request.project_id,
            conversation_id=hitl_request.conversation_id,
        )
    if not has_access:
        raise HTTPException(
            status_code=403,
            detail=_("Access denied to this HITL request"),
        )

    if await _mark_hitl_timeout_if_expired(db=db, repo=repo, hitl_request=hitl_request):
        raise HTTPException(
            status_code=400,
            detail=_("HITL request has expired"),
        )

    if hitl_request.status != HITLRequestStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=_("HITL request is no longer pending"),
        )

    return hitl_request


def _validate_and_summarize_hitl_response(
    *,
    hitl_request: HITLRequest,
    request: HITLResponseRequest,
    tenant_id: str,
) -> tuple[str, str, dict[str, Any] | None]:
    """Validate HITL response semantics and return redacted persistence values."""
    from src.domain.model.agent.hitl_types import HITLType
    from src.infrastructure.agent.hitl.coordinator import validate_hitl_response
    from src.infrastructure.agent.hitl.utils import (
        build_hitl_request_data_from_record,
        resolve_trusted_hitl_type,
        summarize_hitl_response,
    )

    stored_hitl_type = resolve_trusted_hitl_type(hitl_request)
    if stored_hitl_type is None:
        raise HTTPException(
            status_code=400,
            detail=_("HITL request has an invalid stored type"),
        )

    if request.hitl_type != stored_hitl_type:
        raise HTTPException(
            status_code=400,
            detail=_("HITL type does not match request"),
        )

    _validate_hitl_response_shape(
        hitl_type=stored_hitl_type,
        response_data=request.response_data,
    )

    is_valid, _validation_error = validate_hitl_response(
        hitl_type=HITLType(stored_hitl_type),
        request_data=build_hitl_request_data_from_record(hitl_request),
        response_data=request.response_data,
        conversation_id=hitl_request.conversation_id,
        tenant_id=hitl_request.tenant_id,
        project_id=hitl_request.project_id,
        message_id=hitl_request.message_id,
        received_tenant_id=tenant_id,
        received_project_id=hitl_request.project_id,
        received_conversation_id=hitl_request.conversation_id,
        received_message_id=hitl_request.message_id,
    )
    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail=_("Invalid HITL response"),
        )

    response_str, response_metadata = summarize_hitl_response(
        stored_hitl_type,
        request.response_data,
    )
    return stored_hitl_type, response_str, response_metadata


@router.get(
    "/conversations/{conversation_id}/pending",
    response_model=PendingHITLResponse,
)
async def get_pending_hitl_requests(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> PendingHITLResponse:
    """
    Get all pending HITL requests for a conversation.

    This endpoint allows the frontend to query for pending HITL requests
    after a page refresh, enabling recovery of the conversation state.
    """
    try:
        from src.infrastructure.agent.hitl.utils import resolve_trusted_hitl_type

        conv_repo = SqlConversationRepository(db)
        conversation = await conv_repo.find_by_id(conversation_id)

        if not conversation:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))

        # Verify user has access (same tenant)
        if conversation.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail=_("Access denied to this conversation"))
        has_access = await _user_has_hitl_access(
            db=db,
            user_id=str(current_user.id),
            tenant_id=tenant_id,
            project_id=conversation.project_id,
            conversation_id=conversation_id,
        )
        if not has_access:
            raise HTTPException(status_code=403, detail=_("Access denied to this conversation"))

        # Query pending requests
        repo = SqlHITLRequestRepository(db)
        pending = await repo.get_pending_by_conversation(
            conversation_id=conversation_id,
            tenant_id=conversation.tenant_id,
            project_id=conversation.project_id,
            exclude_expired=False,  # Show all pending, let user decide
        )

        requests = [
            HITLRequestResponse(
                id=r.id,
                request_type=resolve_trusted_hitl_type(r) or r.request_type.value,
                conversation_id=r.conversation_id,
                message_id=r.message_id or "",
                question=r.question,
                options=r.options,
                context=r.context,
                metadata=r.metadata,
                status=r.status.value,
                created_at=r.created_at.isoformat() if r.created_at else "",
                expires_at=r.expires_at.isoformat() if r.expires_at else "",
            )
            for r in pending
        ]

        return PendingHITLResponse(
            requests=requests,
            total=len(requests),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting pending HITL requests")
        raise HTTPException(
            status_code=500, detail=_("Failed to get pending HITL requests")
        ) from exc


@router.get("/projects/{project_id}/pending", response_model=PendingHITLResponse)
async def get_project_pending_hitl_requests(
    project_id: str,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
) -> PendingHITLResponse:
    """
    Get all pending HITL requests for a project.

    This endpoint allows querying all pending HITL requests across all
    conversations in a project.
    """
    try:
        from src.infrastructure.agent.hitl.utils import resolve_trusted_hitl_type

        has_access = await _user_has_project_access(
            db=db,
            user_id=str(current_user.id),
            project_id=project_id,
        )
        if not has_access:
            raise HTTPException(status_code=403, detail=_("Access denied to this project"))

        repo = SqlHITLRequestRepository(db)
        pending = await repo.get_pending_by_project_for_user(
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=str(current_user.id),
            limit=limit,
        )

        requests = [
            HITLRequestResponse(
                id=r.id,
                request_type=resolve_trusted_hitl_type(r) or r.request_type.value,
                conversation_id=r.conversation_id,
                message_id=r.message_id or "",
                question=r.question,
                options=r.options,
                context=r.context,
                metadata=r.metadata,
                status=r.status.value,
                created_at=r.created_at.isoformat() if r.created_at else "",
                expires_at=r.expires_at.isoformat() if r.expires_at else "",
            )
            for r in pending
        ]

        return PendingHITLResponse(
            requests=requests,
            total=len(requests),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting project pending HITL requests")
        raise HTTPException(
            status_code=500, detail=_("Failed to get pending HITL requests")
        ) from exc


# =============================================================================
# Unified HITL Response Endpoint (Ray-based)
# =============================================================================


@router.post("/respond", response_model=HumanInteractionResponse)
async def respond_to_hitl(
    request: HITLResponseRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> HumanInteractionResponse:
    """
    Unified endpoint to respond to any HITL request.

    This endpoint publishes to Redis Streams so Ray Actors can continue execution.

    Request body:
    - request_id: The HITL request ID
    - hitl_type: Type of request ("clarification", "decision", "env_var", "permission")
    - response_data: Type-specific response data
        - clarification: {"answer": "user answer"}
        - decision: {"decision": "option_id"}
        - env_var: {"values": {"VAR_NAME": "value"}, "save": true}
        - permission: {"action": "allow", "remember": false}
    """

    response_keys = (
        sorted(request.response_data.keys()) if isinstance(request.response_data, dict) else []
    )
    logger.info(
        "HITL respond request: request_id=%s hitl_type=%s response_keys=%s",
        request.request_id,
        request.hitl_type,
        response_keys,
    )

    try:
        # Validate HITL type
        valid_types = ["clarification", "decision", "env_var", "permission", "a2ui_action"]
        if request.hitl_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=_("Invalid HITL type"),
            )

        repo = SqlHITLRequestRepository(db)
        hitl_request = await _load_authorized_pending_hitl_request(
            db=db,
            user_id=str(current_user.id),
            tenant_id=tenant_id,
            request_id=request.request_id,
        )
        project_id = hitl_request.project_id
        conversation_id = hitl_request.conversation_id
        agent_mode = (hitl_request.metadata or {}).get("agent_mode", "default")
        stored_hitl_type, response_str, response_metadata = _validate_and_summarize_hitl_response(
            hitl_request=hitl_request,
            request=request,
            tenant_id=tenant_id,
        )
        hitl_label = stored_hitl_type.replace("_", " ").title()

        if stored_hitl_type == "permission":
            await _persist_workspace_tool_grant_if_requested(
                db=db,
                hitl_request=hitl_request,
                response_data=request.response_data,
                current_user=current_user,
            )

        updated_request = await repo.update_response(
            request.request_id,
            response_str,
            response_metadata=response_metadata,
        )
        if updated_request is None:
            raise HTTPException(
                status_code=409,
                detail=_("HITL request could not be updated"),
            )
        await db.commit()

        # Redis Stream delivery (primary channel)
        # This allows Ray Actors to receive response directly in-memory
        redis_sent = await _publish_hitl_response_to_redis(
            tenant_id=tenant_id,
            project_id=project_id,
            conversation_id=conversation_id,
            message_id=hitl_request.message_id,
            request_id=request.request_id,
            hitl_type=stored_hitl_type,
            response_data=request.response_data,
            user_id=str(current_user.id),
            agent_mode=agent_mode,
        )
        if not redis_sent:
            logger.warning(
                "HITL response publish failed after claim: request_id=%s hitl_type=%s "
                "keeping_answered_state=true",
                request.request_id,
                stored_hitl_type,
            )
            return HumanInteractionResponse(
                success=True,
                message=f"{hitl_label} response saved. Delivery is pending.",
            )

        logger.info(f"HITL response published to Redis Stream: {request.request_id}")

        logger.info(
            f"User {current_user.id} responded to HITL {request.request_id} "
            f"(type={stored_hitl_type}) via Redis"
        )

        return HumanInteractionResponse(
            success=True,
            message=f"{hitl_label} response received",
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error responding to HITL request")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to respond to HITL request"),
        ) from exc


@router.post("/cancel", response_model=HumanInteractionResponse)
async def cancel_hitl_request(
    request: HITLCancelRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> HumanInteractionResponse:
    """
    Cancel a pending HITL request.
    """
    try:
        repo = SqlHITLRequestRepository(db)
        await _load_authorized_pending_hitl_request(
            db=db,
            user_id=str(current_user.id),
            tenant_id=tenant_id,
            request_id=request.request_id,
        )

        cancelled_request = await repo.mark_cancelled(request.request_id)
        if cancelled_request is None:
            raise HTTPException(
                status_code=409,
                detail=_("HITL request could not be cancelled"),
            )
        await db.commit()

        # Remove any stored HITL state (Redis + Postgres snapshot) after cancel wins the race.
        from src.infrastructure.agent.actor.state.snapshot_repo import delete_hitl_snapshot
        from src.infrastructure.agent.hitl.state_store import get_hitl_state_store

        try:
            state_store = await get_hitl_state_store()
            await state_store.delete_state_by_request(request.request_id)
            await delete_hitl_snapshot(request.request_id)
        except Exception:
            logger.warning(
                "Cancelled HITL request but cleanup failed: request_id=%s",
                request.request_id,
                exc_info=True,
            )

        logger.info(f"User {current_user.id} cancelled HITL {request.request_id}: {request.reason}")

        return HumanInteractionResponse(
            success=True,
            message="HITL request cancelled",
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error cancelling HITL request")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to cancel HITL request"),
        ) from exc


async def _publish_hitl_response_to_redis(
    tenant_id: str,
    project_id: str,
    conversation_id: str,
    message_id: str | None,
    request_id: str,
    hitl_type: str,
    response_data: dict[str, Any],
    user_id: str,
    agent_mode: str,
) -> bool:
    """
    Publish HITL response to Redis Stream for fast delivery.

    This is the primary channel that allows Ray Actors
    to receive responses and continue execution.

    Stream key: hitl:response:{tenant_id}:{project_id}

    Returns:
        True if published successfully, False otherwise
    """
    try:
        from src.configuration.config import get_settings
        from src.infrastructure.agent.hitl.utils import serialize_hitl_stream_response
        from src.infrastructure.agent.state.agent_worker_state import (
            get_redis_client,
        )

        settings = get_settings()

        # Check if real-time HITL is enabled
        if not getattr(settings, "hitl_realtime_enabled", True):
            logger.debug("HITL real-time disabled, skipping Redis Stream publish")
            return False

        redis = await get_redis_client()

        stream_key = f"hitl:response:{tenant_id}:{project_id}"
        message_data: dict[str, Any] = {
            "request_id": request_id,
            "hitl_type": hitl_type,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "agent_mode": agent_mode,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        message_data.update(serialize_hitl_stream_response(hitl_type, response_data))

        # Add to stream with maxlen to prevent unbounded growth
        await redis.xadd(
            stream_key,
            {"data": json.dumps(message_data)},
            maxlen=1000,  # Keep last 1000 messages
        )

        logger.info(f"[HITL Redis] Published response to {stream_key}: request_id={request_id}")
        return True

    except Exception as e:
        logger.warning(f"Failed to publish HITL response to Redis Stream: {e}.")
        return False
