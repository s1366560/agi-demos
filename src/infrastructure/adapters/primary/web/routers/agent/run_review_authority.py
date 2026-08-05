"""Read-only canonical Cloud run projections for active state, summaries, and changes."""

from __future__ import annotations

from datetime import UTC
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.agent_run_authority import (
    ActiveRunProjection,
    ActiveRunResponse,
    ChangeFileResponse,
    LatestRunResponse,
    RunChangeAttribution,
    RunChangesResponse,
    RunSummaryResponse,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    AgentRunAuthorityModel,
    AgentRunSummaryModel,
    Conversation,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.i18n import gettext as _

from .run_authority_common import _canonical_hash, _explicit_change_payloads, _load_scoped_run

router = APIRouter()
_ACTIVE_RUN_STATUSES = frozenset({"queued", "running"})


@router.get(
    "/conversations/{conversation_id}/active-run",
    response_model=ActiveRunResponse,
)
async def get_active_run(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActiveRunResponse:
    """Return the active Cloud run identity needed by Queue/Steer clients."""

    conversation_result = await db.execute(
        refresh_select_statement(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == current_user.id,
                exists(
                    select(UserProject.id).where(
                        UserProject.project_id == Conversation.project_id,
                        UserProject.user_id == current_user.id,
                    )
                ),
                exists(
                    select(UserTenant.id).where(
                        UserTenant.tenant_id == Conversation.tenant_id,
                        UserTenant.user_id == current_user.id,
                    )
                ),
            )
        )
    )
    conversation = conversation_result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=403, detail=_("Conversation access denied"))
    run_result = await db.execute(
        refresh_select_statement(
            select(AgentRunAuthorityModel)
            .where(
                AgentRunAuthorityModel.conversation_id == conversation.id,
                AgentRunAuthorityModel.project_id == conversation.project_id,
                AgentRunAuthorityModel.status.in_(_ACTIVE_RUN_STATUSES),
            )
            .order_by(
                AgentRunAuthorityModel.created_at.desc(),
                AgentRunAuthorityModel.id.desc(),
            )
            .limit(1)
        )
    )
    run = run_result.scalar_one_or_none()
    if run is None:
        return ActiveRunResponse(
            conversation_id=conversation.id,
            active_run=None,
            availability="unavailable",
            reason_code="no_active_run",
            authority_revision=0,
        )
    actions: list[Literal["steer_now", "queue_next", "kill_run"]] = [
        "queue_next",
        "kill_run",
    ]
    if run.status == "running":
        actions.insert(0, "steer_now")
    active = ActiveRunProjection(
        id=run.id,
        turn_id=run.message_id,
        tenant_id=conversation.tenant_id,
        project_id=run.project_id,
        conversation_id=run.conversation_id,
        status=run.status,
        revision=run.revision,
        availability="available",
        reason_code=None,
        allowed_actions=actions,
        authority_revision=run.revision,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )
    return ActiveRunResponse(
        conversation_id=conversation.id,
        active_run=active,
        availability="available",
        reason_code=None,
        authority_revision=run.revision,
    )


