"""Verify automatic UI approval provenance against persisted conversation preferences."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.hitl_request import HITLRequest
from src.infrastructure.adapters.secondary.persistence.models import Conversation
from src.infrastructure.adapters.secondary.persistence.terminal_hitl_run_binding import (
    terminal_hitl_run_binding,
)
from src.infrastructure.agent.hitl.utils import resolve_trusted_hitl_type


async def annotate_automatic_permission_response(
    db: AsyncSession,
    *,
    hitl_request: HITLRequest,
    approval_mode: str | None,
    response_data: dict[str, Any],
) -> dict[str, Any]:
    """Reject stale/forged automatic provenance; manual responses retain no auto marker."""
    cleaned = {
        key: value for key, value in response_data.items() if key not in {"auto_approved", "preset"}
    }
    if approval_mode is None:
        return cleaned
    metadata = hitl_request.metadata or {}
    decision = metadata.get("decision")
    target = decision.get("target") if isinstance(decision, dict) else None
    native_target = isinstance(target, dict) and target.get("kind") in (
        "computer_app",
        "device_mcp_tool",
    )
    if (
        approval_mode not in ("auto_edit", "full_access")
        or resolve_trusted_hitl_type(hitl_request) != "permission"
        or "native_binding" in metadata
        or metadata.get("permission_type") == "computer_use"
        or native_target
        or cleaned.get("granted") is not True
        or cleaned.get("action") != "allow"
        or cleaned.get("scope") != "once"
        or (
            approval_mode == "auto_edit"
            and metadata.get("permission_type")
            not in ("write", "workspace_file_write", "workspace_task_write")
        )
    ):
        raise ValueError("Invalid automatic permission approval")
    config = await db.scalar(
        select(Conversation.agent_config).where(
            Conversation.id == hitl_request.conversation_id,
            Conversation.tenant_id == hitl_request.tenant_id,
            Conversation.project_id == hitl_request.project_id,
            ~terminal_hitl_run_binding(
                tenant_id=hitl_request.tenant_id,
                project_id=hitl_request.project_id,
                conversation_id=hitl_request.conversation_id,
                message_id=getattr(hitl_request, "message_id", None),
            ),
        )
    )
    if not isinstance(config, dict) or config.get("approval_mode") != approval_mode:
        raise ValueError("Conversation approval mode changed")
    return {
        **cleaned,
        "auto_approved": True,
        "preset": "full" if approval_mode == "full_access" else "relaxed",
    }
