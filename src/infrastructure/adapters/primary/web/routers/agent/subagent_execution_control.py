"""Exact Cloud child-control HTTP boundary, with fresh conversation/project membership."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.agent_subagent_control_http_application_authority_v2 import (
    AgentSubAgentControlHttpApplicationAuthorityV2,
    agent_subagent_control_http_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import UserProject
from src.infrastructure.agent.subagent.execution_control_v2 import (
    SubAgentControlConflictV2,
    execution_control_snapshot_v2,
    request_execution_control_v2,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.agent_subagent_control_services import (
    AgentSubAgentControlUnavailableV2,
)
from src.infrastructure.plugins.v2.subagent_run_registry_projection import (
    current_subagent_run_registry_v2,
)

from .trace_router import _get_accessible_conversation

router = APIRouter()


class ChildControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["steer", "kill_run"]
    expected_control_revision: int = Field(ge=0, strict=True)
    idempotency_key: str = Field(min_length=1, max_length=200)
    instruction: str | None = Field(default=None, max_length=16000)

    @model_validator(mode="after")
    def validate_action(self) -> "ChildControlRequest":
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if self.action == "steer" and not (self.instruction or "").strip():
            raise ValueError("steer requires instruction")
        if self.action == "kill_run" and self.instruction is not None:
            raise ValueError("kill_run does not accept instruction")
        return self


class ChildControlSnapshot(BaseModel):
    schema_version: Literal[1] = 1
    authority_kind: Literal["subagent_execution_registry"] = "subagent_execution_registry"
    conversation_id: str
    tenant_id: str
    project_id: str
    controls: list[dict[str, object]]


class ChildControlReceipt(BaseModel):
    accepted: Literal[True]
    duplicate: bool
    action: Literal["steer", "kill_run"]
    conversation_id: str
    run_id: str
    control_revision: int
    idempotency_key: str


async def _authorize(
    db: AsyncSession, user: User, cid: str, tenant_id: str, project_id: str
) -> None:
    conversation = await _get_accessible_conversation(db, user, cid)
    if conversation.tenant_id != tenant_id or conversation.project_id != project_id:
        raise HTTPException(status_code=404, detail=_("Conversation not found"))
    member = await db.scalar(
        select(UserProject.user_id).where(
            UserProject.user_id == str(user.id),
            UserProject.project_id == project_id,
        )
    )
    if member is None:
        raise HTTPException(status_code=404, detail=_("Conversation not found"))


@router.get(
    "/conversations/{conversation_id}/subagent-controls", response_model=ChildControlSnapshot
)
async def get_child_controls(
    conversation_id: str,
    tenant_id: str = Query(min_length=1),
    project_id: str = Query(min_length=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChildControlSnapshot:
    await _authorize(db, current_user, conversation_id, tenant_id, project_id)
    controls = await execution_control_snapshot_v2(
        current_subagent_run_registry_v2(), conversation_id
    )
    return ChildControlSnapshot(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        project_id=project_id,
        controls=controls,
    )


@router.post(
    "/conversations/{conversation_id}/subagents/{run_id}/control",
    response_model=ChildControlReceipt,
)
async def control_child_execution(
    conversation_id: str,
    run_id: str,
    body: ChildControlRequest,
    tenant_id: str = Query(min_length=1),
    project_id: str = Query(min_length=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    authority: AgentSubAgentControlHttpApplicationAuthorityV2 = Depends(
        agent_subagent_control_http_application_authority_dependency_v2,
    ),
) -> ChildControlReceipt:
    await _authorize(db, current_user, conversation_id, tenant_id, project_id)
    try:
        receipt = await request_execution_control_v2(
            current_subagent_run_registry_v2(),
            authority.service,
            conversation_id=conversation_id,
            run_id=run_id,
            requested_by=str(current_user.id),
            **body.model_dump(),
        )
    except SubAgentControlConflictV2 as exc:
        raise HTTPException(
            status_code=409, detail=_("Child execution authority changed; refresh and retry")
        ) from exc
    except AgentSubAgentControlUnavailableV2 as exc:
        raise HTTPException(
            status_code=503, detail=_("Child control delivery unavailable; retry the same command")
        ) from exc
    return ChildControlReceipt.model_validate(receipt)