@router.get(
    "/conversations/{conversation_id}/latest-run",
    response_model=LatestRunResponse,
)
async def get_latest_run(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LatestRunResponse:
    """Return the most recent run for reload-safe Summary and Changes access."""

    conversation_result = await db.execute(
        refresh_select_statement(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == current_user.id,
                exists(
                    select(UserProject.id).where(
                        UserProject.project_id == Conversation.project_id,
                        UserProject.user_id == current_user.id,
                    )
                ),
                exists(
                    select(UserTenant.id).where(
                        UserTenant.tenant_id == Conversation.tenant_id,
                        UserTenant.user_id == current_user.id,
                    )
                ),
            )
        )
    )
    conversation = conversation_result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=403, detail=_("Conversation access denied"))
    run_result = await db.execute(
        refresh_select_statement(
            select(AgentRunAuthorityModel)
            .where(
                AgentRunAuthorityModel.conversation_id == conversation.id,
                AgentRunAuthorityModel.project_id == conversation.project_id,
            )
            .order_by(
                AgentRunAuthorityModel.created_at.desc(),
                AgentRunAuthorityModel.id.desc(),
            )
            .limit(1)
        )
    )
    run = run_result.scalar_one_or_none()
    if run is None:
        return LatestRunResponse(
            conversation_id=conversation.id,
            latest_run=None,
            availability="unavailable",
            reason_code="no_run_recorded",
            authority_revision=0,
        )
    actions: list[Literal["steer_now", "queue_next", "kill_run"]] = []
    if run.status in _ACTIVE_RUN_STATUSES:
        actions.extend(["queue_next", "kill_run"])
        if run.status == "running":
            actions.insert(0, "steer_now")
    latest = ActiveRunProjection(
        id=run.id,
        turn_id=run.message_id,
        tenant_id=conversation.tenant_id,
        project_id=run.project_id,
        conversation_id=run.conversation_id,
        status=run.status,
        revision=run.revision,
        availability="available",
        reason_code=None,
        allowed_actions=actions,
        authority_revision=run.revision,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )
    return LatestRunResponse(
        conversation_id=conversation.id,
        latest_run=latest,
        availability="available",
        reason_code=None,
        authority_revision=run.revision,
    )


