"""Destructive, idempotent revert of recorded Cloud run changes.

The revert mutates the project sandbox workspace, so it is gated like every
other mutating run operation: scoped run authority, an expected run revision,
a snapshot digest pinned to what the client reviewed, an idempotency key with
a persisted receipt, and an audited V2 operation pin around the sandbox write.
Every failure mode fails closed before a single byte is written.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.agent_run_authority import (
    ChangeFileResponse,
    RevertRunChangesRequest,
    RevertRunChangesResponse,
    RunChangeRevertResult,
)
from src.application.services.agent.run_change_revert import (
    CHANGE_REVERT_EVENT_SOURCE,
    CHANGE_REVERTED_EVENT_TYPE,
    ChangeContentNotRecordedError,
    InvalidSelectorPathError,
    RevertFilePlan,
    RevertScriptResult,
    UnknownChangeSelectorError,
    build_reverse_patch,
    parse_revert_script_output,
    plan_change_revert,
    render_revert_script,
)
from src.domain.model.agent.execution.event_time import EventTimeGenerator
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.sandbox.utils import get_sandbox_adapter
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    AgentRunAuthorityModel,
    ProjectSandbox,
    User,
)
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_agent_turn_operation_v2,
)

from .run_authority_common import _canonical_hash, _load_scoped_run
from .run_review_authority import _compute_changes_snapshot

router = APIRouter()

_ACTIVE_RUN_STATUSES = frozenset({"queued", "running"})
_RECEIPTS_KEY = "change_revert_receipts"
_REVERT_TIMEOUT_SECONDS = 60


def _revert_rejection(
    *,
    status_code: int,
    reason_code: str,
    detail: str,
    run: AgentRunAuthorityModel,
    retryable: bool = False,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "accepted": False,
            "reason_code": reason_code,
            "detail": _(detail),
            "run_id": run.id,
            "run_revision": run.revision,
            "retryable": retryable,
        },
    )


async def _last_event_cursor(db: AsyncSession, conversation_id: str) -> tuple[int, int]:
    result = await db.execute(
        refresh_select_statement(
            select(AgentExecutionEvent.event_time_us, AgentExecutionEvent.event_counter)
            .where(AgentExecutionEvent.conversation_id == conversation_id)
            .order_by(
                AgentExecutionEvent.event_time_us.desc(),
                AgentExecutionEvent.event_counter.desc(),
            )
            .limit(1)
        )
    )
    row = result.first()
    if row is None:
        return 0, 0
    return int(row[0]), int(row[1])


def _response_payload(
    *,
    run: AgentRunAuthorityModel,
    body: RevertRunChangesRequest,
    snapshot_digest: str,
    reverted: list[RunChangeRevertResult],
    head_commit: str | None,
    reverted_at: datetime,
) -> dict[str, Any]:
    return RevertRunChangesResponse(
        created=True,
        run_id=run.id,
        conversation_id=run.conversation_id,
        run_revision=run.revision,
        scope=body.scope,
        turn_id=body.turn_id,
        snapshot_digest=snapshot_digest,
        reverted=reverted,
        head_commit=head_commit,
        idempotency_key=body.idempotency_key,
        reverted_at=reverted_at,
    ).model_dump(mode="json")


async def _execute_revert_in_sandbox(
    *,
    adapter: MCPSandboxAdapter,
    sandbox_id: str,
    script: str,
) -> str:
    result = await adapter.call_tool(
        sandbox_id,
        "bash",
        {
            "command": script,
            "working_dir": "/workspace",
            "timeout": _REVERT_TIMEOUT_SECONDS,
            "_workspace_dir": "/workspace",
        },
        timeout=_REVERT_TIMEOUT_SECONDS + 5,
    )
    content = result.get("content", [])
    if not isinstance(content, list):
        return ""
    return "\n".join(item.get("text", "") for item in content if isinstance(item, dict))


class _RevertRejected(Exception):
    """Carries a structured fail-closed response out of the guard helpers."""

    def __init__(self, response: JSONResponse) -> None:
        super().__init__("run change revert rejected")
        self.response = response


@dataclass(frozen=True)
class _PreparedRevert:
    environment_root: str
    plans: list[RevertFilePlan]
    patch: str
    deletions: list[str]


async def _receipt_replay(
    run: AgentRunAuthorityModel,
    body: RevertRunChangesRequest,
    payload_hash: str,
) -> RevertRunChangesResponse | None:
    receipts_raw = run.authorization_snapshot.get(_RECEIPTS_KEY)
    receipts = receipts_raw if isinstance(receipts_raw, dict) else {}
    existing = receipts.get(body.idempotency_key)
    if not isinstance(existing, dict):
        return None
    if existing.get("payload_hash") != payload_hash:
        raise HTTPException(status_code=409, detail=_("Change revert idempotency conflict"))
    stored = existing.get("response")
    if not isinstance(stored, dict):
        raise HTTPException(status_code=409, detail=_("Change revert receipt conflict"))
    return RevertRunChangesResponse.model_validate({**stored, "created": False})


async def _prepare_revert(
    db: AsyncSession,
    run: AgentRunAuthorityModel,
    body: RevertRunChangesRequest,
) -> _PreparedRevert:
    """Run every fail-closed guard before any workspace write."""

    def reject(
        status_code: int, reason_code: str, detail: str, retryable: bool = False
    ) -> NoReturn:
        raise _RevertRejected(
            _revert_rejection(
                status_code=status_code,
                reason_code=reason_code,
                detail=detail,
                run=run,
                retryable=retryable,
            )
        )

    if run.revision != body.expected_run_revision:
        reject(status.HTTP_409_CONFLICT, "run_revision_conflict", "Agent run revision conflict")
    if run.status in _ACTIVE_RUN_STATUSES:
        reject(
            status.HTTP_409_CONFLICT,
            "run_active",
            "Cannot revert changes while the run is active",
        )
    unsigned, digest = await _compute_changes_snapshot(
        db, run=run, scope=body.scope, turn_id=body.turn_id
    )
    if digest != body.snapshot_digest:
        reject(
            status.HTTP_409_CONFLICT,
            "snapshot_digest_mismatch",
            "Changes snapshot is stale; refresh and retry",
        )
    if unsigned["status"] != "ready":
        reject(
            status.HTTP_409_CONFLICT,
            "changes_snapshot_not_ready",
            "Changes snapshot is not ready for revert",
        )
    environment_root = unsigned.get("repository_root") or unsigned.get("workspace_path")
    if not isinstance(environment_root, str) or not environment_root.startswith("/"):
        reject(
            status.HTTP_409_CONFLICT,
            "run_environment_unavailable",
            "The run has no recorded workspace root",
        )
    files = [ChangeFileResponse.model_validate(item) for item in unsigned["files"]]
    try:
        plans = plan_change_revert(
            files,
            [
                (
                    selector.path,
                    tuple(selector.hunk_indices) if selector.hunk_indices is not None else None,
                )
                for selector in body.selectors
            ],
        )
        patch, deletions = build_reverse_patch(plans)
    except UnknownChangeSelectorError:
        reject(
            status.HTTP_409_CONFLICT,
            "unknown_change_selector",
            "A requested file or hunk is not in this snapshot",
        )
    except InvalidSelectorPathError:
        raise HTTPException(
            status_code=422, detail=_("Selector path is not repository-relative")
        ) from None
    except ChangeContentNotRecordedError:
        reject(
            status.HTTP_409_CONFLICT,
            "change_content_not_recorded",
            "Recorded content cannot reconstruct this change",
        )
    return _PreparedRevert(
        environment_root=environment_root,
        plans=plans,
        patch=patch,
        deletions=deletions,
    )


async def _running_cloud_sandbox(
    db: AsyncSession,
    run: AgentRunAuthorityModel,
) -> ProjectSandbox:
    sandbox: ProjectSandbox | None = (
        await db.execute(
            refresh_select_statement(
                select(ProjectSandbox).where(
                    ProjectSandbox.project_id == run.project_id,
                    ProjectSandbox.tenant_id == run.tenant_id,
                )
            )
        )
    ).scalar_one_or_none()
    if sandbox is None or sandbox.sandbox_type != "cloud" or sandbox.status != "running":
        raise _RevertRejected(
            _revert_rejection(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                reason_code="sandbox_write_unavailable",
                detail="No running Cloud sandbox can accept workspace writes",
                run=run,
                retryable=True,
            )
        )
    return sandbox


async def _apply_revert_script(
    *,
    db: AsyncSession,
    run: AgentRunAuthorityModel,
    body: RevertRunChangesRequest,
    current_user: User,
    sandbox_id: str,
    script: str,
) -> RevertScriptResult:
    """Execute the revert inside the audited V2 operation pin."""

    # The adapter is resolved at call time (not via Depends) so the
    # pinned-generation sandbox authority is consulted inside the audited
    # operation and tests can patch the provider, mirroring the terminal
    # router pattern.
    try:
        async with pin_agent_turn_operation_v2(
            operation_id=f"run-change-revert:{run.id}:{body.idempotency_key}",
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
                    "channel": "run-change-revert",
                    "run_id": run.id,
                    "run_revision": body.expected_run_revision,
                    "idempotency_key": body.idempotency_key,
                },
            },
        ):
            adapter = get_sandbox_adapter()
            output = await _execute_revert_in_sandbox(
                adapter=adapter,
                sandbox_id=sandbox_id,
                script=script,
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise _RevertRejected(
            _revert_rejection(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                reason_code="sandbox_write_unavailable",
                detail="Sandbox workspace write failed; retry",
                run=run,
                retryable=True,
            )
        ) from exc
    outcome = parse_revert_script_output(output)
    if outcome.kind == "ok":
        return outcome
    failure_map = {
        "root_unavailable": (
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "sandbox_write_unavailable",
            "The run workspace root is unavailable in the sandbox",
            True,
        ),
        "check_failed": (
            status.HTTP_409_CONFLICT,
            "revert_patch_conflict",
            "The workspace no longer matches the recorded changes",
            False,
        ),
        "delete_missing": (
            status.HTTP_409_CONFLICT,
            "revert_target_missing",
            "A recorded file to delete no longer exists",
            False,
        ),
    }
    status_code, reason_code, detail, retryable = failure_map.get(
        outcome.kind,
        (
            status.HTTP_502_BAD_GATEWAY,
            "revert_execution_failed",
            "The sandbox did not report a revert outcome",
            True,
        ),
    )
    raise _RevertRejected(
        _revert_rejection(
            status_code=status_code,
            reason_code=reason_code,
            detail=detail,
            run=run,
            retryable=retryable,
        )
    )


def _revert_results(plans: list[RevertFilePlan]) -> list[RunChangeRevertResult]:
    return [
        RunChangeRevertResult(
            path=plan.path,
            patch_digest=plan.patch_digest,
            hunk_indices=(
                None
                if plan.delete_file or len(plan.reverted_indices) == plan.file_hunk_count
                else list(plan.reverted_indices)
            ),
            deleted_file=plan.delete_file or plan.status in {"added", "untracked"},
        )
        for plan in plans
    ]


async def _record_revert_event(
    db: AsyncSession,
    *,
    run: AgentRunAuthorityModel,
    body: RevertRunChangesRequest,
    plans: list[RevertFilePlan],
    head_commit: str | None,
    user_id: str,
    reverted_at: datetime,
) -> None:
    last_time_us, last_counter = await _last_event_cursor(db, run.conversation_id)
    event_time_us, event_counter = EventTimeGenerator(last_time_us, last_counter).next()
    db.add(
        AgentExecutionEvent(
            id=str(uuid.uuid4()),
            conversation_id=run.conversation_id,
            message_id=run.message_id,
            event_type=CHANGE_REVERTED_EVENT_TYPE,
            event_data={
                "source": CHANGE_REVERT_EVENT_SOURCE,
                "run_id": run.id,
                "scope": body.scope,
                "turn_id": body.turn_id,
                "idempotency_key": body.idempotency_key,
                "reverted": [
                    {
                        "path": result.path,
                        "patch_digest": result.patch_digest,
                        "hunk_indices": result.hunk_indices,
                    }
                    for result in _revert_results(plans)
                ],
                "head_commit": head_commit,
                "reverted_by": user_id,
                "reverted_at": reverted_at.isoformat(),
            },
            event_time_us=event_time_us,
            event_counter=event_counter,
            correlation_id=f"run-change-revert:{run.id}:{body.idempotency_key}",
            created_at=reverted_at,
        )
    )


@router.post(
    "/runs/{run_id}/changes/revert",
    response_model=RevertRunChangesResponse,
)
async def revert_run_changes(
    run_id: str,
    body: RevertRunChangesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RevertRunChangesResponse | JSONResponse:
    """Reverse-apply selected recorded changes inside the Cloud sandbox."""

    run, _conversation = await _load_scoped_run(
        db, run_id=run_id, user_id=current_user.id, lock=True
    )
    payload_hash = _canonical_hash(body.model_dump(mode="json"))
    replay = await _receipt_replay(run, body, payload_hash)
    if replay is not None:
        return replay
    try:
        prepared = await _prepare_revert(db, run, body)
        sandbox = await _running_cloud_sandbox(db, run)
        script = render_revert_script(
            repository_root=prepared.environment_root,
            patch=prepared.patch,
            deletions=prepared.deletions,
        )
        outcome = await _apply_revert_script(
            db=db,
            run=run,
            body=body,
            current_user=current_user,
            sandbox_id=sandbox.sandbox_id,
            script=script,
        )
    except _RevertRejected as rejected:
        return rejected.response

    reverted_at = datetime.now(UTC)
    await _record_revert_event(
        db,
        run=run,
        body=body,
        plans=prepared.plans,
        head_commit=outcome.head_commit,
        user_id=current_user.id,
        reverted_at=reverted_at,
    )
    await db.commit()

    _fresh_unsigned, fresh_digest = await _compute_changes_snapshot(
        db, run=run, scope=body.scope, turn_id=body.turn_id
    )
    payload = _response_payload(
        run=run,
        body=body,
        snapshot_digest=fresh_digest,
        reverted=_revert_results(prepared.plans),
        head_commit=outcome.head_commit,
        reverted_at=reverted_at,
    )
    snapshot = dict(run.authorization_snapshot)
    receipts_raw = snapshot.get(_RECEIPTS_KEY)
    receipts: dict[str, Any] = dict(receipts_raw) if isinstance(receipts_raw, dict) else {}
    receipts[body.idempotency_key] = {"payload_hash": payload_hash, "response": payload}
    snapshot[_RECEIPTS_KEY] = receipts
    run.authorization_snapshot = snapshot
    await db.commit()
    return RevertRunChangesResponse.model_validate(payload)


__all__ = ["revert_run_changes", "router"]
