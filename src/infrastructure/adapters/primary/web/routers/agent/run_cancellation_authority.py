"""Versioned, scoped cancellation requests; only the worker may settle cancellation."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.conversation_session_projection import SessionPlanRunResponse
from src.application.services.agent.run_cancellation_signal import RunCancellationIdentity
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanRunModel,
    AgentRunAuthorityModel,
    HITLRequest,
    User,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.agent_worker_runtime import current_agent_worker_redis_client_v2
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_agent_turn_operation_v2,
)

from .run_authority_common import _load_scoped_run

router = APIRouter()


class CancelRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)


class CancelRunResponse(BaseModel):
    accepted: Literal[True] = True
    status: Literal["cancel_requested", "cancelled"]
    run: SessionPlanRunResponse


def _response(run: AgentRunAuthorityModel) -> CancelRunResponse:
    fields = {
        name: getattr(run, name)
        for name in SessionPlanRunResponse.model_fields
        if name not in {"environment", "last_heartbeat_at"}
    }
    fields["last_heartbeat_at"] = None
    fields["environment"] = run.authorization_snapshot.get("environment")
    return CancelRunResponse(
        status="cancelled" if run.status == "cancelled" else "cancel_requested",
        run=SessionPlanRunResponse.model_validate(fields),
    )


@router.post("/runs/{run_id}/cancel", response_model=CancelRunResponse)
async def cancel_run(
    run_id: str,
    body: CancelRunRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CancelRunResponse:
    run, _conversation = await _load_scoped_run(
        db, run_id=run_id, user_id=current_user.id, lock=True
    )
    snapshot = dict(run.authorization_snapshot)
    receipt = snapshot.get("cancellation_receipt")
    same_request = (
        isinstance(receipt, dict) and receipt.get("expected_revision") == body.expected_revision
    )
    if run.status == "cancelled" and same_request and run.revision == body.expected_revision + 1:
        return _response(run)
    if run.status not in {"queued", "running"} or run.revision != body.expected_revision:
        raise HTTPException(status_code=409, detail=_("Run authority changed; refresh and retry"))
    if receipt is not None and not same_request:
        raise HTTPException(status_code=409, detail=_("Run cancellation request conflicts"))
    pending_hitl = await db.scalar(
        select(HITLRequest.id)
        .where(
            HITLRequest.tenant_id == run.tenant_id,
            HITLRequest.project_id == run.project_id,
            HITLRequest.conversation_id == run.conversation_id,
            HITLRequest.status == "pending",
            HITLRequest.expires_at > datetime.now(UTC),
        )
        .limit(1)
    )
    if pending_hitl is not None:
        raise HTTPException(
            status_code=409, detail=_("Resolve the pending interaction before cancelling this run")
        )
    if not same_request:
        snapshot["cancellation_receipt"] = {
            "expected_revision": body.expected_revision,
            "requested_by": current_user.id,
            "requested_at": datetime.now(UTC).isoformat(),
        }
        run.authorization_snapshot = snapshot
        if run.plan_run_id is not None:
            plan_run = await db.get(AgentPlanRunModel, run.plan_run_id, with_for_update=True)
            if (
                plan_run is None
                or plan_run.id != run.id
                or plan_run.conversation_id != run.conversation_id
                or plan_run.project_id != run.project_id
            ):
                raise HTTPException(status_code=409, detail=_("Plan run authority changed"))
            plan_run.authorization_snapshot = dict(snapshot)
        await db.commit()
    else:
        # Never hold a database row lock while waiting on a remote worker/control store.
        await db.commit()
    identity = RunCancellationIdentity(
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        conversation_id=run.conversation_id,
        run_id=run.id,
    )
    try:
        async with pin_agent_turn_operation_v2(
            operation_id=f"run-cancellation:{run.id}:{body.expected_revision}",
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            session_id=run.conversation_id,
            services={
                OPERATION_DB_SESSION_SERVICE_V2: db,
                OPERATION_IDENTITY_SERVICE_V2: {
                    "tenant_id": run.tenant_id,
                    "project_id": run.project_id,
                    "user_id": current_user.id,
                },
                OPERATION_METADATA_SERVICE_V2: {
                    "kind": "agent-control",
                    "channel": "run-cancellation",
                    "run_id": run.id,
                    "run_revision": body.expected_revision,
                },
            },
        ):
            stored = await current_agent_worker_redis_client_v2().set(
                identity.key,
                identity.payload(),
                ex=86400,
            )
        if not stored:
            raise RuntimeError("Cancellation signal was not stored")
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=_("Run cancellation delivery unavailable; retry")
        ) from exc
    await db.refresh(run)
    if run.status == "cancelled" and run.revision == body.expected_revision + 1:
        return _response(run)
    if run.status not in {"queued", "running"} or run.revision != body.expected_revision:
        raise HTTPException(status_code=409, detail=_("Run authority changed; refresh and retry"))
    return _response(run)