@router.get("/runs/{run_id}/summary", response_model=RunSummaryResponse)
async def get_run_summary(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RunSummaryResponse:
    """Return the persisted summary or an explicit legacy partial result."""

    run, conversation = await _load_scoped_run(
        db,
        run_id=run_id,
        user_id=current_user.id,
    )
    result = await db.execute(
        refresh_select_statement(
            select(AgentRunSummaryModel).where(AgentRunSummaryModel.run_id == run.id)
        )
    )
    summary = result.scalar_one_or_none()
    if summary is None:
        return RunSummaryResponse(
            run_id=run.id,
            tenant_id=conversation.tenant_id,
            project_id=run.project_id,
            conversation_id=run.conversation_id,
            status=run.status,
            revision=run.revision,
            summary_state="partial",
            reason_code="summary_not_recorded",
            started_at=None,
            completed_at=None,
            duration_ms=None,
            input_tokens=None,
            output_tokens=None,
            cost_usd=None,
            model_breakdown=[],
            completion_summary=None,
            artifact_count=None,
            checks_passed=None,
            checks_failed=None,
            files_changed=None,
            lines_added=None,
            lines_deleted=None,
            evidence_references=[],
        )
    return RunSummaryResponse(
        run_id=summary.run_id,
        tenant_id=summary.tenant_id,
        project_id=summary.project_id,
        conversation_id=summary.conversation_id,
        status=summary.status,
        revision=summary.revision,
        summary_state=cast(Literal["recorded", "partial"], summary.summary_state),
        reason_code=summary.reason_code,
        started_at=summary.started_at,
        completed_at=summary.completed_at,
        duration_ms=summary.duration_ms,
        input_tokens=summary.input_tokens,
        output_tokens=summary.output_tokens,
        cost_usd=summary.cost_usd,
        model_breakdown=list(summary.model_breakdown_json),
        completion_summary=summary.completion_summary,
        artifact_count=summary.artifact_count,
        checks_passed=summary.checks_passed,
        checks_failed=summary.checks_failed,
        files_changed=summary.files_changed,
        lines_added=summary.lines_added,
        lines_deleted=summary.lines_deleted,
        evidence_references=list(summary.evidence_references_json),
    )


def _change_file_from_payload(payload: dict[str, Any]) -> ChangeFileResponse | None:
    path = payload.get("path") or payload.get("file_path")
    additions = payload.get("additions")
    deletions = payload.get("deletions")
    patch_digest = payload.get("patch_digest")
    hunks = payload.get("hunks")
    if (
        not isinstance(path, str)
        or not isinstance(additions, int)
        or isinstance(additions, bool)
        or not isinstance(deletions, int)
        or isinstance(deletions, bool)
        or not isinstance(patch_digest, str)
        or not isinstance(hunks, list)
    ):
        return None
    try:
        return ChangeFileResponse.model_validate(
            {
                "path": path,
                "old_path": payload.get("old_path"),
                "status": payload.get("status", "modified"),
                "additions": additions,
                "deletions": deletions,
                "binary": payload.get("binary", False),
                "untracked": payload.get("untracked", False),
                "patch_digest": patch_digest,
                "hunks": hunks,
            }
        )
    except ValidationError:
        return None


@router.get("/runs/{run_id}/changes", response_model=RunChangesResponse)
async def get_run_changes(
    run_id: str,
    scope: Literal["turn", "run", "session"] = Query(...),
    turn_id: str | None = Query(default=None),
    expected_revision: int = Query(..., ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RunChangesResponse:
    """Return only structurally attributed file/hunk events for the requested scope."""

    run, _conversation = await _load_scoped_run(
        db,
        run_id=run_id,
        user_id=current_user.id,
    )
    if expected_revision != run.revision:
        raise HTTPException(status_code=409, detail=_("Agent run revision conflict"))
    if scope == "turn" and not turn_id:
        raise HTTPException(status_code=422, detail=_("turn_id is required for turn scope"))
    statement = select(AgentExecutionEvent).where(
        AgentExecutionEvent.conversation_id == run.conversation_id
    )
    if scope == "run":
        statement = statement.where(AgentExecutionEvent.message_id == run.message_id)
    elif scope == "turn":
        statement = statement.where(AgentExecutionEvent.message_id == turn_id)
    result = await db.execute(
        refresh_select_statement(
            statement.order_by(
                AgentExecutionEvent.event_time_us.asc(),
                AgentExecutionEvent.event_counter.asc(),
            )
        )
    )
    events = result.scalars().all()
    changes: list[RunChangeAttribution] = []
    files: list[ChangeFileResponse] = []
    for event in events:
        for payload in _explicit_change_payloads(event):
            file_path = payload.get("file_path") or payload.get("path")
            hunk_id = payload.get("hunk_id")
            changes.append(
                RunChangeAttribution(
                    file_path=file_path if isinstance(file_path, str) else None,
                    hunk_id=hunk_id if isinstance(hunk_id, str) else None,
                    attribution=(
                        "attributed"
                        if isinstance(file_path, str) or isinstance(hunk_id, str)
                        else "unattributed"
                    ),
                    turn_id=event.message_id,
                    event_id=event.id,
                    event_revision=f"{event.event_time_us}:{event.event_counter}",
                    payload=payload,
                )
            )
            change_file = _change_file_from_payload(payload)
            if change_file is not None:
                files.append(change_file)
    environment_raw = run.authorization_snapshot.get("environment")
    environment = environment_raw if isinstance(environment_raw, dict) else {}
    captured_at = (
        max(
            (
                event.created_at.replace(tzinfo=UTC)
                if event.created_at.tzinfo is None
                else event.created_at.astimezone(UTC)
            )
            for event in events
        )
        if events
        else (
            run.updated_at.replace(tzinfo=UTC)
            if run.updated_at.tzinfo is None
            else run.updated_at.astimezone(UTC)
        )
    )
    snapshot_status: Literal["ready", "unattributed"] = "ready" if files else "unattributed"
    reason = None if files else "change_attribution_not_recorded"
    unsigned = {
        "run_id": run.id,
        "conversation_id": run.conversation_id,
        "run_revision": run.revision,
        "environment_id": environment.get("id"),
        "repository_root": environment.get("repository_root"),
        "workspace_path": environment.get("workspace_path"),
        "branch": environment.get("branch"),
        "base_revision": environment.get("base_commit"),
        "head_revision": None,
        "status": snapshot_status,
        "reason": reason,
        "additions": sum(item.additions for item in files),
        "deletions": sum(item.deletions for item in files),
        "files_changed": len(files),
        "truncated": False,
        "captured_at": captured_at.isoformat(),
        "files": [item.model_dump(mode="json") for item in files],
        "scope": scope,
        "turn_id": turn_id,
        "attribution": [item.model_dump(mode="json") for item in changes],
    }
    revision = _canonical_hash(unsigned)
    return RunChangesResponse.model_validate(
        {
            "id": f"cloud-change-{revision[:24]}",
            **unsigned,
            "snapshot_revision": revision,
        }
    )


__all__ = [
    "get_active_run",
    "get_latest_run",
    "get_run_changes",
    "get_run_summary",
    "router",
]
